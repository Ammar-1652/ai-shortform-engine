"""Narration stays off until the operator enables it for one candidate."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from clipforge.campaign.policy import evaluate_mode
from clipforge.language.matrix import require_language
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.voice import NarrationPlan, NarrationRequest, VoiceProviderProfile
from clipforge.voice.audio import VoiceError
from clipforge.voice.provider import VoiceProvider
from clipforge.voice.service import generate_narration, verify_narration

_FAKE_ENGINE = "fake-engine"
_FAKE_REVISION = "rev-1"
_FAKE_EVIDENCE = "evidence-voice"
_FAKE_CONSENT = "consent-1"


def build_plan(
    *,
    project_id: str,
    source_asset_id: str,
    candidate_id: str,
    script_text: str,
    language: str,
    enabled: bool,
    operator_reason: str,
    voice_id: str = "voice-1",
    provider: str = "fake",
    model_id: str = "fake-model",
    model_license: str = "allowed",
    consent_status: str = "recorded",
    target_duration_us: int = 1_000_000,
    engine_id: str | None = None,
    model_revision: str | None = None,
    provider_version: str | None = None,
    voice_type: str = "preset",
    commercial_use: str | None = None,
    output_use: str | None = None,
    license_evidence_id: str | None = None,
    consent_record_id: str | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
    timing_policy: str | None = None,
    duration_tolerance_us: int | None = None,
    conversion_recipe: str = "identity",
) -> NarrationPlan:
    require_language(language)
    decision = evaluate_mode("voice_narration_provider", operator_confirmed=enabled)
    if decision.decision == "needs_operator_confirmation" and enabled:
        enabled = False
    digest = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    if provider == "fake":
        resolved_engine = engine_id or _FAKE_ENGINE
        resolved_revision = model_revision or _FAKE_REVISION
        resolved_evidence = license_evidence_id or _FAKE_EVIDENCE
        resolved_consent = consent_record_id or _FAKE_CONSENT
        resolved_version = provider_version or "0"
        resolved_use = output_use or "internal"
        resolved_commercial = commercial_use or "allowed"
        resolved_rate = 16_000 if sample_rate is None else sample_rate
        resolved_channels = 1 if channels is None else channels
        resolved_policy = timing_policy or "preserve_duration"
        resolved_tolerance = 100_000 if duration_tolerance_us is None else duration_tolerance_us
    else:
        missing = [
            name
            for name, value in (
                ("engine_id", engine_id),
                ("model_revision", model_revision),
                ("provider_version", provider_version),
                ("license_evidence_id", license_evidence_id),
                ("consent_record_id", consent_record_id),
                ("sample_rate", sample_rate),
                ("channels", channels),
            )
            if value is None
        ]
        if missing:
            raise VoiceError("narration plan is missing " + ", ".join(missing))
        assert engine_id is not None
        assert model_revision is not None
        assert provider_version is not None
        assert license_evidence_id is not None
        assert consent_record_id is not None
        assert sample_rate is not None
        assert channels is not None
        placeholders = {
            _FAKE_ENGINE,
            _FAKE_REVISION,
            _FAKE_EVIDENCE,
            _FAKE_CONSENT,
            "fake-model",
            "voice-1",
        }
        supplied = {engine_id, model_revision, license_evidence_id, consent_record_id, model_id, voice_id}
        if supplied & placeholders:
            raise VoiceError("a live narration plan cannot use a fake placeholder")
        resolved_engine = engine_id
        resolved_revision = model_revision
        resolved_evidence = license_evidence_id
        resolved_consent = consent_record_id
        resolved_version = provider_version
        resolved_use = output_use or "commercial"
        resolved_commercial = commercial_use or model_license
        resolved_rate = sample_rate
        resolved_channels = channels
        resolved_policy = timing_policy or "reject_if_out_of_range"
        resolved_tolerance = 2_000_000 if duration_tolerance_us is None else duration_tolerance_us
        blocked = model_license != "allowed" or resolved_commercial != "allowed"
        if resolved_use == "commercial" and (blocked or model_id.lower().startswith("k2-fsa/")):
            raise VoiceError("narration model rights are not allowed")
    return NarrationPlan(
        plan_id=f"narration-{candidate_id}",
        project_id=project_id,
        source_asset_id=source_asset_id,
        candidate_id=candidate_id,
        enabled=enabled and decision.decision == "allowed",
        operator_reason=operator_reason,
        campaign_policy_decision=decision.decision,
        language=language,
        voice_id=voice_id,
        voice_type=voice_type,  # type: ignore[arg-type]
        provider=provider,
        provider_version=resolved_version,
        engine_id=resolved_engine,
        model_id=model_id,
        model_revision=resolved_revision,
        model_license=model_license,  # type: ignore[arg-type]
        commercial_use=resolved_commercial,  # type: ignore[arg-type]
        output_use=resolved_use,  # type: ignore[arg-type]
        license_evidence_id=resolved_evidence,
        consent_record_id=resolved_consent,
        conversion_recipe=conversion_recipe,
        consent_status=consent_status,  # type: ignore[arg-type]
        source_script_sha256=digest,
        target_duration_us=target_duration_us,
        sample_rate=resolved_rate,
        channels=resolved_channels,
        timing_policy=resolved_policy,  # type: ignore[arg-type]
        duration_tolerance_us=resolved_tolerance,
    )


def render_plan(
    database: object,
    work_root: Path,
    plan: NarrationPlan,
    provider: VoiceProvider,
    *,
    script_text: str,
    created_by: str = "voice",
) -> NarrationPlan:
    """Generate audio only when the plan is enabled. A disabled plan is success without audio."""
    digest = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
    if digest != plan.source_script_sha256:
        raise VoiceError("narration script changed")
    if not plan.enabled:
        return plan
    if plan.campaign_policy_decision != "allowed":
        raise VoiceError("narration is waiting for an operator decision")
    if plan.model_license in {"unknown", "prohibited", "cc_by_nc"}:
        raise VoiceError("narration model rights are not allowed")
    if plan.commercial_use in {"unknown", "prohibited", "cc_by_nc"}:
        raise VoiceError("narration model rights are not allowed")
    if plan.output_use == "commercial" and plan.model_id.lower().startswith("k2-fsa/"):
        raise VoiceError("narration model rights are not allowed")
    if plan.consent_status != "recorded":
        raise VoiceError("narration consent is missing")
    now = datetime.now(UTC)
    request = NarrationRequest(
        project_id=plan.project_id,
        source_asset_id=plan.source_asset_id,
        candidate_id=plan.candidate_id,
        script_text=script_text,
        script_sha256=digest,
        language=plan.language,
        provider_id=plan.provider,
        voice_profile_id=plan.voice_id,
        sample_rate=plan.sample_rate,
        channels=plan.channels,
        timing_policy=plan.timing_policy,
        target_duration_us=plan.target_duration_us,
        duration_tolerance_us=plan.duration_tolerance_us,
        output_use=plan.output_use,
        conversion_recipe=plan.conversion_recipe,
        created_by=created_by,
        profile=VoiceProviderProfile(
            provider_id=plan.provider,
            provider_version=plan.provider_version,
            engine_id=plan.engine_id,
            model_id=plan.model_id,
            model_revision=plan.model_revision,
            language=plan.language,
            voice_profile_id=plan.voice_id,
            voice_type=plan.voice_type,
            consent_record_id=plan.consent_record_id,
            commercial_use=plan.commercial_use,
            model_license=plan.model_license,
            license_evidence_id=plan.license_evidence_id,
            clone_permission=plan.voice_type == "cloned",
            provenance=ArtifactProvenance(
                created_at=now,
                created_by=created_by,
                tool="clipforge-voice",
                tool_version="0.1.0",
                source_asset_ids=[plan.source_asset_id],
            ),
        ),
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=created_by,
            tool="clipforge-voice",
            tool_version="0.1.0",
            source_asset_ids=[plan.source_asset_id],
        ),
    )
    artifact = generate_narration(database, work_root, request, provider)  # type: ignore[arg-type]
    payload = plan.model_dump(mode="json")
    payload["artifact_id"] = artifact.artifact_id
    payload["generated_audio_sha256"] = artifact.audio_sha256
    payload["actual_duration_us"] = artifact.duration_us
    return NarrationPlan.model_validate(payload)


def verify_plan(database: object, work_root: Path, plan: NarrationPlan) -> str:
    if not plan.enabled:
        return "PASS narration disabled"
    if plan.artifact_id is None or plan.generated_audio_sha256 is None:
        raise VoiceError("narration audio is missing")
    return verify_narration(database, work_root, plan.artifact_id)  # type: ignore[arg-type]


def write_plan(work_root: Path, plan: NarrationPlan) -> Path:
    path = work_root.resolve() / "voice" / plan.source_asset_id / f"{plan.candidate_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.model_dump_json() + "\n", encoding="utf-8")
    raw = path.read_text(encoding="utf-8").lower()
    if "bearer " in raw or "token=" in raw:
        path.unlink()
        raise VoiceError("narration plan contained a secret")
    return path


def load_plan(path: Path) -> NarrationPlan:
    return NarrationPlan.model_validate(json.loads(path.read_text(encoding="utf-8")))
