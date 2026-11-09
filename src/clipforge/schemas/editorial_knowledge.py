"""Typed editorial knowledge records used by the direction layer.

Knowledge is advisory input to Codex and a provenance-bound input to a
direction plan. These records never constitute a review approval and never
contain executable renderer code.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from clipforge.schemas.common import EntityId, Versioned
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import SourceTimeRange

_SHA = r"^[0-9a-f]{64}$"

KnowledgeSourceKind = Literal[
    "repository",
    "web_page",
    "reference_video",
    "reference_audio",
    "campaign_document",
    "internal_policy",
]
PermissionStatus = Literal["analysis_allowed", "reuse_allowed", "blocked", "unknown"]
KnowledgeState = Literal[
    "captured",
    "analyzed",
    "proposed",
    "evaluated",
    "active",
    "superseded",
    "withdrawn",
]
EvidenceKind = Literal["observed", "heuristic", "technical", "viewer_review", "performance"]
KnowledgeAuthority = Literal[
    "system_invariant",
    "campaign_policy",
    "upstream_guidance",
    "operator_observation",
    "human_feedback",
    "analytics",
]
ImplementationAvailability = Literal[
    "guidance_only",
    "supported",
    "needs_component",
    "incompatible",
    "retired",
]


def _plain(value: str, *, label: str, max_length: int = 500) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} cannot be empty")
    if len(cleaned) > max_length:
        raise ValueError(f"{label} is too long")
    if any(ord(char) < 32 and char not in "\t" for char in cleaned):
        raise ValueError(f"{label} contains control characters")
    return cleaned


def _relative(value: str, *, label: str) -> str:
    cleaned = _plain(value, label=label, max_length=400)
    if (
        cleaned.startswith("/")
        or cleaned.startswith("\\")
        or "://" in cleaned
        or cleaned.startswith("file:")
        or "\\" in cleaned
        or any(part == ".." for part in cleaned.split("/"))
    ):
        raise ValueError(f"{label} must be a confined relative path")
    return cleaned


class KnowledgeScope(Versioned):
    """Scope limits keep a useful pattern from becoming a universal claim."""

    campaign_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    languages: list[str] = Field(default_factory=list, max_length=32)
    platforms: list[str] = Field(default_factory=list, max_length=16)
    genres: list[str] = Field(default_factory=list, max_length=32)
    profile_ids: list[EntityId] = Field(default_factory=list, max_length=32)

    @field_validator("languages", "platforms", "genres")
    @classmethod
    def scope_values_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(value, label="scope value", max_length=80) for value in values]


class KnowledgeSource(Versioned):
    """A pinned repository, page, policy, or authorized reference source."""

    source_id: EntityId
    kind: KnowledgeSourceKind
    title: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=500)
    repository_commit: str | None = Field(default=None, max_length=80)
    selected_paths: list[str] = Field(default_factory=list, max_length=64)
    license_id: str | None = Field(default=None, max_length=100)
    license_url: str | None = Field(default=None, max_length=500)
    attribution: str | None = Field(default=None, max_length=1000)
    permission: PermissionStatus
    allowed_uses: list[Literal["analysis", "guidance", "code", "asset_reuse"]] = Field(
        default_factory=list, max_length=4
    )
    content_sha256: str | None = Field(default=None, pattern=_SHA)
    captured_at: AwareDatetime
    source_version: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "title", "locator", "repository_commit", "license_id", "license_url", "attribution", "notes"
    )
    @classmethod
    def source_text_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _plain(value, label="knowledge source field", max_length=1000)

    @field_validator("selected_paths")
    @classmethod
    def selected_paths_are_relative(cls, values: list[str]) -> list[str]:
        return [_relative(value, label="selected path") for value in values]

    @model_validator(mode="after")
    def permission_has_a_usable_record(self) -> Self:
        if self.permission in {"reuse_allowed", "analysis_allowed"} and not self.content_sha256:
            raise ValueError("an admitted source needs a captured content hash")
        if (
            self.permission == "reuse_allowed"
            and not ({"asset_reuse", "code"} & set(self.allowed_uses))
            and self.kind != "repository"
        ):
            raise ValueError("reuse_allowed source must declare asset_reuse or code")
        if self.kind == "repository" and not self.repository_commit:
            raise ValueError("repository source requires an exact commit")
        return self


class ReferenceObservation(Versioned):
    """One observed fact from an authorized reference or local artifact."""

    observation_id: EntityId
    source_id: EntityId
    kind: Literal["visual", "audio", "speech", "caption", "narrative", "pacing", "identity", "rights"]
    interval: SourceTimeRange | None = None
    observation: str = Field(min_length=1, max_length=1000)
    method: Literal["frame_probe", "contact_sheet", "audio_probe", "transcript", "human_watch", "metadata"]
    confidence: Literal["low", "medium", "high"]
    evidence_paths: list[str] = Field(default_factory=list, max_length=16)
    limitations: list[str] = Field(default_factory=list, max_length=12)
    evidence_kind: EvidenceKind
    content_sha256: str = Field(pattern=_SHA)

    @field_validator("observation")
    @classmethod
    def observation_is_plain(cls, value: str) -> str:
        return _plain(value, label="observation", max_length=1000)

    @field_validator("evidence_paths")
    @classmethod
    def evidence_paths_are_relative(cls, values: list[str]) -> list[str]:
        return [_relative(value, label="evidence path") for value in values]

    @field_validator("limitations")
    @classmethod
    def limitations_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(value, label="observation limitation", max_length=300) for value in values]


class ReferenceMetric(Versioned):
    """One measured or explicitly unavailable reference-video metric."""

    name: Literal[
        "duration",
        "audio_duration",
        "integrated_loudness",
        "true_peak",
        "hook_duration",
        "first_visual_change",
        "shot_count",
        "median_shot_duration",
        "cut_density",
        "words_per_second",
        "caption_line_count",
        "caption_position",
        "transition_class",
        "sfx_timing",
        "silence_windows",
        "motion_intensity",
        "payoff_position",
        "cta_hold",
    ]
    value: float | None = Field(default=None)
    unit: (
        Literal[
            "microseconds",
            "cuts_per_minute",
            "words_per_second",
            "lines",
            "ratio",
            "LUFS",
            "dBFS",
            "count",
        ]
        | None
    ) = None
    evidence_kind: EvidenceKind
    method: Literal["ffprobe", "frame_probe", "audio_probe", "transcript", "human_watch", "unavailable"]
    limitation: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def value_and_unit_match(self) -> Self:
        if self.value is not None and self.name not in {"integrated_loudness", "true_peak"} and self.value < 0:
            raise ValueError("reference metric value must be non-negative for this metric")
        if self.value is None:
            if self.method != "unavailable" or not self.limitation:
                raise ValueError("an unavailable metric requires method=unavailable and a limitation")
        elif self.unit is None:
            raise ValueError("a measured metric requires a unit")
        return self


class ReferenceAnalysis(Versioned):
    """Bounded analysis record for an authorized reference video or audio file."""

    analysis_id: EntityId
    source_id: EntityId
    source_locator: str = Field(min_length=1, max_length=400)
    permission: Literal["analysis_allowed", "reuse_allowed", "blocked", "unknown"]
    permission_evidence: str = Field(min_length=1, max_length=500)
    media_sha256: str = Field(pattern=_SHA)
    analyzer_version: str = Field(min_length=1, max_length=80)
    metrics: list[ReferenceMetric] = Field(min_length=1, max_length=32)
    observation_ids: list[EntityId] = Field(default_factory=list, max_length=128)
    evidence_paths: list[str] = Field(default_factory=list, max_length=32)
    unknowns: list[str] = Field(default_factory=list, max_length=32)
    analysis_sha256: str = Field(pattern=_SHA)
    provenance: ArtifactProvenance
    created_at: AwareDatetime

    @field_validator("source_locator", "permission_evidence")
    @classmethod
    def reference_text_is_plain(cls, value: str) -> str:
        return _plain(value, label="reference analysis field", max_length=500)

    @field_validator("evidence_paths")
    @classmethod
    def reference_paths_are_relative(cls, values: list[str]) -> list[str]:
        return [_relative(value, label="reference evidence path") for value in values]

    @field_validator("unknowns")
    @classmethod
    def reference_unknowns_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(value, label="reference unknown", max_length=500) for value in values]

    @model_validator(mode="after")
    def permission_is_explicit(self) -> Self:
        if self.permission not in {"analysis_allowed", "reuse_allowed"}:
            raise ValueError("production reference analysis requires explicit analysis permission")
        if self.source_id not in self.provenance.source_asset_ids:
            raise ValueError("reference analysis provenance must include source_id")
        return self


class KnowledgeEvaluationCase(Versioned):
    """A scenario that proves a guidance card selects or rejects correctly."""

    evaluation_id: EntityId
    title: str = Field(min_length=1, max_length=180)
    scenario: str = Field(min_length=1, max_length=1000)
    input_tags: list[str] = Field(default_factory=list, max_length=24)
    expected_outcome: Literal["select", "reject", "warn", "needs_review"]
    expected_reason: str = Field(min_length=1, max_length=500)
    fixture_path: str | None = None
    source_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    content_sha256: str = Field(pattern=_SHA)

    @field_validator("title", "scenario", "expected_reason")
    @classmethod
    def evaluation_text_is_plain(cls, value: str) -> str:
        return _plain(value, label="evaluation field", max_length=1000)

    @field_validator("input_tags")
    @classmethod
    def tags_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(value, label="evaluation tag", max_length=80) for value in values]

    @field_validator("fixture_path")
    @classmethod
    def fixture_path_is_confined(cls, value: str | None) -> str | None:
        return None if value is None else _relative(value, label="fixture path")


class EditorialGuidanceCard(Versioned):
    """An actionable, bounded editorial instruction for Codex."""

    card_id: EntityId
    title: str = Field(min_length=1, max_length=160)
    authority: KnowledgeAuthority
    state: KnowledgeState
    implementation: ImplementationAvailability
    scope: KnowledgeScope = Field(default_factory=KnowledgeScope)
    source_ids: list[EntityId] = Field(min_length=1, max_length=16)
    evidence_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    evaluation_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    intent: str = Field(min_length=1, max_length=500)
    triggers: list[str] = Field(min_length=1, max_length=12)
    prerequisites: list[str] = Field(default_factory=list, max_length=12)
    steps: list[str] = Field(min_length=1, max_length=16)
    parameters: dict[str, str] = Field(default_factory=dict, max_length=32)
    coordination: list[str] = Field(default_factory=list, max_length=16)
    avoid_when: list[str] = Field(min_length=1, max_length=16)
    limitations: list[str] = Field(min_length=1, max_length=16)
    capability_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    supersedes_card_id: EntityId | None = None
    revision: int = Field(default=1, ge=1, le=10_000)
    content_sha256: str = Field(pattern=_SHA)
    updated_at: AwareDatetime

    @field_validator(
        "title",
        "intent",
        "triggers",
        "prerequisites",
        "steps",
        "coordination",
        "avoid_when",
        "limitations",
    )
    @classmethod
    def guidance_text_is_plain(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            return _plain(value, label="guidance text", max_length=700)
        return [_plain(item, label="guidance text", max_length=700) for item in value]

    @field_validator("parameters")
    @classmethod
    def parameters_are_plain(cls, values: dict[str, str]) -> dict[str, str]:
        return {
            _plain(key, label="guidance parameter key", max_length=80): _plain(
                value, label="guidance parameter", max_length=300
            )
            for key, value in values.items()
        }

    @model_validator(mode="after")
    def active_guidance_is_evaluable(self) -> Self:
        if self.state in {"evaluated", "active"} and not self.evaluation_ids:
            raise ValueError("evaluated or active guidance requires evaluation cases")
        if self.implementation == "supported" and not self.capability_ids:
            raise ValueError("supported guidance requires capability ids")
        return self


class NarrativePattern(Versioned):
    """A source-grounded hook/body/payoff structure."""

    pattern_id: EntityId
    name: str = Field(min_length=1, max_length=160)
    state: KnowledgeState
    scope: KnowledgeScope = Field(default_factory=KnowledgeScope)
    source_ids: list[EntityId] = Field(min_length=1, max_length=16)
    guidance_card_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    evidence_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    hook_shape: str = Field(min_length=1, max_length=500)
    body_shape: str = Field(min_length=1, max_length=500)
    payoff_shape: str = Field(min_length=1, max_length=500)
    required_source_facts: list[str] = Field(min_length=1, max_length=16)
    continuity_rules: list[str] = Field(min_length=1, max_length=16)
    repetition_rules: list[str] = Field(default_factory=list, max_length=8)
    reject_when: list[str] = Field(min_length=1, max_length=16)
    content_sha256: str = Field(pattern=_SHA)

    @field_validator(
        "name",
        "hook_shape",
        "body_shape",
        "payoff_shape",
        "required_source_facts",
        "continuity_rules",
        "repetition_rules",
        "reject_when",
    )
    @classmethod
    def pattern_text_is_plain(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            return _plain(value, label="narrative pattern field", max_length=700)
        return [_plain(item, label="narrative pattern field", max_length=700) for item in value]


class EditorialStyleCard(Versioned):
    """A coordinated story, visual, motion, caption, and audio direction."""

    style_card_id: EntityId
    name: str = Field(min_length=1, max_length=160)
    state: KnowledgeState
    scope: KnowledgeScope = Field(default_factory=KnowledgeScope)
    source_ids: list[EntityId] = Field(min_length=1, max_length=32)
    observation_ids: list[EntityId] = Field(default_factory=list, max_length=64)
    reference_analysis_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    reference_analysis_sha256: list[str] = Field(default_factory=list, max_length=32)
    guidance_card_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    narrative_pattern_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    evaluation_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    caption_style_id: str | None = Field(default=None, max_length=100)
    visual_identity: list[str] = Field(default_factory=list, max_length=16)
    pacing_rules: list[str] = Field(min_length=1, max_length=16)
    audio_rules: list[str] = Field(min_length=1, max_length=16)
    ending_rules: list[str] = Field(min_length=1, max_length=16)
    limitations: list[str] = Field(min_length=1, max_length=16)
    confidence: Literal["low", "medium", "high"]
    content_sha256: str = Field(pattern=_SHA)
    updated_at: AwareDatetime

    @field_validator("reference_analysis_sha256")
    @classmethod
    def analysis_hashes_are_sha256(cls, values: list[str]) -> list[str]:
        if any(__import__("re").fullmatch(_SHA, value) is None for value in values):
            raise ValueError("reference analysis bindings must be sha256 hex digests")
        return values

    @model_validator(mode="after")
    def analysis_bindings_match(self) -> Self:
        if self.reference_analysis_ids and len(self.reference_analysis_ids) != len(
            self.reference_analysis_sha256
        ):
            raise ValueError("reference analysis ids and hashes must be paired")
        return self

    @field_validator(
        "name",
        "visual_identity",
        "pacing_rules",
        "audio_rules",
        "ending_rules",
        "limitations",
    )
    @classmethod
    def style_text_is_plain(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            return _plain(value, label="style card field", max_length=700)
        return [_plain(item, label="style card field", max_length=700) for item in value]


class KnowledgeConflict(Versioned):
    """A conflict that must be resolved before guidance enters a context."""

    conflict_id: EntityId
    record_ids: list[EntityId] = Field(min_length=2, max_length=16)
    kind: Literal["scope", "policy", "timing", "license", "implementation", "evidence", "copy"]
    description: str = Field(min_length=1, max_length=1000)
    status: Literal["unresolved", "resolved", "rejected"]
    winning_record_id: EntityId | None = None
    resolution_note: str | None = Field(default=None, max_length=700)
    resolved_by: Literal["system_enforcer", "codex_operator", "human_reviewer"] | None = None
    updated_at: AwareDatetime

    @field_validator("description", "resolution_note")
    @classmethod
    def conflict_text_is_plain(cls, value: str | None) -> str | None:
        return None if value is None else _plain(value, label="conflict text", max_length=1000)

    @model_validator(mode="after")
    def resolution_is_complete(self) -> Self:
        resolved = (self.winning_record_id, self.resolution_note, self.resolved_by)
        if self.status == "resolved" and not all(resolved):
            raise ValueError("resolved conflict requires winner, note, and resolver")
        if self.status != "resolved" and any(resolved):
            raise ValueError("unresolved or rejected conflict cannot carry a resolution")
        return self


class KnowledgeRelease(Versioned):
    """An immutable set of admitted cards used to build direction context."""

    release_id: EntityId
    name: str = Field(min_length=1, max_length=160)
    state: Literal["draft", "active", "retired"]
    source_ids: list[EntityId] = Field(min_length=1, max_length=64)
    observation_ids: list[EntityId] = Field(default_factory=list, max_length=128)
    guidance_card_ids: list[EntityId] = Field(default_factory=list, max_length=128)
    narrative_pattern_ids: list[EntityId] = Field(default_factory=list, max_length=64)
    style_card_ids: list[EntityId] = Field(default_factory=list, max_length=64)
    motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=128)
    conflict_ids: list[EntityId] = Field(default_factory=list, max_length=64)
    evaluation_ids: list[EntityId] = Field(default_factory=list, max_length=128)
    manifest_sha256: str = Field(pattern=_SHA)
    created_at: AwareDatetime
    created_by: Literal["codex_operator", "system_enforcer", "human_reviewer"]

    @model_validator(mode="after")
    def active_release_has_no_unresolved_conflict(self) -> Self:
        if self.state == "active" and self.conflict_ids:
            raise ValueError("active knowledge release cannot include unresolved conflicts")
        return self


class KnowledgeLibraryDocument(Versioned):
    """Strict on-disk bundle for one knowledge-library release."""

    sources: list[KnowledgeSource] = Field(default_factory=list, max_length=128)
    observations: list[ReferenceObservation] = Field(default_factory=list, max_length=256)
    evaluations: list[KnowledgeEvaluationCase] = Field(default_factory=list, max_length=256)
    guidance_cards: list[EditorialGuidanceCard] = Field(default_factory=list, max_length=256)
    narrative_patterns: list[NarrativePattern] = Field(default_factory=list, max_length=128)
    style_cards: list[EditorialStyleCard] = Field(default_factory=list, max_length=128)
    conflicts: list[KnowledgeConflict] = Field(default_factory=list, max_length=128)
    releases: list[KnowledgeRelease] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def ids_are_unique(self) -> Self:
        groups = {
            "sources": [item.source_id for item in self.sources],
            "observations": [item.observation_id for item in self.observations],
            "evaluations": [item.evaluation_id for item in self.evaluations],
            "guidance cards": [item.card_id for item in self.guidance_cards],
            "narrative patterns": [item.pattern_id for item in self.narrative_patterns],
            "style cards": [item.style_card_id for item in self.style_cards],
            "conflicts": [item.conflict_id for item in self.conflicts],
            "releases": [item.release_id for item in self.releases],
        }
        for label, ids in groups.items():
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} ids must be unique")
        return self


class ContextFact(Versioned):
    """A source or campaign fact made available in a direction context."""

    fact_id: EntityId
    kind: Literal["source", "campaign", "transcript", "visual", "alignment", "rights", "capability"]
    text: str = Field(min_length=1, max_length=700)
    evidence_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    verified: bool = False

    @field_validator("text")
    @classmethod
    def fact_text_is_plain(cls, value: str) -> str:
        return _plain(value, label="context fact", max_length=700)


class DirectionContextBundle(Versioned):
    """Relevant knowledge and source facts supplied to one editorial decision."""

    context_id: EntityId
    project_id: EntityId
    campaign_id: EntityId | None = None
    source_asset_id: EntityId
    candidate_id: EntityId
    language: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
    platform: str = Field(min_length=1, max_length=40)
    profile_id: EntityId | None = None
    knowledge_release_id: EntityId
    source_sha256: str = Field(pattern=_SHA)
    transcript_sha256: str | None = Field(default=None, pattern=_SHA)
    alignment_sha256: str | None = Field(default=None, pattern=_SHA)
    visual_analysis_sha256: str | None = Field(default=None, pattern=_SHA)
    facts: list[ContextFact] = Field(min_length=1, max_length=64)
    guidance_card_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    narrative_pattern_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    style_card_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    motion_catalog_sha256: str | None = Field(default=None, pattern=_SHA)
    excluded_record_ids: list[EntityId] = Field(default_factory=list, max_length=64)
    unknowns: list[str] = Field(default_factory=list, max_length=32)
    capability_ids: list[EntityId] = Field(default_factory=list, max_length=64)
    context_sha256: str = Field(pattern=_SHA)
    provenance: ArtifactProvenance
    created_at: AwareDatetime

    @field_validator("unknowns")
    @classmethod
    def unknowns_are_plain(cls, values: list[str]) -> list[str]:
        return [_plain(value, label="context unknown", max_length=500) for value in values]

    @model_validator(mode="after")
    def context_is_bound(self) -> Self:
        if self.source_asset_id not in self.provenance.source_asset_ids:
            raise ValueError("context provenance must include source_asset_id")
        return self


class DecisionAlternative(Versioned):
    """A guidance, style, or recipe candidate that was rejected."""

    record_id: EntityId
    kind: Literal["guidance", "pattern", "style", "motion", "asset", "audio"]
    reason: str = Field(min_length=1, max_length=700)
    priority_rule: str = Field(min_length=1, max_length=120)

    @field_validator("reason", "priority_rule")
    @classmethod
    def decision_text_is_plain(cls, value: str) -> str:
        return _plain(value, label="decision alternative", max_length=700)


class EditorialDecisionTrace(Versioned):
    """Reviewable explanation of the guidance used by a direction plan."""

    trace_id: EntityId
    context_id: EntityId
    direction_id: EntityId | None = None
    selected_guidance_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    selected_pattern_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    selected_style_card_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    selected_motion_recipe_ids: list[EntityId] = Field(default_factory=list, max_length=32)
    rejected: list[DecisionAlternative] = Field(default_factory=list, max_length=64)
    source_evidence_ids: list[EntityId] = Field(default_factory=list, max_length=64)
    reasons: list[str] = Field(min_length=1, max_length=16)
    deviations: list[str] = Field(default_factory=list, max_length=16)
    context_sha256: str = Field(pattern=_SHA)
    operator_role: Literal["codex_operator", "human_reviewer"]
    created_at: AwareDatetime

    @field_validator("reasons", "deviations")
    @classmethod
    def trace_text_is_plain(cls, value: list[str]) -> list[str]:
        return [_plain(item, label="decision trace text", max_length=700) for item in value]


class EditorialFeedback(Versioned):
    """Append-only feedback tied to an exact plan/render/scene."""

    feedback_id: EntityId
    plan_id: EntityId
    artifact_id: EntityId | None = None
    scene_id: EntityId | None = None
    reviewer_role: Literal["codex_operator", "human_reviewer"]
    kind: Literal["defect", "preference", "acceptance", "rejection", "performance"]
    severity: Literal["error", "warning", "info"]
    observation: str = Field(min_length=1, max_length=1000)
    evidence_paths: list[str] = Field(default_factory=list, max_length=16)
    proposed_card_ids: list[EntityId] = Field(default_factory=list, max_length=16)
    created_at: AwareDatetime

    @field_validator("observation")
    @classmethod
    def feedback_observation_is_plain(cls, value: str) -> str:
        return _plain(value, label="feedback observation", max_length=1000)

    @field_validator("evidence_paths")
    @classmethod
    def feedback_paths_are_relative(cls, values: list[str]) -> list[str]:
        return [_relative(value, label="feedback evidence path") for value in values]
