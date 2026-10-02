"""Local source inspection and ingest. Ingest does not prepare derivatives."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.errors import ClipforgeError
from clipforge.media.ingest import ingest_source
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.probe import probe_file
from clipforge.media.process import ProcessRunner
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import (
    Database,
    get_asset_license_record,
    get_source_asset,
    get_source_manifest,
    list_source_assets,
)

source_app = typer.Typer(no_args_is_help=True, help="Inspect and register local video files.")


@source_app.command("inspect")
def source_inspect(
    path: Annotated[str, typer.Argument(help="Local video file. URLs are rejected.")],
) -> None:
    """Probe a local file and print the automatic stream choice. Does not write a database row."""
    from clipforge.media.local_file import require_local_media_file

    try:
        media = require_local_media_file(path)
        _raw, probe = probe_file(
            media,
            ProcessRunner(),
            video_override=None,
            audio_override=None,
            log_path=None,
        )
    except ClipforgeError as exc:
        _fail(exc)
    video = next(stream for stream in probe.video_streams if stream.index == probe.selection.video_stream_index)
    typer.echo(f"path: {media}")
    typer.echo(f"format: {probe.format.format_name or 'unknown'}")
    typer.echo(f"ffprobe: {probe.ffprobe_version}")
    typer.echo(f"video_streams: {len(probe.video_streams)}")
    typer.echo(f"audio_streams: {len(probe.audio_streams)}")
    typer.echo(f"chapters: {probe.chapter_count}")
    typer.echo(
        f"selected_video: {probe.selection.video_stream_index} ({probe.selection.video_selection}) "
        f"{video.codec_name or 'unknown'} {video.width}x{video.height} "
        f"display {video.display_width}x{video.display_height}"
    )
    typer.echo(
        "selected_audio: "
        + (
            "none"
            if probe.selection.audio_stream_index is None
            else f"{probe.selection.audio_stream_index} ({probe.selection.audio_selection})"
        )
    )
    typer.echo(f"avg_frame_rate: {_ratio(video.avg_frame_rate)}")
    typer.echo(f"r_frame_rate: {_ratio(video.r_frame_rate)}")
    typer.echo(f"frame_timing: {probe.classification.frame_timing.value}")
    typer.echo(f"hdr: {probe.classification.hdr.value}")
    rotation = "unknown" if video.rotation.degrees is None else str(video.rotation.degrees)
    typer.echo(f"rotation_degrees: {rotation}")
    typer.echo(f"video_origin_us: {probe.timeline.video_origin_us}")
    typer.echo(f"video_start_assumed_zero: {probe.timeline.video_start_assumed_zero}")
    typer.echo(f"audio_offset_us: {probe.timeline.audio_offset_us}")
    typer.echo(f"canonical_duration_us: {probe.timeline.canonical_duration_us}")
    typer.echo(f"duration_evidence: {probe.timeline.duration_evidence}")
    typer.echo(f"transcription_eligible: {probe.classification.transcription_eligible}")
    if probe.classification.transcription_eligible:
        typer.echo("note: inspection did not transcribe this file")


@source_app.command("ingest")
def source_ingest(
    project_id: Annotated[str, typer.Argument(help="Existing project id.")],
    path: Annotated[str, typer.Argument(help="Local video file.")],
    rights_status: Annotated[
        str, typer.Option("--rights-status", help="owned, licensed, or campaign_provided.")
    ],
    rights_evidence: Annotated[
        str, typer.Option("--rights-evidence", help="Local evidence file or http(s) reference.")
    ],
    rights_name: Annotated[str, typer.Option("--rights-name", help="Your label for the rights assertion.")],
    confirm_rights: Annotated[
        bool,
        typer.Option("--confirm-rights", help="Record that you assert these rights. Not a legal verification."),
    ] = False,
    video_stream: Annotated[
        int | None,
        typer.Option("--video-stream", help="ffprobe stream index. Invalid values fail."),
    ] = None,
    audio_stream: Annotated[
        int | None,
        typer.Option("--audio-stream", help="ffprobe stream index. Invalid values fail."),
    ] = None,
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Register a local file on a project. Does not build a proxy or an ASR audio file."""
    try:
        result = ingest_source(
            database=Database(resolve_db_path(db)),
            project_id=project_id,
            source=path,
            rights_status=rights_status,
            rights_evidence=rights_evidence,
            rights_name=rights_name,
            confirm_rights=confirm_rights,
            work_root=resolve_work_dir(work_dir),
            video_stream=video_stream,
            audio_stream=audio_stream,
        )
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(f"source_asset_id: {result.source_asset_id}")
    typer.echo(f"deduplicated: {'yes' if result.deduplicated else 'no'}")
    typer.echo(f"content_sha256: {result.content_sha256}")
    typer.echo(f"storage_mode: {result.storage_mode}")
    typer.echo(f"video_stream: {result.video_stream_index}")
    audio = "none" if result.audio_stream_index is None else str(result.audio_stream_index)
    typer.echo(f"audio_stream: {audio}")
    typer.echo(f"canonical_duration_us: {result.canonical_duration_us}")
    typer.echo(f"video_origin_us: {result.video_origin_us}")
    typer.echo(f"audio_offset_us: {result.audio_offset_us}")
    typer.echo(f"transcription_eligible: {'yes' if result.transcription_eligible else 'no'}")
    typer.echo(f"frame_timing: {result.frame_timing}")
    typer.echo(f"hdr: {result.hdr}")
    typer.echo(f"filename: {result.original_filename}")


@source_app.command("list")
def source_list(
    project_id: Annotated[str, typer.Argument(help="Project id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
) -> None:
    """List sources in one project. Mutation state uses size and mtime, not a rehash."""
    try:
        database = Database(resolve_db_path(db))
        with database.connect() as connection:
            assets = list_source_assets(connection, project_id)
            rows = [(asset, get_source_manifest(connection, asset.source_asset_id)) for asset in assets]
            licenses = {
                asset.source_asset_id: get_asset_license_record(connection, asset.license_record_id)
                for asset in assets
            }
    except ClipforgeError as exc:
        _fail(exc)
    if not rows:
        typer.echo("No sources.")
        return
    for asset, manifest in rows:
        license_record = licenses[asset.source_asset_id]
        mutation = _cheap_mutation(path_from_file_uri(asset.uri), manifest.size_bytes, manifest.mtime_ns)
        audio = "none" if manifest.audio_stream_index is None else str(manifest.audio_stream_index)
        typer.echo(
            f"{manifest.source_asset_id}\t{manifest.original_filename}\t{manifest.content_sha256}\t"
            f"{manifest.canonical_duration_us}\tv{manifest.video_stream_index}\ta{audio}\t"
            f"{license_record.status.value}\t"
            f"{'yes' if manifest.transcription_eligible else 'no'}\t"
            f"{manifest.ingested_at.isoformat()}\t{mutation}"
        )


@source_app.command("show")
def source_show(
    source_asset_id: Annotated[str, typer.Argument(help="Source asset id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
) -> None:
    """Show one source. Does not rehash when size and mtime still match."""
    try:
        database = Database(resolve_db_path(db))
        with database.connect() as connection:
            asset = get_source_asset(connection, source_asset_id)
            manifest = get_source_manifest(connection, source_asset_id)
            license_record = get_asset_license_record(connection, asset.license_record_id)
        path = path_from_file_uri(asset.uri)
        mutation = _cheap_mutation(path, manifest.size_bytes, manifest.mtime_ns)
    except ClipforgeError as exc:
        _fail(exc)
    audio = "none" if manifest.audio_stream_index is None else str(manifest.audio_stream_index)
    typer.echo(f"source_asset_id: {manifest.source_asset_id}")
    typer.echo(f"project_id: {manifest.project_id}")
    typer.echo(f"path: {path}")
    typer.echo(f"filename: {manifest.original_filename}")
    typer.echo(f"content_sha256: {manifest.content_sha256}")
    typer.echo(f"storage_mode: {manifest.storage_mode}")
    typer.echo(f"size_bytes: {manifest.size_bytes}")
    typer.echo(f"canonical_duration_us: {manifest.canonical_duration_us}")
    typer.echo(f"video_stream: {manifest.video_stream_index}")
    typer.echo(f"audio_stream: {audio}")
    typer.echo(f"video_origin_us: {manifest.video_origin_us}")
    typer.echo(f"audio_offset_us: {manifest.probe.timeline.audio_offset_us}")
    typer.echo(f"rights_status: {license_record.status.value}")
    typer.echo(f"transcription_eligible: {'yes' if manifest.transcription_eligible else 'no'}")
    typer.echo(f"ingested_at: {manifest.ingested_at.isoformat()}")
    typer.echo(f"mutation: {mutation}")
    typer.echo(f"frame_timing: {manifest.probe.classification.frame_timing.value}")
    typer.echo(f"hdr: {manifest.probe.classification.hdr.value}")


def _cheap_mutation(path: Path, size_bytes: int, mtime_ns: int) -> str:
    if not path.is_file():
        return "missing"
    stat = path.stat()
    if stat.st_size == size_bytes and stat.st_mtime_ns == mtime_ns:
        return "unchanged"
    return "stat_differs"


def _ratio(value: object) -> str:
    if value is None:
        return "unknown"
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if isinstance(numerator, int) and isinstance(denominator, int):
        return f"{numerator}/{denominator}"
    return "unknown"


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(f"FAIL: {exc}", err=True)
    raise typer.Exit(1)
