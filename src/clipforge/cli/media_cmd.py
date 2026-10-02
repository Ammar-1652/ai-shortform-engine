"""Prepare and verify derived media. Neither command transcribes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.errors import ClipforgeError
from clipforge.media.prepare import prepare_source
from clipforge.media.process import MediaCancelled
from clipforge.media.verify import format_report, verify_source
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

media_app = typer.Typer(no_args_is_help=True, help="Prepare and verify derived media.")


@media_app.command("prepare")
def media_prepare(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Build or reuse the analysis proxy and, when the source has audio, ASR FLAC."""
    try:
        result = prepare_source(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
        )
    except MediaCancelled as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(130) from exc
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(f"job_id: {result.job_id}")
    typer.echo(f"proxy: {result.proxy_path}")
    typer.echo(f"proxy_sha256: {result.proxy_sha256}")
    typer.echo(f"proxy_cache: {'hit' if result.proxy_from_cache else 'miss'}")
    if result.audio_path is None:
        typer.echo("asr_audio: skipped")
    else:
        cache = "hit" if result.audio_from_cache else "miss"
        typer.echo(f"asr_audio: {result.audio_path}")
        typer.echo(f"asr_audio_sha256: {result.audio_sha256}")
        typer.echo(f"asr_audio_cache: {cache}")
    typer.echo(f"storage_estimate_bytes: {result.storage_estimate_bytes}")
    typer.echo(f"ffmpeg: {result.ffmpeg_version}")
    typer.echo("next: clipforge transcript run")


@media_app.command("verify")
def media_verify(
    source_asset_id: Annotated[str, typer.Argument(help="Ingested source id.")],
    db: Annotated[Path | None, typer.Option("--db", help="SQLite database path.")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Report source, rights, proxy, and ASR audio state. Does not repair files."""
    try:
        report = verify_source(
            database=Database(resolve_db_path(db)),
            source_asset_id=source_asset_id,
            work_root=resolve_work_dir(work_dir),
        )
    except ClipforgeError as exc:
        _fail(exc)
    typer.echo(format_report(report))
    if report.status == "FAIL":
        raise typer.Exit(1)


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(f"FAIL: {exc}", err=True)
    raise typer.Exit(1)
