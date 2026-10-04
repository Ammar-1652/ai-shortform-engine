"""Platform adapter commands. These do not upload unless live smoke is enabled."""

from __future__ import annotations

from typing import NoReturn

import typer

from clipforge.errors import ClipforgeError
from clipforge.platform.service import capabilities_text, doctor_text

platform_app = typer.Typer(no_args_is_help=True, help="Inspect the optional platform adapter.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@platform_app.command("doctor")
def platform_doctor() -> None:
    """Report whether an adapter exists and whether upload is configured."""
    try:
        typer.echo(doctor_text())
    except ClipforgeError as exc:
        _fail(exc)


@platform_app.command("capabilities")
def platform_capabilities() -> None:
    """Print the local adapter capabilities. This does not contact a platform."""
    try:
        typer.echo(capabilities_text())
    except ClipforgeError as exc:
        _fail(exc)
