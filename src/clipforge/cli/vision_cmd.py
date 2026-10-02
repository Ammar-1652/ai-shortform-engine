"""Vision commands. They accept a source id, not an arbitrary video path.

Faces are detections only. Speaker attribution is not performed. Candidate
mining is not performed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_model_root, resolve_work_dir
from clipforge.storage import Database

_LIMITS = "Faces are detections only. Speaker attribution is not performed. Candidate mining is not performed."

vision_app = typer.Typer(no_args_is_help=True, help=f"Record scene, frame, and face evidence. {_LIMITS}")
model_app = typer.Typer(no_args_is_help=True, help=f"Inspect or fetch the face detector model. {_LIMITS}")
vision_app.add_typer(model_app, name="model")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@vision_app.command("doctor")
def vision_doctor_command(
    model_dir: Annotated[
        Path | None,
        typer.Option("--model-dir", help="Model cache. Defaults to CLIPFORGE_MODEL_ROOT or var/models."),
    ] = None,
    work_dir: Annotated[
        Path | None,
        typer.Option("--work-dir", help="Work root used for the disk report."),
    ] = None,
) -> None:
    """Report visual-analysis libraries. Does not download or load a face model.

    Faces are detections only. Speaker attribution is not performed. Candidate
    mining is not performed.
    """
    from clipforge.vision.doctor import doctor_status, format_doctor, vision_doctor

    lines = vision_doctor(resolve_model_root(model_dir), resolve_work_dir(work_dir))
    typer.echo(format_doctor(lines))
    if doctor_status(lines) == "FAIL":
        raise typer.Exit(1)


@model_app.command("status")
def model_status(
    model_dir: Annotated[Path | None, typer.Option("--model-dir", help="Model cache directory.")] = None,
) -> None:
    """Show whether the face detector model is cached. Read-only.

    Faces are detections only. Speaker attribution is not performed. Candidate
    mining is not performed.
    """
    from clipforge.vision.models import face_model_is_cached, face_model_path, face_model_sha256

    root = resolve_model_root(model_dir)
    if face_model_is_cached(root):
        digest = face_model_sha256(root)
        typer.echo(f"cached: yes\npath: {face_model_path(root)}\nsha256: {digest}")
        return
    typer.echo(f"cached: no\npath: {face_model_path(root)}")


@model_app.command("fetch")
def model_fetch(
    name: Annotated[str, typer.Argument(help="Only face-detector is supported.")],
    allow_model_download: Annotated[
        bool,
        typer.Option("--allow-model-download", help="Permit fetching the official model."),
    ] = False,
    model_dir: Annotated[Path | None, typer.Option("--model-dir", help="Model cache directory.")] = None,
) -> None:
    """Fetch the official MediaPipe face detector. No download without the flag.

    Faces are detections only. Speaker attribution is not performed. Candidate
    mining is not performed.
    """
    from clipforge.vision.models import ensure_face_model

    if name != "face-detector":
        _fail(ClipforgeError("only `face-detector` can be fetched in Round 4"))
    try:
        model = ensure_face_model(resolve_model_root(model_dir), allow_download=allow_model_download)
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(f"filename: {model.filename}")
    typer.echo(f"sha256: {model.sha256}")
    typer.echo(f"bytes: {model.size_bytes}")
    typer.echo(f"path: {model.path}")


@vision_app.command("analyze")
def vision_analyze(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem path.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Ignore a valid visual cache and analyze again."),
    ] = False,
    allow_model_download: Annotated[
        bool,
        typer.Option("--allow-model-download", help="Permit fetching a missing face detector model."),
    ] = False,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
    model_dir: Annotated[Path | None, typer.Option("--model-dir", help="Model cache directory.")] = None,
) -> None:
    """Analyze the source's analysis proxy. Faces are detections only.

    Speaker attribution is not performed. Candidate mining is not performed.
    A missing proxy is not prepared automatically.
    """
    from clipforge.vision.service import analyze_source

    try:
        result = analyze_source(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            model_root=resolve_model_root(model_dir),
            allow_model_download=allow_model_download,
            force=force,
        )
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"job_id: {result.job_id}")
    typer.echo(f"analysis_id: {result.analysis_id}")
    typer.echo(f"source_asset_id: {result.source_asset_id}")
    typer.echo(f"proxy_sha256: {result.proxy_sha256}")
    typer.echo(f"scene_count: {result.scene_count}")
    typer.echo(f"representative_frames: {result.representative_frame_count}")
    typer.echo(f"face_sampled_frames: {result.face_sample_frame_count}")
    typer.echo(f"face_detections: {result.face_detection_count}")
    typer.echo(f"face_tracks: {result.face_track_count}")
    typer.echo(f"contact_sheets: {result.contact_sheet_count}")
    typer.echo(f"analysis_path: {result.analysis_path}")
    typer.echo(f"analysis_sha256: {result.analysis_sha256}")
    typer.echo(f"cache: {'hit' if result.cache_hit else 'miss'}")
    typer.echo(f"runtime_seconds: {result.runtime_seconds:.3f}")
    if result.warning:
        typer.echo(f"warning: {result.warning}")


@vision_app.command("show")
def vision_show(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    json_output: Annotated[bool, typer.Option("--json", help="Print the canonical document.")] = False,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Show the stored visual analysis. Does not decode video or load a model.

    Faces are detections only. Speaker attribution is not performed. Candidate
    mining is not performed.
    """
    from clipforge.transcription.io import dump_json
    from clipforge.vision.show import format_visual_analysis, load_visual_analysis

    try:
        document = load_visual_analysis(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
        )
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(dump_json(document) if json_output else format_visual_analysis(document))


@vision_app.command("verify")
def vision_verify(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
    model_dir: Annotated[Path | None, typer.Option("--model-dir", help="Model cache directory.")] = None,
) -> None:
    """Check stored visual evidence. Read-only. Does not repair or load a model.

    Faces are detections only. Speaker attribution is not performed. Candidate
    mining is not performed.
    """
    from clipforge.vision.verify import verify_vision

    report = verify_vision(
        database=Database(resolve_db_path(db)),
        source_asset_id=source_asset_id,
        work_root=resolve_work_dir(work_dir),
        model_root=resolve_model_root(model_dir),
    )
    for line in report.lines:
        typer.echo(f"{line.status} {line.name}: {line.detail}")
    if report.status == "FAIL":
        raise typer.Exit(1)
