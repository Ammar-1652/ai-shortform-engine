"""Optional narration commands. doctor, capabilities, list, and verify do not generate audio."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.schemas.voice import NarrationRequest
from clipforge.storage import Database
from clipforge.voice.provider import FakeVoiceProvider, provider_from_env
from clipforge.voice.service import (
    capability_text,
    doctor_text,
    generate_narration,
    list_narration,
    verify_narration,
)

voice_app = typer.Typer(no_args_is_help=True, help="Optional local narration.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


def _provider(name: str) -> FakeVoiceProvider | object:
    if name == "fake":
        return FakeVoiceProvider()
    if name == "voicestudio":
        return provider_from_env()
    _fail(ClipforgeError("voice provider must be fake or voicestudio"))


@voice_app.command("doctor")
def voice_doctor(
    provider: Annotated[str, typer.Option("--provider")] = "voicestudio",
) -> None:
    """Report whether narration is required. A disabled provider is not a failure."""
    try:
        typer.echo(doctor_text(_provider(provider)))  # type: ignore[arg-type]
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@voice_app.command("capabilities")
def voice_capabilities(
    provider: Annotated[str, typer.Option("--provider")] = "voicestudio",
) -> None:
    """Show provider capabilities. A disabled provider makes no request."""
    try:
        typer.echo(capability_text(_provider(provider)))  # type: ignore[arg-type]
    except (ClipforgeError, OSError) as exc:
        _fail(exc)


@voice_app.command("generate")
def voice_generate(
    request_path: Annotated[Path, typer.Option("--request")],
    provider: Annotated[str, typer.Option("--provider")] = "fake",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Generate one narration asset from an explicit request."""
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        request = NarrationRequest.model_validate(payload)
        document = generate_narration(
            Database(resolve_db_path(db)),
            resolve_work_dir(work_dir),
            request,
            _provider(provider),  # type: ignore[arg-type]
        )
    except (ClipforgeError, ValidationError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(exc)
    typer.echo(f"artifact_id: {document.artifact_id}")
    typer.echo(f"audio_sha256: {document.audio_sha256}")


@voice_app.command("verify")
def voice_verify(
    artifact_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check one narration asset. Does not generate audio."""
    try:
        typer.echo(verify_narration(Database(resolve_db_path(db)), resolve_work_dir(work_dir), artifact_id))
    except (ClipforgeError, ValidationError) as exc:
        _fail(exc)


@voice_app.command("list")
def voice_list(
    project_id: Annotated[str, typer.Argument()],
    db: Annotated[Path | None, typer.Option("--db")] = None,
) -> None:
    """List narration assets. Does not generate audio."""
    try:
        rows = list_narration(Database(resolve_db_path(db)), project_id)
    except ClipforgeError as exc:
        _fail(exc)
    if not rows:
        typer.echo("No narration assets are stored.")
        return
    for item in rows:
        typer.echo(item)
