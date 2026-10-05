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
) -> NarrationPlan:
    require_language(language)
    decision = evaluate_mode("voice_narration_provider", operator_confirmed=enabled)
    if decision.decision == "needs_operator_confirmation" and enabled:
        enabled = False
    digest = hashlib.sha256(script_text.encode("utf-8")).hexdigest()
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
        provider=provider,
        provider_version="0",
        model_id=model_id,
        model_license=model_license,  # type: ignore[arg-type]
        consent_status=consent_status,  # type: ignore[arg-type]
        source_script_sha256=digest,
        target_duration_us=target_duration_us,
        sample_rate=16000,
        channels=1,
        timing_policy="preserve_duration",
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
        output_use="internal",
        created_by=created_by,
        profile=VoiceProviderProfile(
            provider_id=plan.provider,
            provider_version=plan.provider_version,
            engine_id="fake-engine" if plan.provider == "fake" else "omnivoice",
            model_id=plan.model_id,
            model_revision="rev-1",
            language=plan.language,
            voice_profile_id=plan.voice_id,
            voice_type="preset",
            consent_record_id="consent-1",
            commercial_use="allowed",
            model_license=plan.model_license,
            license_evidence_id="evidence-voice",
            clone_permission=False,
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
