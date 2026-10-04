"""Models written to ``schemas/generated`` for later TypeScript consumers.

``ContractModel`` and ``Versioned`` are bases, not documents. They are the only
schema classes excluded from ``CONTRACT_MODELS``. Every other concrete subclass
must be listed there.
"""

from __future__ import annotations

from pydantic import BaseModel

from clipforge.schemas.advanced import (
    AdvancedHeroCacheRecord,
    AdvancedHeroDraftOutput,
    AdvancedHeroDraftSetDocument,
    AdvancedHeroPlanDocument,
    AdvancedHeroProfile,
    AdvancedHeroRenderInput,
    AssetBinding,
    AudioMixEvent,
    DiagramEvent,
    DiagramPayload,
    EmphasisEvent,
    ReframingStrategy,
    ReframingWindow,
    TypographyEvent,
)
from clipforge.schemas.candidates import (
    CandidateDeduplicationDecision,
    CandidateEvidenceBundle,
    CandidateFilterDecision,
    CandidateMiningCacheRecord,
    CandidateMiningDocument,
    CandidateMiningProfile,
    CandidateMiningSummary,
    CandidateScoreBreakdown,
    EditOpportunityWeights,
    QualityWeights,
)
from clipforge.schemas.editorial import (
    AudioEvent,
    BrollEvent,
    CandidateClip,
    CandidateEvidence,
    CaptionCue,
    EditPlan,
    MotionEvent,
    OutputInterval,
)
from clipforge.schemas.governance import (
    AssetLicenseRecord,
    AssetReference,
    CampaignProfile,
    ComplianceResult,
    ComplianceRule,
    ReviewDecision,
)
from clipforge.schemas.hero import (
    AlignedWord,
    ForcedAlignmentDocument,
    HeroCacheRecord,
    HeroDraftOutput,
    HeroDraftSetDocument,
    HeroPlanDocument,
    HeroProfile,
    HeroRenderInput,
)
from clipforge.schemas.ingest import (
    AudioStreamInfo,
    ColorMetadata,
    DerivativeCacheRecord,
    MediaClassification,
    MediaFormatInfo,
    MediaTimelineInfo,
    NormalizedMediaProbe,
    RationalNumber,
    RotationMetadata,
    SourceIngestManifest,
    StreamDisposition,
    StreamSelection,
    VideoStreamInfo,
)
from clipforge.schemas.jobs import JobRecord, QACheck, QAResult, RenderArtifact, RenderJob
from clipforge.schemas.media import (
    FaceObservation,
    MediaProbe,
    Scene,
    SegmentDiagnostics,
    SourceAsset,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)
from clipforge.schemas.preview import (
    CandidateRoughPreview,
    RoughCaptionCue,
    RoughPreviewCacheRecord,
    RoughPreviewProfile,
    RoughPreviewRenderInput,
    RoughPreviewSetDocument,
    RoughPreviewSetSummary,
)
from clipforge.schemas.project import Project
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.qa import PolicyDigest, QACacheRecord, QASetDocument
from clipforge.schemas.time import SourceTimeRange, TimelineSegment, TimeMapDocument
from clipforge.schemas.transcription import TranscriptionCacheRecord, TranscriptionProfile
from clipforge.schemas.vision import (
    ContactSheet,
    EvidenceFile,
    FaceDetectionSample,
    FaceKeypoint,
    FrameEvidence,
    FrameVisualMetrics,
    NormalizedBoundingBox,
    SceneVisualEvidence,
    VisualAnalysisCacheRecord,
    VisualAnalysisDocument,
    VisualAnalysisSummary,
)

CONTRACT_MODELS: tuple[type[BaseModel], ...] = (
    Project,
    SourceAsset,
    MediaProbe,
    SourceTimeRange,
    TimelineSegment,
    TimeMapDocument,
    TranscriptWord,
    TranscriptSegment,
    SegmentDiagnostics,
    Transcript,
    TranscriptionProfile,
    TranscriptionCacheRecord,
    Scene,
    FaceObservation,
    NormalizedBoundingBox,
    FaceKeypoint,
    FrameVisualMetrics,
    EvidenceFile,
    FrameEvidence,
    FaceDetectionSample,
    SceneVisualEvidence,
    ContactSheet,
    VisualAnalysisSummary,
    VisualAnalysisDocument,
    VisualAnalysisCacheRecord,
    QualityWeights,
    EditOpportunityWeights,
    CandidateMiningProfile,
    CandidateEvidenceBundle,
    CandidateScoreBreakdown,
    CandidateDeduplicationDecision,
    CandidateFilterDecision,
    CandidateMiningSummary,
    CandidateMiningDocument,
    CandidateMiningCacheRecord,
    RoughPreviewProfile,
    RoughCaptionCue,
    RoughPreviewRenderInput,
    CandidateRoughPreview,
    RoughPreviewSetSummary,
    RoughPreviewSetDocument,
    RoughPreviewCacheRecord,
    HeroProfile,
    AlignedWord,
    ForcedAlignmentDocument,
    HeroRenderInput,
    HeroDraftOutput,
    HeroDraftSetDocument,
    HeroCacheRecord,
    HeroPlanDocument,
    AdvancedHeroProfile,
    ReframingStrategy,
    ReframingWindow,
    TypographyEvent,
    DiagramPayload,
    DiagramEvent,
    AssetBinding,
    AudioMixEvent,
    EmphasisEvent,
    AdvancedHeroRenderInput,
    AdvancedHeroDraftOutput,
    AdvancedHeroDraftSetDocument,
    AdvancedHeroCacheRecord,
    AdvancedHeroPlanDocument,
    CandidateEvidence,
    CandidateClip,
    CampaignProfile,
    ComplianceRule,
    ComplianceResult,
    EditPlan,
    CaptionCue,
    MotionEvent,
    BrollEvent,
    AudioEvent,
    OutputInterval,
    AssetReference,
    AssetLicenseRecord,
    RenderJob,
    RenderArtifact,
    QACheck,
    QAResult,
    PolicyDigest,
    QASetDocument,
    QACacheRecord,
    ReviewDecision,
    JobRecord,
    ArtifactProvenance,
    AudioStreamInfo,
    ColorMetadata,
    DerivativeCacheRecord,
    MediaClassification,
    MediaFormatInfo,
    MediaTimelineInfo,
    NormalizedMediaProbe,
    RationalNumber,
    RotationMetadata,
    SourceIngestManifest,
    StreamDisposition,
    StreamSelection,
    VideoStreamInfo,
)


def schema_title(model: type[BaseModel]) -> str:
    """File stem for a model. ``TimeMapDocument`` is published as ``TimeMap``."""
    schema = model.model_json_schema()
    title = schema.get("title")
    if not isinstance(title, str) or not title:
        return model.__name__
    return title
