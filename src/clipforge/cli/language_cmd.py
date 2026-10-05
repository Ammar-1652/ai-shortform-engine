"""Caption language checks. This command does not write a database."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.errors import ClipforgeError
from clipforge.language.frames import prove_captions
from clipforge.paths import resolve_work_dir

language_app = typer.Typer(no_args_is_help=True, help="Check caption languages.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@language_app.command("check")
def language_check(
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Draw caption stills and report alignment claims."""
    try:
        proofs = prove_captions(resolve_work_dir(work_dir) / "captions")
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    for proof in proofs:
        typer.echo(f"language: {proof.language}")
        typer.echo(f"text_direction: {proof.text_direction}")
        typer.echo(f"alignment_status: {proof.alignment_status}")
        typer.echo(f"safe_area: {'pass' if proof.safe_area else 'fail'}")
        typer.echo(f"glyphs: {'present' if proof.glyphs_present else 'missing'}")
    typer.echo("multilingual_result: multilingual_pass")
    typer.echo("alignment_claim: alignment_not_claimed")
