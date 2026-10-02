"""Report work-root disk space and the configured reserve."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from clipforge.errors import ClipforgeError
from clipforge.media.disk import format_bytes, read_disk
from clipforge.paths import resolve_work_dir

storage_app = typer.Typer(no_args_is_help=True, help="Show derived-media disk space.")


@storage_app.command("status")
def storage_status(
    work_dir: Annotated[Path | None, typer.Option("--work-dir", help="Derived-media work root.")] = None,
) -> None:
    """Print free space and the reserve. Does not change files."""
    root = resolve_work_dir(work_dir)
    try:
        status = read_disk(root)
    except ClipforgeError as exc:
        typer.echo(f"FAIL: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"work_root: {status.work_root}")
    typer.echo(f"filesystem: {status.filesystem}")
    typer.echo(f"total: {format_bytes(status.total_bytes)}")
    typer.echo(f"used: {format_bytes(status.used_bytes)}")
    typer.echo(f"free: {format_bytes(status.free_bytes)}")
    typer.echo(f"reserve: {format_bytes(status.reserve_bytes)}")
    typer.echo(f"usable: {format_bytes(status.usable_bytes)}")
