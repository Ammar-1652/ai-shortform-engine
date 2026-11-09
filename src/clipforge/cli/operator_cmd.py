"""Read-only capability discovery for a new production operator."""

import json
from pathlib import Path
from typing import Annotated

import typer

from clipforge.errors import ClipforgeError
from clipforge.operator.catalogue import CAPABILITIES, EXTENSIONS, capability, role_policy, validate_catalogue

operator_app = typer.Typer(
    no_args_is_help=True, help="Discover operator roles, tools and extension boundaries."
)
release_app = typer.Typer(no_args_is_help=True, help="Capture and verify local executable release snapshots.")
operator_app.add_typer(release_app, name="release")


@release_app.command("capture")
def release_capture(work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None) -> None:
    """Pin current code and dependencies, including relevant uncommitted files."""
    from clipforge.operator.release import save_release
    from clipforge.paths import resolve_work_dir

    try:
        typer.echo(save_release(resolve_work_dir(work_dir)).model_dump_json(indent=2))
    except (ClipforgeError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@release_app.command("verify")
def release_verify(
    release_id: str, work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None
) -> None:
    """Read-only verification against the current source and dependency inventory."""
    from clipforge.operator.release import verify_release
    from clipforge.paths import resolve_work_dir

    try:
        release = verify_release(resolve_work_dir(work_dir), release_id)
        typer.echo(f"verified_release: {release.release_id}")
    except (ClipforgeError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@operator_app.command("roles")
def roles() -> None:
    """Print the responsibility policy. Does not grant approval."""
    typer.echo(role_policy().model_dump_json(indent=2))


@operator_app.command("tools")
def tools() -> None:
    """List existing tools with prerequisites, outputs, owner, and limitations."""
    typer.echo(json.dumps([item.model_dump(mode="json") for item in CAPABILITIES], indent=2))


@operator_app.command("show")
def show(name: Annotated[str, typer.Argument(help="Capability id from operator tools.")]) -> None:
    """Show one tool's handoff contract; inspect its --help before invoking it."""
    try:
        typer.echo(capability(name).model_dump_json(indent=2))
    except ClipforgeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@operator_app.command("extensions")
def extensions() -> None:
    """Show the approved locations for new tools, skills, assets, and providers."""
    typer.echo(json.dumps([item.model_dump(mode="json") for item in EXTENSIONS], indent=2))


@operator_app.command("verify")
def verify() -> None:
    """Verify that advertised tools exist. Does not run media or provider calls."""
    from typer.main import get_command

    from clipforge.cli.main import app

    try:
        validate_catalogue(get_command(app))
    except ClipforgeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"verified_capabilities: {len(CAPABILITIES)}; external/live readiness: not_claimed")
