"""Installed capabilities of the existing production core, with no dispatch engine."""

# The catalogue is operator-facing prose. Keep records readable in source;
# the typed models and CLI verification remain the correctness checks.

from __future__ import annotations

from clipforge.errors import ClipforgeError
from clipforge.schemas.operator import ExtensionBoundary, OperatorCapability
from clipforge.schemas.roles import WorkflowRolePolicy


def _tool(
    name: str,
    purpose: str,
    plane: str,
    command: str,
    requires: list[str],
    produces: list[str],
    limitation: str,
    *,
    execution: str = "write",
    owner: str = "codex_operator",
) -> OperatorCapability:
    return OperatorCapability.model_validate(
        dict(
            capability_id=name,
            purpose=purpose,
            plane=plane,
            command=command.split(),
            requires=requires,
            produces=produces,
            limitation=limitation,
            execution=execution,
            owner=owner,
        )
    )


CAPABILITIES = (
    _tool(
        "release-capture",
        "Capture the current executable code and dependency release identity",
        "control",
        "operator release capture",
        ["current checkout"],
        ["ProductionRelease"],
        "Captures identity only; it does not fetch, activate, or publish code.",
    ),
    _tool(
        "release-verify",
        "Verify a release snapshot against the current checkout",
        "control",
        "operator release verify",
        ["release id"],
        ["verified release"],
        "Read-only; a stale release blocks reuse and needs a new capture.",
        execution="read",
    ),
    _tool(
        "source-inspect",
        "Inspect local source streams, duration and eligibility",
        "media",
        "source inspect",
        ["authorized local path"],
        ["probe facts"],
        "Does not infer the story from transcript text.",
        execution="read",
    ),
    _tool(
        "prepare",
        "Prepare picture and speech on the same source clock",
        "media",
        "media prepare",
        ["ingested source", "cleared rights"],
        ["analysis proxy", "ASR FLAC"],
        "Does not select editorial cuts.",
    ),
    _tool(
        "transcribe",
        "Extract approximate full-source speech",
        "media",
        "transcript run",
        ["prepared ASR audio", "installed ASR model"],
        ["raw transcript"],
        "Approximate timing cannot authorize final captions.",
    ),
    _tool(
        "visual-analysis",
        "Extract scene, frame and face evidence",
        "media",
        "vision analyze",
        ["prepared picture", "installed detector"],
        ["visual analysis", "frame evidence"],
        "A face is not an active speaker.",
    ),
    _tool(
        "candidate-mine",
        "Propose candidate spans for Codex inspection",
        "decision",
        "candidate mine",
        ["transcript", "visual analysis", "campaign policy"],
        ["candidate set"],
        "Scores are heuristics; Codex chooses the story.",
    ),
    _tool(
        "preview",
        "Render inexpensive review previews",
        "media",
        "preview render",
        ["current candidate set"],
        ["rough preview set"],
        "Captions remain provisional.",
    ),
    _tool(
        "candidate-select",
        "Record Codex's candidate promotion",
        "review",
        "review decide",
        ["inspected current preview", "exact preview identifiers", "reviewer-role codex_operator"],
        ["append-only candidate decision"],
        "Does not approve final playback or publication.",
    ),
    _tool(
        "align",
        "Force-align selected speech to source words",
        "media",
        "hero align",
        ["promoted candidate", "installed aligner"],
        ["forced alignment"],
        "Model/live evidence checks remain mandatory.",
    ),
    _tool(
        "hero-plan",
        "Build typed captions and motion for the selected candidate",
        "decision",
        "hero plan",
        ["forced alignment", "current candidate decision"],
        ["Hero plan"],
        "Does not change source meaning or certify pronunciation.",
    ),
    _tool(
        "hero-render",
        "Render the Hero plan",
        "media",
        "hero render",
        ["current Hero plan"],
        ["Hero MP4", "Hero manifest"],
        "An encoded draft is not human acceptance.",
    ),
    _tool(
        "hero-select",
        "Record Codex's technical and editorial Hero decision",
        "review",
        "hero review decide",
        ["inspected Hero", "exact artifact, plan and alignment identifiers", "reviewer-role codex_operator"],
        ["append-only Hero decision"],
        "Cannot authorize delivery.",
    ),
    _tool(
        "direction",
        "Validate Codex's source-grounded creative brief",
        "decision",
        "hero advanced direction plan",
        ["direction skill", "three evidence-backed alternatives", "selected Hero"],
        ["DirectionDocument"],
        "The tool validates and binds; Codex chooses and scores the alternatives.",
    ),
    _tool(
        "direction-lint",
        "Check source continuity, layer density, and semantic direction gates",
        "decision",
        "hero advanced direction lint",
        ["persisted DirectionDocument", "current alignment and visual evidence"],
        ["DirectionLintReport"],
        "Read-only; a passing lint report is not human final approval.",
        execution="read",
    ),
    _tool(
        "treatment-doctor",
        "Verify typed per-beat treatment policies and the graphics production flag",
        "decision",
        "editorial treatment doctor",
        ["preset catalog", "motion policy"],
        ["treatment policy status"],
        "Read-only; it does not select assets or render a clip.",
        execution="read",
    ),
    _tool(
        "treatment-plan",
        "Inspect per-beat B-roll, SFX, camera, transition, and omission decisions",
        "decision",
        "editorial treatment plan",
        ["treatment-aware DirectionDocument"],
        ["TreatmentPlanSummary", "bounded asset requests"],
        "Read-only; provider requests still require Codex relevance selection and rights clearance.",
        execution="read",
    ),
    _tool(
        "treatment-show",
        "Show every selected beat treatment decision and its evidence bindings",
        "decision",
        "editorial treatment show",
        ["treatment-aware DirectionDocument"],
        ["per-beat treatment decisions"],
        "Read-only; it does not change a direction or approval.",
        execution="read",
    ),
    _tool(
        "treatment-lint",
        "Reject missing, stale, or unresolved treatment decisions before rendering",
        "decision",
        "editorial treatment lint",
        ["treatment-aware DirectionDocument"],
        ["treatment lint report"],
        "A passing report proves contract integrity, not human viewer acceptance.",
        execution="read",
    ),
    _tool(
        "treatment-bind-asset",
        "Bind verified provider and license evidence to a treatment placement",
        "asset",
        "editorial treatment bind-asset",
        ["acquired treatment request", "registered local asset", "license evidence"],
        ["request-bound DirectionAssetPlacement"],
        "Does not download media; provider acquisition and rights checks remain separate typed tools.",
        execution="read",
    ),
    _tool(
        "editorial-knowledge-doctor",
        "Validate the admitted editorial knowledge release",
        "decision",
        "editorial doctor",
        ["local knowledge library"],
        ["knowledge release status"],
        "Does not call a network provider or approve a render.",
        execution="read",
    ),
    _tool(
        "editorial-knowledge-list",
        "List guidance, narrative patterns, styles, sources, and evaluations",
        "decision",
        "editorial knowledge list",
        ["validated knowledge library"],
        ["knowledge record index"],
        "Read-only metadata; it does not select a render by itself.",
        execution="read",
    ),
    _tool(
        "editorial-knowledge-context",
        "Build a hash-bound direction context for Codex",
        "decision",
        "editorial knowledge context",
        ["source hash", "candidate facts", "campaign policy", "available capabilities"],
        ["DirectionContextBundle"],
        "The context informs Codex; it is not an approval and cannot contain executable code.",
    ),
    _tool(
        "editorial-feedback",
        "Append feedback tied to an exact plan, render, or scene",
        "review",
        "editorial knowledge feedback",
        ["exact plan or artifact", "evidence path"],
        ["append-only EditorialFeedback"],
        "Feedback proposes knowledge changes; it does not rewrite active guidance automatically.",
    ),
    _tool(
        "editorial-motion-doctor",
        "Validate approved local Remotion motion recipes and component routes",
        "decision",
        "editorial motion doctor",
        ["motion recipe catalog", "renderer component registry"],
        ["motion catalog status"],
        "Does not fetch upstream instructions or render media.",
        execution="read",
    ),
    _tool(
        "editorial-motion-list",
        "List approved and reference-only motion recipes",
        "decision",
        "editorial motion list",
        ["validated motion catalog"],
        ["motion recipe index"],
        "Listing a recipe does not authorize its use without a direction purpose.",
        execution="read",
    ),
    _tool(
        "editorial-analyze-reference",
        "Probe an authorized local reference and record measurements and unknowns",
        "decision",
        "editorial analyze-reference",
        ["authorized local reference under work root", "permission evidence"],
        ["ReferenceAnalysis"],
        "A media probe does not prove hook, caption, or performance quality; those need further evidence.",
    ),
    _tool(
        "editorial-style-proposal",
        "Turn measured reference evidence into a reviewable proposed style card",
        "decision",
        "editorial reference propose-style-card",
        ["verified ReferenceAnalysis", "style id and name"],
        ["proposed EditorialStyleCard"],
        "Proposals remain inactive until evaluation and a new knowledge release admit them.",
    ),
    _tool(
        "openverse-doctor",
        "Inspect optional Openverse configuration without network access",
        "asset",
        "assets openverse doctor",
        ["local configuration"],
        ["provider status"],
        "Does not contact Openverse or clear an asset.",
        execution="read",
    ),
    _tool(
        "openverse-search",
        "Search bounded Openverse image or audio metadata",
        "asset",
        "assets openverse search",
        ["explicit live flag", "bounded query"],
        ["normalized discovery metadata"],
        "Search is not a download or license clearance; live mode is disabled by default.",
    ),
    _tool(
        "openverse-select",
        "Select one Openverse result after metadata and rights review",
        "asset",
        "assets openverse select",
        ["normalized response", "policy fingerprint", "independent license evidence for clearance"],
        ["append-only OpenverseSelection"],
        "Selection never downloads bytes; blocked or pending rights cannot enter a render.",
    ),
    _tool(
        "openverse-acquire",
        "Acquire bytes for an independently rights-verified Openverse selection",
        "asset",
        "assets openverse acquire",
        ["allowed OpenverseSelection", "bounded direct URL", "independent license evidence"],
        ["hash-bound acquisition manifest"],
        "Acquisition remains separate from selection and still requires local asset "
        "registration before editing.",
    ),
    _tool(
        "openverse-verify",
        "Verify acquired Openverse bytes and manifest",
        "asset",
        "assets openverse verify",
        ["acquisition manifest"],
        ["verified bytes"],
        "Read-only; it does not grant a license or register an editorial asset.",
        execution="read",
    ),
    _tool(
        "asset-register",
        "Register a local B-roll, image, graphic, font or SFX asset",
        "asset",
        "assets register-local",
        ["local file", "rights evidence", "relevant content tags"],
        ["asset binding", "license record"],
        "Check --help for supported kinds; raw downloaded files are not editorial clearance.",
    ),
    _tool(
        "envato-search",
        "Search Envato through the approved adapter",
        "asset",
        "assets envato search",
        ["configured Envato MCP", "campaign permission"],
        ["search hits", "download request"],
        "Provider availability and campaign outside-media restrictions still apply.",
    ),
    _tool(
        "envato-fetch",
        "Fetch an explicitly selected asset and certificate",
        "asset",
        "assets envato fetch",
        ["download request", "authenticated approved bridge", "campaign permission"],
        ["registered asset", "license evidence"],
        "No subscription or unlicensed download is implied by discovery.",
    ),
    _tool(
        "advanced-plan",
        "Validate cuts, crop, captions, assets and Remotion graphic choices",
        "decision",
        "hero advanced plan",
        ["Codex direction", "ordered editorial arc", "speech/overlay evidence required by campaign"],
        ["Advanced Hero plan"],
        "Only supported typed components and placements can render.",
    ),
    _tool(
        "advanced-render",
        "Execute the typed plan with verified resumable units",
        "media",
        "hero advanced render",
        ["current validated plan", "rights", "service authorization"],
        ["Advanced MP4", "checkpoints", "caption and viewer evidence"],
        "Resume only matching receipts; no manual batch bypass.",
    ),
    _tool(
        "execution-checkpoint",
        "Inspect hash-bound campaign progress and recovery state",
        "control",
        "campaign checkpoint verify",
        ["execution checkpoint id"],
        ["verified checkpoint status"],
        "Read-only; it does not mark a stage complete or repair a failed run.",
        execution="read",
    ),
    _tool(
        "qa",
        "Measure and validate current technical and campaign evidence",
        "control",
        "qa run",
        ["current Advanced artifact"],
        ["QA set"],
        "QA cannot record human creative acceptance.",
    ),
    _tool(
        "final-target",
        "Prepare exact playback identity for the human",
        "review",
        "final review watch-target",
        ["current QA-eligible Advanced artifact"],
        ["HumanPlaybackTarget"],
        "Does not claim that anyone watched.",
        execution="read",
    ),
    _tool(
        "final-accept",
        "Record the human's playback and creative decision",
        "review",
        "final review decide",
        ["human audio and muted playback", "human decision", "exact artifact target"],
        ["HumanPlaybackReview", "final ReviewDecision"],
        "Codex may explain the review; it cannot invent the person's watch.",
        execution="human_decision",
        owner="human_reviewer",
    ),
    _tool(
        "delivery",
        "Copy the verified approved MP4 into a local package",
        "control",
        "publish export",
        ["effective human final approval", "current QA and rights"],
        ["verified local package"],
        "Does not upload to a platform.",
    ),
)

EXTENSIONS = tuple(
    ExtensionBoundary.model_validate(
        dict(
            kind=kind,
            approved_location=location,
            consumer=consumer,
            required_evidence=evidence,
            prohibited_authority=["final approval", "rights override", "TimeMap bypass"],
        )
    )
    for kind, location, consumer, evidence in (
        (
            "skill",
            ".codex/skills/<name>/SKILL.md",
            "Codex",
            ["scope", "tool routing", "policy precedence", "reviewed references"],
        ),
        (
            "editorial_reference",
            ".codex/skills/<name>/references/",
            "Codex direction brief",
            ["source", "eligibility", "unsupported cases", "license for copied content"],
        ),
        (
            "local_tool",
            "src/clipforge/<plane>/ with CLI adapter",
            "typed service",
            ["typed contract", "failure tests", "CLI catalogue entry"],
        ),
        (
            "mcp",
            "src/clipforge/assets/ or approved external provider adapter",
            "asset/intake service",
            ["ADR when adding boundary", "provenance", "rights", "confined local handoff"],
        ),
        (
            "renderer_component",
            "apps/renderer/src/ with typed Python/TS event",
            "production composition",
            ["allowlist", "purpose", "geometry", "frame tests", "recipe fingerprint"],
        ),
        (
            "asset_pack",
            "ignored work root plus license catalogue",
            "asset service",
            ["file hash", "license", "content tags", "campaign permission"],
        ),
    )
)


def capability(name: str) -> OperatorCapability:
    for item in CAPABILITIES:
        if item.capability_id == name:
            return item
    raise ClipforgeError(f"unknown operator capability {name}; run clipforge operator tools")


def validate_catalogue(root: object) -> None:
    """Resolve every advertised command against the real CLI without running it."""
    ids = [item.capability_id for item in CAPABILITIES]
    if len(ids) != len(set(ids)):
        raise ClipforgeError("operator capability ids are duplicated")
    for item in CAPABILITIES:
        current: object = root
        for name in item.command:
            commands = getattr(current, "commands", None)
            if not isinstance(commands, dict) or name not in commands:
                raise ClipforgeError(f"operator capability {item.capability_id} advertises a missing command")
            current = commands[name]
        if isinstance(getattr(current, "commands", None), dict):
            raise ClipforgeError(f"operator capability {item.capability_id} must name an executable command")


def role_policy() -> WorkflowRolePolicy:
    return WorkflowRolePolicy()
