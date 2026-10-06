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
from clipforge.voice.plan import build_plan, load_plan, render_plan, verify_plan, write_plan
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


@voice_app.command("languages")
def voice_languages() -> None:
    """List narration languages. This command does not write."""
    from clipforge.language.service import languages_text

    typer.echo(languages_text())


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


@voice_app.command("plan")
def voice_plan(
    source_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    script: Annotated[str, typer.Option("--script")],
    language: Annotated[str, typer.Option("--language")] = "en-US",
    reason: Annotated[str, typer.Option("--reason")] = "operator has not requested narration",
    enabled: Annotated[bool, typer.Option("--enabled")] = False,
    project_id: Annotated[str, typer.Option("--project")] = "project-1",
    provider: Annotated[str, typer.Option("--provider")] = "fake",
    engine_id: Annotated[str | None, typer.Option("--engine")] = None,
    model_id: Annotated[str | None, typer.Option("--model")] = None,
    model_revision: Annotated[str | None, typer.Option("--model-revision")] = None,
    voice_id: Annotated[str | None, typer.Option("--voice")] = None,
    provider_version: Annotated[str | None, typer.Option("--provider-version")] = None,
    model_license: Annotated[str | None, typer.Option("--model-license")] = None,
    commercial_use: Annotated[str | None, typer.Option("--commercial-use")] = None,
    output_use: Annotated[str | None, typer.Option("--output-use")] = None,
    license_evidence_id: Annotated[str | None, typer.Option("--license-evidence")] = None,
    consent_record_id: Annotated[str | None, typer.Option("--consent-record")] = None,
    sample_rate: Annotated[int | None, typer.Option("--sample-rate")] = None,
    channels: Annotated[int | None, typer.Option("--channels")] = None,
    target_duration_us: Annotated[int, typer.Option("--target-duration-us")] = 1_000_000,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Write a narration plan. This does not generate audio."""
    try:
        plan = build_plan(
            project_id=project_id,
            source_asset_id=source_id,
            candidate_id=candidate_id,
            script_text=script,
            language=language,
            enabled=enabled,
            operator_reason=reason,
            provider=provider,
            voice_id=voice_id or "voice-1",
            model_id=model_id or "fake-model",
            model_license=model_license or "allowed",
            engine_id=engine_id,
            model_revision=model_revision,
            provider_version=provider_version,
            commercial_use=commercial_use,
            output_use=output_use,
            license_evidence_id=license_evidence_id,
            consent_record_id=consent_record_id,
            sample_rate=sample_rate,
            channels=channels,
            target_duration_us=target_duration_us,
        )
        path = write_plan(resolve_work_dir(work_dir), plan)
    except (ClipforgeError, ValidationError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"plan: {path.name}")
    typer.echo(f"enabled: {str(plan.enabled).lower()}")
    typer.echo(f"campaign_policy_decision: {plan.campaign_policy_decision}")


@voice_app.command("render")
def voice_render_cmd(
    source_id: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str, typer.Argument()],
    script: Annotated[str, typer.Option("--script")],
    provider: Annotated[str, typer.Option("--provider")] = "fake",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Generate audio only when the saved plan is enabled."""
    root = resolve_work_dir(work_dir)
    path = root / "voice" / source_id / f"{candidate_id}.json"
    try:
        plan = load_plan(path)
        updated = render_plan(
            Database(resolve_db_path(db)),
            root,
            plan,
            _provider(provider),  # type: ignore[arg-type]
            script_text=script,
        )
        write_plan(root, updated)
    except (ClipforgeError, ValidationError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(f"enabled: {str(updated.enabled).lower()}")
    if updated.generated_audio_sha256:
        typer.echo(f"audio_sha256: {updated.generated_audio_sha256}")
    else:
        typer.echo("audio: not_run")


@voice_app.command("verify")
def voice_verify(
    source_or_artifact: Annotated[str, typer.Argument()],
    candidate_id: Annotated[str | None, typer.Argument()] = None,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Check one narration asset or a saved plan. Does not generate audio."""
    database = Database(resolve_db_path(db))
    root = resolve_work_dir(work_dir)
    try:
        if candidate_id is None:
            typer.echo(verify_narration(database, root, source_or_artifact))
            return
        plan = load_plan(root / "voice" / source_or_artifact / f"{candidate_id}.json")
        typer.echo(verify_plan(database, root, plan))
    except (ClipforgeError, ValidationError, OSError, ValueError) as exc:
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
