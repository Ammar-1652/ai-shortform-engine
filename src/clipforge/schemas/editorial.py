"""Candidate clips and edit plans. Event times use the output clock only."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.schemas.common import ContractModel, EntityId, Microseconds, Versioned
from clipforge.schemas.governance import ComplianceResult, is_compliance_cleared
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimeMapDocument, digest_time_map


class EvidenceKind(StrEnum):
    TRANSCRIPT = "transcript"
    VISUAL = "visual"
    AUDIO = "audio"
    CAMPAIGN_FIT = "campaign_fit"
    HUMAN = "human"


class CandidateStatus(StrEnum):
    PROPOSED = "proposed"
    VISUAL_PENDING = "visual_pending"
    READY_FOR_REVIEW = "ready_for_review"
    REJECTED = "rejected"


class CandidateEvidence(Versioned):
    """One reason a candidate exists. The kind says whether it is spoken, visual, or other."""

    evidence_id: EntityId
    kind: EvidenceKind
    detail: str = Field(min_length=1)
    source_start_us: Microseconds | None = None
    source_end_us: Microseconds | None = None

    @model_validator(mode="after")
    def range_is_complete(self) -> Self:
        if (self.source_start_us is None) != (self.source_end_us is None):
            raise ValueError("source_start_us and source_end_us must be set together")
        if (
            self.source_start_us is not None
            and self.source_end_us is not None
            and self.source_end_us <= self.source_start_us
        ):
            raise ValueError("evidence source_end_us must be greater than source_start_us")
        return self


class CandidateClip(Versioned):
    """A possible short. ``creative_score`` does not clear compliance.

    ``ready_for_review`` requires transcript evidence, visual evidence, and a
    fully passed compliance gate. There is no path that adds the two together
    into one publish score.
    """

    candidate_id: EntityId
    project_id: EntityId
    source_asset_id: EntityId
    status: CandidateStatus
    time_map: TimeMapDocument
    evidence: list[CandidateEvidence] = Field(min_length=1)
    compliance: list[ComplianceResult] = Field(min_length=1)
    creative_score: float | None = Field(default=None, ge=0, le=1)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def ready_means_both_channels_and_a_clear_gate(self) -> Self:
        if self.time_map.to_time_map().total_output_duration() <= 0:
            raise ValueError(
                "a candidate clip must have a time map with total_output_duration > 0. "
                "An empty map is not a clip."
            )
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("candidate provenance.source_asset_ids must include source_asset_id")
        if self.status is CandidateStatus.READY_FOR_REVIEW:
            kinds = {item.kind for item in self.evidence}
            if EvidenceKind.TRANSCRIPT not in kinds or EvidenceKind.VISUAL not in kinds:
                raise ValueError(
                    "ready_for_review requires transcript evidence and visual evidence. "
                    "Transcript-only understanding cannot be marked ready."
                )
            if not is_compliance_cleared(self.compliance):
                raise ValueError(
                    "ready_for_review requires every compliance result to pass. Missing evidence is not a pass."
                )
        return self


class OutputInterval(ContractModel):
    """An interval on the output timeline produced by the candidate's time map."""

    output_start_us: Microseconds
    output_end_us: Microseconds
    clock: Literal["output"] = "output"

    @model_validator(mode="after")
    def end_after_start(self) -> Self:
        if self.output_end_us <= self.output_start_us:
            raise ValueError("output_end_us must be greater than output_start_us")
        return self


class CaptionCue(Versioned):
    cue_id: EntityId
    interval: OutputInterval
    text: str = Field(min_length=1)


class MotionPurpose(StrEnum):
    NUMBER = "number"
    COMPARISON = "comparison"
    PRODUCT_FEATURE = "product_feature"
    PROCESS_STEP = "process_step"
    CONCEPT = "concept"
    VISUAL_REVEAL = "visual_reveal"
    KEY_PHRASE = "key_phrase"
    DATA = "data"
    UI_INTERACTION = "ui_interaction"


class MotionEvent(Versioned):
    """A motion-graphics event. ``purpose`` is required so a transition cannot be purposeless."""

    event_id: EntityId
    interval: OutputInterval
    purpose: MotionPurpose
    component_id: str = Field(min_length=1, max_length=120)
    payload: dict[str, str] = Field(default_factory=dict)


class BrollEvent(Versioned):
    """B-roll on the output clock, with an in-point on the B-roll asset's own clock."""

    event_id: EntityId
    interval: OutputInterval
    asset_id: EntityId
    broll_source_in_us: Microseconds = Field(
        description="In-point on the B-roll asset clock. Not a program-timeline time."
    )
    # These fields are deliberately optional for old rough/hero documents. A
    # production Advanced Hero render must populate them from a reviewed
    # direction brief; an empty list identifies the old evenly-spaced fallback
    # and is rejected by the production renderer.
    source_evidence_ids: list[EntityId] = Field(default_factory=list)
    relevance_note: str = Field(default="", max_length=500)


class AudioEvent(Versioned):
    event_id: EntityId
    interval: OutputInterval
    asset_id: EntityId
    role: Literal["sfx", "music", "voice"]
    gain_db: float = Field(default=0, ge=-60, le=24)


class EditPlan(Versioned):
    """Creative decisions bound to one time map.

    ``time_map_sha256`` must match ``digest_time_map``. Changing the map without
    updating the digest, or attaching events past the map, fails validation.
    """

    edit_plan_id: EntityId
    project_id: EntityId
    candidate_id: EntityId
    stage: Literal["rough", "hero"]
    time_map: TimeMapDocument
    time_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captions: list[CaptionCue] = Field(default_factory=list)
    motion_events: list[MotionEvent] = Field(default_factory=list)
    broll_events: list[BrollEvent] = Field(default_factory=list)
    audio_events: list[AudioEvent] = Field(default_factory=list)
    provenance: ArtifactProvenance

    @model_validator(mode="after")
    def events_match_the_map(self) -> Self:
        digest = digest_time_map(self.time_map)
        if self.time_map_sha256 != digest:
            raise ValueError(
                "time_map_sha256 does not match the time map. Recompute the digest after any timing change."
            )
        if not self.provenance.source_asset_ids:
            raise ValueError("edit plan provenance must list at least one source_asset_id")
        duration = self.time_map.to_time_map().total_output_duration()
        if duration <= 0:
            raise ValueError(
                "an edit plan must have a time map with total_output_duration > 0. An empty map is not an edit."
            )
        for label, interval in self._intervals():
            if interval.output_end_us > duration:
                raise ValueError(
                    f"{label} ends at {interval.output_end_us} us, past the time map duration {duration} us"
                )
        return self

    def _intervals(self) -> list[tuple[str, OutputInterval]]:
        found: list[tuple[str, OutputInterval]] = []
        found.extend((f"caption {cue.cue_id}", cue.interval) for cue in self.captions)
        found.extend((f"motion {event.event_id}", event.interval) for event in self.motion_events)
        found.extend((f"broll {event.event_id}", event.interval) for event in self.broll_events)
        found.extend((f"audio {event.event_id}", event.interval) for event in self.audio_events)
        return found
