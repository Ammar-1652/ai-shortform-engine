"""Profile commands. list, show, and verify only read configuration."""

from __future__ import annotations

from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.policy.loader import PolicyError, load_catalog, resolve_profile

profile_app = typer.Typer(no_args_is_help=True, help="Inspect campaign profiles and policies.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@profile_app.command("doctor")
def profile_doctor() -> None:
    """Report config roots, profiles, and policies. This does not download anything."""
    try:
        catalog = load_catalog()
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)
    typer.echo("PASS config_root: configs/profiles")
    typer.echo("PASS config_root: configs/policies")
    for profile_id in sorted(catalog.profiles):
        typer.echo(f"PASS profile: {profile_id}")
    for policy_id in sorted(catalog.policies):
        typer.echo(f"PASS policy: {policy_id}")


@profile_app.command("list")
def profile_list() -> None:
    """List profile ids. Does not write."""
    try:
        catalog = load_catalog()
    except ClipforgeError as exc:
        _fail(exc)
    for profile_id in sorted(catalog.profiles):
        profile = catalog.profiles[profile_id]
        typer.echo(f"{profile.profile_id}\t{profile.mode.value}\t{profile.name}")


@profile_app.command("show")
def profile_show(profile_id: Annotated[str, typer.Argument()]) -> None:
    """Show one resolved profile and its policy hashes. Does not write."""
    try:
        resolved = resolve_profile(profile_id)
    except (PolicyError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"profile_id: {resolved.profile_id}")
    typer.echo(f"name: {resolved.name}")
    typer.echo(f"mode: {resolved.mode}")
    typer.echo(f"objective: {resolved.objective}")
    typer.echo(f"profile_sha256: {resolved.profile_sha256}")
    for policy in resolved.policies:
        typer.echo(f"policy: {policy.policy_id} sha256 {policy.sha256}")


@profile_app.command("verify")
def profile_verify(profile_id: Annotated[str, typer.Argument()]) -> None:
    """Check that a profile and its policies resolve. Does not write."""
    try:
        resolved = resolve_profile(profile_id)
    except (PolicyError, ValidationError) as exc:
        _fail(exc)
    typer.echo(f"PASS profile {resolved.profile_id}")
