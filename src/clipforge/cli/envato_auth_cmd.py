"""Interactive portal credential enrollment. Secrets never become CLI options."""

from __future__ import annotations

import getpass
import sys
import warnings
from typing import Annotated, NoReturn

import typer

from clipforge.assets.credentials import (
    PortalCredentials,
    PortalCredentialStore,
    credential_doctor_text,
    credential_status_text,
)
from clipforge.assets.mcp_client import AssetError

envato_auth_app = typer.Typer(no_args_is_help=True, help="Store portal login in the Linux OS keyring.")


def _fail(exc: AssetError) -> NoReturn:
    typer.echo(f"{exc.code}: {exc}", err=True)
    raise typer.Exit(1)


def _prompt_secret(label: str) -> str:
    if not sys.stdin.isatty():
        raise AssetError(
            "auth setup requires a real local terminal; do not pipe passwords or paste them into chat",
            code="interactive_terminal_required",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            return getpass.getpass(label)
    except (getpass.GetPassWarning, EOFError, OSError):
        raise AssetError(
            "a non-echoing terminal prompt is unavailable; no credentials were saved",
            code="interactive_terminal_required",
        ) from None


@envato_auth_app.command("setup")
def auth_setup(
    replace: Annotated[bool, typer.Option("--replace", help="Replace the saved portal login.")] = False,
) -> None:
    """Ask once locally, save in OS keyring, and verify retrieval. Does not sign in."""
    try:
        store = PortalCredentialStore()
        if not replace and store.load() is not None:
            raise AssetError(
                "portal credentials are already saved; use auth setup --replace to update them",
                code="credentials_exist",
            )
        username = _prompt_secret("Portal email/username (hidden): ")
        password = _prompt_secret("Portal password (hidden): ")
        if _prompt_secret("Repeat portal password (hidden): ") != password:
            raise AssetError("password confirmation did not match; nothing saved", code="confirmation_mismatch")
        store.save(PortalCredentials(username, password), replace=replace)
    except AssetError as exc:
        _fail(exc)
    typer.echo("credentials: saved_and_readback_verified\nstorage: OS_keyring\nportal_login: not_verified")


@envato_auth_app.command("doctor")
def auth_doctor() -> None:
    """Report local prerequisites without retrieving credentials or contacting a site."""
    typer.echo(credential_doctor_text())


@envato_auth_app.command("status")
def auth_status() -> None:
    """Check keyring entry presence without displaying login details or contacting a site."""
    try:
        typer.echo(credential_status_text())
    except AssetError as exc:
        _fail(exc)


@envato_auth_app.command("forget")
def auth_forget(
    yes: Annotated[
        bool, typer.Option("--yes", help="Delete only Clipforge's saved portal credential.")
    ] = False,
) -> None:
    """Remove the keyring entry. Does not revoke third-party website sessions."""
    if not yes:
        _fail(AssetError("use --yes to forget the saved portal credential", code="confirmation_required"))
    try:
        PortalCredentialStore().forget()
    except AssetError as exc:
        _fail(exc)
    typer.echo("credentials: removed\nremote_logout: not_run")
