"""QA set binding. The aggregate status cannot hide a failed or incomplete check."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from clipforge.schemas.common import EntityId, Microseconds, Versioned
from clipforge.schemas.editorial import OutputInterval
from clipforge.schemas.jobs import QAKind, QAResult, QAStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.roles import WorkflowRolePolicy

_SHA = r"^[0-9a-f]{64}$"
_EVIDENCE_PATH = (
    r"^candidates/[A-Za-z0-9][A-Za-z0-9._:-]{0,127}/viewer-evidence/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}(?:/[A-Za-z0-9][A-Za-z0-9._-]{0,100})*$"
)


class ViewerEvidenceFile(Versioned):
    """One decoded image/contact sheet bound to the current encoded draft."""

    relative_path: str = Field(pattern=_EVIDENCE_PATH)
    sha256: str = Field(pattern=_SHA)
    kind: str = Field(min_length=1, max_length=60)
    frame_index: int | None = Field(default=None, ge=0)


class EditorialPilotReceipt(Versioned):
    """Hash-bound preflight receipt required before a clean Advanced render."""

    pilot_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    plan_sha256: str = Field(pattern=_SHA)
    direction_sha256: str = Field(pattern=_SHA)
    dependency_sha256: str = Field(pattern=_SHA)
    status: Literal["passed", "blocked"]
    checked_event_ids: list[EntityId] = Field(default_factory=list, max_length=64)
    inspected_intervals: list[OutputInterval] = Field(default_factory=list, max_length=64)
    findings: list[str] = Field(default_factory=list, max_length=32)
    created_at: AwareDatetime
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def is_bound(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("pilot provenance must include the source asset")
        if self.status == "passed" and self.findings:
            raise ValueError("a passed pilot cannot contain findings")
        return self


class HumanWatchRecord(Versioned):
    """A separate human playback observation; automation cannot create approval."""

    reviewer: str = Field(min_length=1, max_length=120)
    watched_with_audio: bool
    watched_muted: bool
    observations: list[str] = Field(min_length=1, max_length=40)
    decision: Literal["needs_changes", "reviewed_pending_final", "accepted_for_final_review"]
    reviewed_at: AwareDatetime
    player: str = Field(default="", max_length=200)


class HumanPlaybackTarget(Versioned):
    """Exact playback identity displayed before a human records a decision."""

    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    advanced_artifact_id: EntityId
    advanced_manifest_sha256: str = Field(pattern=_SHA)
    advanced_plan_sha256: str = Field(pattern=_SHA)
    source_sha256: str = Field(pattern=_SHA)
    video_sha256: str = Field(pattern=_SHA)


class HumanPlaybackReview(HumanPlaybackTarget):
    """Human observation stored with a final decision, never in immutable render bytes."""

    watch: HumanWatchRecord
    automated: Literal[False]
    reviewer_role: Literal["human_reviewer"] = "human_reviewer"

    @model_validator(mode="after")
    def complete_watch(self) -> Self:
        if not self.watch.watched_with_audio or not self.watch.watched_muted:
            raise ValueError("human watch must include audio and muted playback")
        if not self.watch.player.strip() or not self.watch.reviewer.strip():
            raise ValueError("human watch must name its player and reviewer")
        if any(not observation.strip() for observation in self.watch.observations):
            raise ValueError("human watch observations cannot be blank")
        return self


class ViewerEvidenceBundle(Versioned):
    """Decoded viewer-facing evidence for one exact Advanced Hero artifact."""

    evidence_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    candidate_id: EntityId
    artifact_id: EntityId
    manifest_sha256: str = Field(pattern=_SHA)
    encoded_media_sha256: str = Field(pattern=_SHA)
    render_input_sha256: str = Field(pattern=_SHA)
    pilot_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    treatment_fingerprint: str = Field(default="", pattern=r"^$|" + _SHA)
    treatment_audio_mix_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    treatment_audio_mix_status: Literal["", "planned", "measured"] = ""
    treatment_audio_integrated_lufs: float | None = None
    treatment_audio_true_peak_dbfs: float | None = None
    treatment_audio_rms_windows: list[float] = Field(default_factory=list, max_length=128)
    style_fingerprint: str = Field(pattern=_SHA)
    font_dependency_sha256: str = Field(pattern=_SHA)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    frame_rate: str = Field(pattern=r"^[0-9]+/[0-9]+$")
    duration_us: Microseconds
    integrated_lufs: float
    true_peak_dbfs: float
    decoded_frames: list[ViewerEvidenceFile] = Field(min_length=1)
    contact_sheets: list[ViewerEvidenceFile] = Field(min_length=1)
    platform_crop_previews: list[ViewerEvidenceFile] = Field(min_length=1)
    camera_motion_event_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    transition_event_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    human_watch: HumanWatchRecord | None = None
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def is_bound(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("viewer evidence provenance must include its source")
        if self.artifact_id not in self.provenance.parent_artifact_ids:
            raise ValueError("viewer evidence provenance must include its artifact")
        if self.width != 1080 or self.height != 1920 or self.frame_rate != "30/1":
            raise ValueError("viewer evidence must describe the portrait production output")
        if self.human_watch is not None and (
            not self.human_watch.watched_with_audio or not self.human_watch.watched_muted
        ):
            raise ValueError("human watch must include audio and muted playback")
        return self


class PolicyDigest(Versioned):
    """One resolved policy and its canonical hash. The path is not stored."""

    policy_id: EntityId
    sha256: str = Field(pattern=_SHA)


class QASetDocument(Versioned):
    """Technical and campaign QA bound to one current artifact."""

    qa_set_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    target_artifact_id: EntityId
    target_artifact_kind: str = Field(min_length=1, max_length=80)
    target_manifest_sha256: str = Field(pattern=_SHA)
    profile_id: EntityId
    profile_sha256: str = Field(pattern=_SHA)
    policies: list[PolicyDigest] = Field(min_length=1)
    technical: QAResult
    campaign: QAResult
    status: QAStatus
    treatment_fingerprint: str = Field(default="", pattern=r"^$|" + _SHA)
    treatment_summary_sha256: str = Field(default="", pattern=r"^$|" + _SHA)
    provenance: ArtifactProvenance
    workflow_roles: WorkflowRolePolicy | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def set_is_bound(self) -> Self:
        if self.technical.kind is not QAKind.TECHNICAL:
            raise ValueError("technical result must use kind technical")
        if self.campaign.kind is not QAKind.CAMPAIGN_COMPLIANCE:
            raise ValueError("campaign result must use kind campaign_compliance")
        for result in (self.technical, self.campaign):
            if result.artifact_id != self.target_artifact_id:
                raise ValueError("QA results must reference the target artifact")
            if result.project_id != self.project_id:
                raise ValueError("QA results must reference the project")
            if self.source_asset_id not in result.provenance.source_asset_ids:
                raise ValueError("QA result provenance must include the source asset")
            if not result.checks:
                raise ValueError("a QA result cannot pass with an empty check list")
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("QA provenance must include the source asset")
        if self.target_artifact_id not in self.provenance.parent_artifact_ids:
            raise ValueError("QA provenance must include the parent artifact")
        ids = [item.policy_id for item in self.policies]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise ValueError("policy digests must be unique and sorted by policy id")
        expected = aggregate_status(self.technical.status, self.campaign.status)
        if self.status is not expected:
            raise ValueError(
                f"QA aggregate status is {self.status.value} but the results aggregate to "
                f"{expected.value}. Do not upgrade a failed or incomplete QA set."
            )
        return self


class QACacheRecord(Versioned):
    """Sidecar for the current QA set. It stores hashes, not filesystem paths."""

    project_id: EntityId
    source_asset_id: EntityId
    qa_set_id: EntityId
    artifact_id: EntityId
    target_artifact_id: EntityId
    target_artifact_kind: str = Field(min_length=1, max_length=80)
    target_manifest_sha256: str = Field(pattern=_SHA)
    profile_id: EntityId
    profile_sha256: str = Field(pattern=_SHA)
    manifest_sha256: str = Field(pattern=_SHA)
    manifest_size_bytes: int = Field(ge=1)
    status: QAStatus
    created_at: AwareDatetime


def aggregate_status(*statuses: QAStatus) -> QAStatus:
    """Return the worst status. An empty list is not a pass."""
    if not statuses:
        return QAStatus.INSUFFICIENT_EVIDENCE
    if QAStatus.FAIL in statuses:
        return QAStatus.FAIL
    if QAStatus.INSUFFICIENT_EVIDENCE in statuses:
        return QAStatus.INSUFFICIENT_EVIDENCE
    return QAStatus.PASS
