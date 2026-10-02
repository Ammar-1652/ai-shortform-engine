"""Contract validation, serialization, and schema export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.errors import ComplianceGateError, SchemaExportError
from clipforge.schemas import (
    AssetLicenseRecord,
    CampaignProfile,
    CandidateClip,
    CandidateEvidence,
    CandidateStatus,
    CaptionCue,
    ComplianceResult,
    ComplianceRule,
    ComplianceStatus,
    EditPlan,
    EvidenceKind,
    FaceObservation,
    JobRecord,
    JobStatus,
    MediaProbe,
    MotionEvent,
    MotionPurpose,
    OutputInterval,
    Project,
    QACheck,
    QAKind,
    QAResult,
    QAStatus,
    ReviewDecision,
    RightsStatus,
    Scene,
    SourceTimeRange,
    TimeMapDocument,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
    assert_schemas_current,
    export_schemas,
    is_vertical_9_16,
    require_compliance_cleared,
    require_rights_cleared,
)
from clipforge.schemas.common import ContractModel, Versioned
from clipforge.schemas.registry import CONTRACT_MODELS
from tests.helpers import jump_digest, jump_map, provenance, stamp

FIXTURE = Path(__file__).parent / "fixtures" / "jump_cut_time_map.json"
ROOT = Path(__file__).resolve().parents[1]


def test_fixture_round_trip_and_duration() -> None:
    document = TimeMapDocument.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
    assert document.to_time_map().total_output_duration() == 10_000_000
    again = TimeMapDocument.model_validate(document.model_dump(mode="json"))
    assert again == document


def test_project_round_trip() -> None:
    project = Project(
        project_id="project-1",
        name="  Launch reel  ",
        created_at=stamp(),
        provenance=provenance(),
        metadata={"language": "en"},
    )
    assert project.name == "Launch reel"
    restored = Project.model_validate(project.model_dump(mode="json"))
    assert restored == project


def test_invalid_timing_and_versions() -> None:
    with pytest.raises(ValidationError):
        SourceTimeRange(start_us=5, end_us=5)
    with pytest.raises(ValidationError):
        SourceTimeRange(start_us=5, end_us=4)
    with pytest.raises(ValidationError):
        SourceTimeRange(start_us=-1, end_us=5)
    with pytest.raises(ValidationError):
        TimeMapDocument(
            time_map_id="map-1",
            segments=[],
            schema_version="9.9.9",  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError, match="overlap"):
        TimeMapDocument.model_validate(
            {
                "time_map_id": "map-bad",
                "segments": [
                    {"segment_id": "a", "source_start_us": 0, "source_end_us": 5},
                    {"segment_id": "b", "source_start_us": 4, "source_end_us": 9},
                ],
            }
        )


def test_invalid_status_and_smuggled_score_are_rejected() -> None:
    with pytest.raises(ValidationError):
        JobRecord.model_validate(
            {
                "job_id": "job-1",
                "project_id": "project-1",
                "kind": "ingest",
                "status": "shipped",
                "created_at": stamp().isoformat(),
                "updated_at": stamp().isoformat(),
            }
        )
    with pytest.raises(ValidationError):
        ComplianceResult.model_validate(
            {
                "result_id": "result-1",
                "rule_id": "rule-1",
                "status": "pass",
                "evidence": "license on file",
                "compliance_score": 0.3,
            }
        )


def test_failed_job_requires_an_error() -> None:
    with pytest.raises(ValidationError):
        JobRecord(
            job_id="job-1",
            project_id="project-1",
            kind="ingest",
            status=JobStatus.FAILED,
            created_at=stamp(),
            updated_at=stamp(),
        )


def test_face_is_not_a_speaker_and_scene_needs_both_channels() -> None:
    with pytest.raises(ValidationError):
        FaceObservation(
            observation_id="face-1",
            source_asset_id="asset-1",
            time_range=SourceTimeRange(start_us=0, end_us=1_000),
            confidence=0.9,
            speaker_attribution="speaking",  # type: ignore[arg-type]
            provenance=provenance(["asset-1"]),
        )
    with pytest.raises(ValidationError, match="Transcript-only"):
        Scene(
            scene_id="scene-1",
            source_asset_id="asset-1",
            time_range=SourceTimeRange(start_us=0, end_us=1_000),
            transcript_evidence="hello",
            analysis_complete=True,
            provenance=provenance(["asset-1"]),
        )


def test_candidate_ready_gate_ignores_creative_score() -> None:
    shared = {
        "candidate_id": "cand-1",
        "project_id": "project-1",
        "source_asset_id": "asset-1",
        "time_map": jump_map(),
        "creative_score": 1.0,
        "provenance": provenance(["asset-1"]),
        "evidence": [
            CandidateEvidence(evidence_id="ev-t", kind=EvidenceKind.TRANSCRIPT, detail="hook"),
        ],
        "compliance": [
            ComplianceResult(
                result_id="result-1",
                rule_id="rule-1",
                status=ComplianceStatus.FAIL,
                evidence="claim is not allowed",
            )
        ],
    }
    with pytest.raises(ValidationError):
        CandidateClip(status=CandidateStatus.READY_FOR_REVIEW, **shared)
    proposed = CandidateClip(status=CandidateStatus.PROPOSED, **shared)
    assert proposed.creative_score == 1.0
    ready = CandidateClip(
        status=CandidateStatus.READY_FOR_REVIEW,
        candidate_id="cand-2",
        project_id="project-1",
        source_asset_id="asset-1",
        time_map=jump_map(),
        creative_score=0.2,
        provenance=provenance(["asset-1"]),
        evidence=[
            CandidateEvidence(evidence_id="ev-t", kind=EvidenceKind.TRANSCRIPT, detail="hook"),
            CandidateEvidence(evidence_id="ev-v", kind=EvidenceKind.VISUAL, detail="product in frame"),
        ],
        compliance=[
            ComplianceResult(
                result_id="result-1",
                rule_id="rule-1",
                status=ComplianceStatus.PASS,
                evidence="rights record license-1",
            )
        ],
    )
    assert ready.creative_score == 0.2


def test_compliance_and_rights_fail_closed() -> None:
    with pytest.raises(ComplianceGateError, match="Missing evidence"):
        require_compliance_cleared([])
    with pytest.raises(ComplianceGateError, match="creative score"):
        require_compliance_cleared(
            [
                ComplianceResult(
                    result_id="result-1",
                    rule_id="rule-1",
                    status=ComplianceStatus.INSUFFICIENT_EVIDENCE,
                    evidence="model output was not checked",
                )
            ]
        )
    with pytest.raises(ComplianceGateError):
        require_rights_cleared(
            AssetLicenseRecord(
                license_record_id="lic-1",
                asset_id="asset-1",
                status=RightsStatus.UNKNOWN,
                recorded_at=stamp(),
                recorded_by="tester",
            )
        )
    with pytest.raises(ComplianceGateError, match="evidence"):
        require_rights_cleared(
            AssetLicenseRecord(
                license_record_id="lic-1",
                asset_id="asset-1",
                status=RightsStatus.LICENSED,
                license_name="envato",
                recorded_at=stamp(),
                recorded_by="tester",
            )
        )
    require_rights_cleared(
        AssetLicenseRecord(
            license_record_id="lic-1",
            asset_id="asset-1",
            status=RightsStatus.OWNED,
            evidence_uri="file:///licenses/owned.txt",
            recorded_at=stamp(),
            recorded_by="tester",
        )
    )


def test_review_cannot_be_automated_and_final_approval_names_an_artifact() -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(
            review_id="review-1",
            project_id="project-1",
            candidate_id="cand-1",
            subject_kind="candidate",
            decision="approved",
            reviewer_id="ada",
            created_at=stamp(),
            automated=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError, match="artifact_id"):
        ReviewDecision(
            review_id="review-1",
            project_id="project-1",
            subject_kind="final",
            decision="approved",
            reviewer_id="ada",
            created_at=stamp(),
        )


def test_qa_cannot_pass_over_a_failed_check() -> None:
    with pytest.raises(ValidationError, match="checks aggregate"):
        QAResult(
            qa_id="qa-1",
            project_id="project-1",
            artifact_id="artifact-1",
            kind=QAKind.CAMPAIGN_COMPLIANCE,
            status=QAStatus.PASS,
            checks=[QACheck(name="claims", status=QAStatus.FAIL, evidence="unapproved superlative")],
            provenance=provenance(["asset-1"]),
        )


def test_edit_plan_rejects_stale_digest_and_events_past_the_map() -> None:
    with pytest.raises(ValidationError, match="time_map_sha256"):
        EditPlan(
            edit_plan_id="plan-1",
            project_id="project-1",
            candidate_id="cand-1",
            stage="rough",
            time_map=jump_map(),
            time_map_sha256="0" * 64,
            provenance=provenance(["asset-1"]),
        )
    with pytest.raises(ValidationError, match="past the time map"):
        EditPlan(
            edit_plan_id="plan-1",
            project_id="project-1",
            candidate_id="cand-1",
            stage="hero",
            time_map=jump_map(),
            time_map_sha256=jump_digest(),
            captions=[
                CaptionCue(
                    cue_id="cue-1",
                    interval=OutputInterval(output_start_us=0, output_end_us=10_000_001),
                    text="too long",
                )
            ],
            provenance=provenance(["asset-1"]),
        )


def test_motion_requires_a_purpose_and_transcript_words_stay_inside_the_segment() -> None:
    with pytest.raises(ValidationError):
        MotionEvent(
            event_id="motion-1",
            interval=OutputInterval(output_start_us=0, output_end_us=1_000),
            component_id="stat",
        )
    MotionEvent(
        event_id="motion-1",
        interval=OutputInterval(output_start_us=0, output_end_us=1_000),
        purpose=MotionPurpose.NUMBER,
        component_id="stat",
    )
    with pytest.raises(ValidationError, match="outside"):
        Transcript(
            transcript_id="transcript-1",
            project_id="project-1",
            source_asset_id="asset-1",
            asr_model="faster-whisper",
            alignment="approximate",
            segments=[
                TranscriptSegment(
                    segment_id="seg-1",
                    start_us=0,
                    end_us=1_000,
                    text="hi",
                    words=[TranscriptWord(word_id="w-1", text="hi", start_us=900, end_us=1_200)],
                )
            ],
            provenance=provenance(["asset-1"]),
        )


def test_probe_rejects_a_partial_or_impossible_frame_rate() -> None:
    with pytest.raises(ValidationError):
        MediaProbe(
            probe_id="probe-1",
            source_asset_id="asset-1",
            duration_us=1_000,
            frame_rate_numerator=30000,
            provenance=provenance(["asset-1"]),
        )
    with pytest.raises(ValidationError):
        MediaProbe(
            probe_id="probe-1",
            source_asset_id="asset-1",
            duration_us=0,
            provenance=provenance(["asset-1"]),
        )


def test_aspect_helper_and_profile_files() -> None:
    assert is_vertical_9_16(1080, 1920)
    assert not is_vertical_9_16(1920, 1080)
    profile = CampaignProfile.model_validate_json(
        (ROOT / "configs" / "profiles" / "organic.json").read_text(encoding="utf-8")
    )
    rule = ComplianceRule.model_validate_json(
        (ROOT / "configs" / "policies" / "source-rights.json").read_text(encoding="utf-8")
    )
    assert profile.mode.value == "organic"
    assert rule.severity == "block"


def _all_subclasses(root: type[ContractModel]) -> set[type[ContractModel]]:
    found: set[type[ContractModel]] = set()
    stack = list(root.__subclasses__())
    while stack:
        child = stack.pop()
        if child in found:
            continue
        found.add(child)
        stack.extend(child.__subclasses__())
    return found


def test_contract_registry_covers_every_concrete_model() -> None:
    """ContractModel and Versioned are the only schema bases excluded from export."""
    import clipforge.schemas  # noqa: F401

    found = _all_subclasses(ContractModel)
    exported = set(CONTRACT_MODELS)
    excluded = {ContractModel, Versioned}
    assert ContractModel not in exported
    assert Versioned not in exported
    assert not (found - exported - excluded)
    assert not (exported - found)


def test_export_then_check(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    assert_schemas_current(tmp_path)
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert index["schema_version"] == "1.0.0"
    assert "TimeMap" in index["models"]
    assert (tmp_path / "TimeMap.schema.json").is_file()
    (tmp_path / "TimeMap.schema.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(SchemaExportError, match="drifted"):
        assert_schemas_current(tmp_path)


def test_committed_schemas_match() -> None:
    assert_schemas_current(ROOT / "schemas" / "generated")
