"""Transcript commands. They accept a source id, not an arbitrary audio path."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.errors import ClipforgeError
from clipforge.media.process import MediaCancelled
from clipforge.paths import resolve_db_path, resolve_model_root, resolve_work_dir
from clipforge.storage import Database
from clipforge.transcription.profile import TranscriptionRequest

transcript_app = typer.Typer(
    no_args_is_help=True,
    help="Inspect and run first-pass transcripts from prepared ASR audio.",
)


@transcript_app.command("doctor")
def transcript_doctor(
    model_dir: Annotated[
        Path | None,
        typer.Option("--model-dir", help="Model cache. Defaults to CLIPFORGE_MODEL_ROOT or var/models."),
    ] = None,
) -> None:
    """Report the local ASR runtime. Does not download a model or load weights."""
    from clipforge.transcription.doctor import doctor_status, format_doctor, transcription_doctor

    lines = transcription_doctor(resolve_model_root(model_dir))
    typer.echo(format_doctor(lines))
    if doctor_status(lines) == "FAIL":
        raise typer.Exit(1)


@transcript_app.command("run")
def transcript_run(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id. Not a filesystem audio path.")],
    model: Annotated[
        str,
        typer.Option("--model", help="Model id such as small.en, or an absolute model directory."),
    ] = "small.en",
    language: Annotated[
        str,
        typer.Option("--language", help="Language code such as en, or auto. Not translation."),
    ] = "en",
    device: Annotated[
        str,
        typer.Option("--device", help="auto, cpu, or cuda. cuda does not fall back to cpu."),
    ] = "auto",
    compute_type: Annotated[
        str,
        typer.Option("--compute-type", help="auto or a CTranslate2 compute type."),
    ] = "auto",
    allow_model_download: Annotated[
        bool,
        typer.Option(
            "--allow-model-download",
            help="Permit fetching a missing model. Otherwise do not download.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Ignore a valid transcript cache and run again."),
    ] = False,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
    model_dir: Annotated[Path | None, typer.Option("--model-dir", help="Model cache directory.")] = None,
) -> None:
    """Run a first-pass transcript on the source's prepared ASR audio.

    Word timestamps are provisional. Translation is not available. A model
    download happens only when --allow-model-download is set and the model
    is not already cached.
    """
    from clipforge.transcription.service import transcribe_source

    def progress(percent: int) -> None:
        typer.echo(f"progress: {percent}%")

    try:
        result = transcribe_source(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            model_root=resolve_model_root(model_dir),
            request=TranscriptionRequest(
                model=model,
                language=language,
                device=device,
                compute_type=compute_type,
                allow_model_download=allow_model_download,
                force=force,
            ),
            progress=progress,
        )
    except MediaCancelled as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(130) from exc
    except ClipforgeError as exc:
        _fail(exc)
    if result.warning:
        typer.echo(f"warning: {result.warning}")
    typer.echo(f"job_id: {result.job_id}")
    typer.echo(f"transcript_id: {result.transcript_id}")
    typer.echo(f"source_asset_id: {result.source_asset_id}")
    typer.echo(f"model: {result.model_requested}")
    typer.echo(f"model_revision: {result.model_revision}")
    typer.echo(f"device: {result.device}")
    typer.echo(f"compute_type: {result.compute_type}")
    typer.echo(f"language: {result.language_requested}")
    typer.echo(f"detected_language: {result.detected_language}")
    typer.echo(f"language_probability: {result.language_probability}")
    typer.echo(f"segments: {result.segment_count}")
    typer.echo(f"words: {result.word_count}")
    typer.echo(f"speech_detected: {'yes' if result.speech_detected else 'no'}")
    typer.echo(f"canonical_duration_us: {result.canonical_duration_us}")
    typer.echo(f"cache: {'hit' if result.cache_hit else 'miss'}")
    typer.echo(f"transcript: {result.transcript_path}")
    typer.echo(f"transcript_sha256: {result.transcript_sha256}")
    if result.model_load_seconds is not None:
        typer.echo(f"model_load_seconds: {result.model_load_seconds:.3f}")
    if result.inference_seconds is not None:
        typer.echo(f"inference_seconds: {result.inference_seconds:.3f}")
    if result.real_time_factor is not None:
        typer.echo(f"real_time_factor: {result.real_time_factor:.3f}")


@transcript_app.command("show")
def transcript_show(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print the canonical transcript document.")] = False,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Print a stored transcript. Does not load a model or contact the network."""
    from clipforge.transcription.show import format_transcript, load_transcript

    try:
        document = load_transcript(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
        )
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(format_transcript(document, as_json=as_json))


@transcript_app.command("verify")
def transcript_verify(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
    model_dir: Annotated[
        Path | None,
        typer.Option("--model-dir", help="Model cache checked only for a warning."),
    ] = None,
) -> None:
    """Check a stored transcript. Does not load a model, download, or repair files."""
    from clipforge.transcription.verify import format_transcript_report, verify_transcript

    try:
        report = verify_transcript(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
            model_root=resolve_model_root(model_dir),
        )
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(format_transcript_report(report))
    if report.status == "FAIL":
        raise typer.Exit(1)


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(f"FAIL: {exc}", err=True)
    raise typer.Exit(1)
