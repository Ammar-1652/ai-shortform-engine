"""Deterministic face-follow reframing. A track is geometry, not a person or a speaker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.probe import probe_hero
from clipforge.hero.reframe import (
    ReframeError,
    assert_unlinked,
    build_face_follow,
    evidence_digest,
    facts_line,
    max_crop_movement,
    reject_evidence_reference,
)
from clipforge.media.workspace import SourceWorkspace
from clipforge.publish.errors import PublishError
from clipforge.publish.preflight import _reframe_binding, cache_fingerprint
from clipforge.qa.technical import TechnicalInputs, _reframing
from clipforge.review.final_gate import _difference
from clipforge.schemas.advanced import (
    AdvancedHeroDraftSetDocument,
    AdvancedHeroPlanDocument,
    ReframingStrategy,
    ReframingWindow,
)
from clipforge.schemas.jobs import QAStatus
from clipforge.schemas.reframe import FaceFollowSample, FaceFollowTrajectory, ReframePlanDocument
from clipforge.schemas.time import TimelineSegment, TimeMapDocument, digest_time_map
from clipforge.schemas.vision import FaceDetectionSample, NormalizedBoundingBox
from clipforge.storage import Database
from clipforge.timeline import frame_start_us
from clipforge.timeline.framerate import FrameRate

_SHA = "ab" * 32
_OTHER = "cd" * 32
_WIDTH = 320
_HEIGHT = 180
_DURATION = 1_000_000


def _box(x: float, y: float = 0.4, width: float = 0.12, height: float = 0.18) -> NormalizedBoundingBox:
    return NormalizedBoundingBox(x=x, y=y, width=width, height=height)


def _sample(
    index: int,
    timestamp: int,
    x: float,
    *,
    confidence: float = 0.9,
    track: str = "track-1",
    width: float = 0.12,
) -> FaceDetectionSample:
    box = _box(x, width=width)
    return FaceDetectionSample(
        detection_id=f"det-{index}",
        scene_id="scene-0",
        timestamp_us=timestamp,
        confidence=confidence,
        bounding_box=box,
        center_x=box.x + (box.width / 2),
        center_y=box.y + (box.height / 2),
        area_ratio=box.width * box.height,
        track_id=track,
    )


def _track(
    xs: list[float] | None = None, *, confidence: float = 0.9, width: float = 0.12
) -> list[FaceDetectionSample]:
    times = [0, 200_000, 400_000, 600_000, 800_000, 999_999]
    values = xs if xs is not None else [0.30, 0.31, 0.32, 0.33, 0.34, 0.35]
    return [
        _sample(index, stamp, value, confidence=confidence, width=width)
        for index, (stamp, value) in enumerate(zip(times, values, strict=True))
    ]


def _time_map(duration_us: int = _DURATION, source_start_us: int = 0) -> TimeMapDocument:
    return TimeMapDocument(
        time_map_id="map-1",
        segments=[
            TimelineSegment(
                segment_id="seg-1",
                source_start_us=source_start_us,
                source_end_us=source_start_us + duration_us,
            )
        ],
    )


def _plan(**overrides: object) -> ReframePlanDocument:
    time_map = overrides.pop("time_map", None)
    document = time_map if isinstance(time_map, TimeMapDocument) else _time_map()
    values: dict[str, object] = {
        "samples": _track(),
        "source_width": _WIDTH,
        "source_height": _HEIGHT,
        "time_map": document,
        "time_map_sha256": digest_time_map(document),
        "source_sha256": _SHA,
        "analysis_source_sha256": _SHA,
        "analysis_present": True,
        "producer_succeeded": True,
        "visual_analysis_id": "analysis-1",
        "visual_analysis_sha256": _OTHER,
        "producer_job_id": "job-visual",
        "plan_id": "reframe-1",
        "source_asset_id": "source-1",
        "created_by": "ada",
        "tool_version": "0.29.0",
        "profile_fingerprint": _SHA,
        "face_sample_interval_us": 500_000,
    }
    values.update(overrides)
    return build_face_follow(**values)  # type: ignore[arg-type]


def test_one_track_builds_a_face_follow_plan() -> None:
    document = _plan()
    assert document.applied_strategy == "face_follow"
    assert document.requested_strategy == "face_follow"
    assert document.fallback_reason == ""
    assert document.face_track_id == "track-1"
    assert document.trajectory is not None
    assert document.trajectory_sha256 == document.trajectory.digest()
    assert "speaker" not in document.model_dump_json()
    assert max_crop_movement(document) <= 12
    assert "requested=face_follow" in facts_line(document)


def test_multiple_faces_block_explicit_face_follow() -> None:
    samples = [*_track(), _sample(9, 500_000, 0.6, track="track-2")]
    with pytest.raises(ReframeError, match="face_follow_requires_one_track"):
        _plan(samples=samples)


def test_missing_visual_analysis_blocks() -> None:
    with pytest.raises(ReframeError, match="visual_analysis_missing"):
        _plan(samples=[], analysis_present=False)


def test_stale_visual_analysis_blocks() -> None:
    with pytest.raises(ReframeError, match="visual_analysis_stale"):
        _plan(analysis_source_sha256=_OTHER)


def test_failed_producer_blocks() -> None:
    with pytest.raises(ReframeError, match="visual_analysis_producer_failed"):
        _plan(producer_succeeded=False)


def test_insufficient_coverage_blocks() -> None:
    samples = _track()[:2]
    with pytest.raises(ReframeError, match="face_track_coverage_insufficient"):
        _plan(samples=samples)


def test_low_confidence_blocks() -> None:
    with pytest.raises(ReframeError, match="face_track_confidence_insufficient"):
        _plan(samples=_track(confidence=0.2))


def test_long_gap_blocks() -> None:
    samples = [_sample(0, 0, 0.3), _sample(1, 900_000, 0.32)]
    with pytest.raises(ReframeError, match="face_track_gap_too_long"):
        _plan(samples=samples)


def test_crop_out_of_bounds_blocks() -> None:
    with pytest.raises(ReframeError, match="face_follow_crop_out_of_bounds"):
        _plan(samples=_track(xs=[0.02, 0.02, 0.02, 0.02, 0.02, 0.02], width=0.9))


def test_fast_motion_blocks() -> None:
    samples = [
        _sample(index, min(999_999, index * 33_333), 0.36 if index < 15 else 0.66, width=0.08)
        for index in range(30)
    ]
    with pytest.raises(ReframeError, match="face_follow_motion_too_fast"):
        _plan(samples=samples)


def test_trajectory_is_deterministic_and_changes_with_evidence() -> None:
    first = _plan()
    second = _plan()
    assert first.trajectory_sha256 == second.trajectory_sha256
    assert first.plan_fingerprint == second.plan_fingerprint
    moved = _plan(samples=_track(xs=[0.32, 0.33, 0.34, 0.35, 0.36, 0.37]))
    assert moved.trajectory_sha256 != first.trajectory_sha256


def test_source_and_analysis_hashes_bind_the_plan() -> None:
    original = _plan()
    changed_source = _plan(source_sha256="ef" * 32, analysis_source_sha256="ef" * 32)
    changed_analysis = _plan(visual_analysis_sha256="11" * 32)
    assert changed_source.plan_fingerprint != original.plan_fingerprint
    assert changed_analysis.plan_fingerprint != original.plan_fingerprint
    assert changed_source.source_sha256 != original.source_sha256


def test_contracts_reject_bad_geometry() -> None:
    document = _plan()
    assert document.trajectory is not None
    sample = document.trajectory.samples[0]
    with pytest.raises(ValidationError):
        FaceFollowSample.model_validate(sample.model_dump() | {"confidence": float("nan")})
    with pytest.raises(ValidationError):
        FaceFollowSample.model_validate(sample.model_dump() | {"output_us": -1})
    with pytest.raises(ValidationError):
        FaceFollowSample.model_validate(sample.model_dump() | {"crop_x": -1})
    with pytest.raises(ValidationError):
        FaceFollowSample.model_validate(sample.model_dump() | {"crop_width": _WIDTH})
    with pytest.raises(ValidationError):
        ReframePlanDocument.model_validate(document.model_dump() | {"extra": 1})
    backwards = document.trajectory.model_dump()
    backwards["samples"][2]["output_us"] = 1
    with pytest.raises(ValidationError):
        FaceFollowTrajectory.model_validate(backwards)
    with pytest.raises(ValidationError):
        ReframePlanDocument.model_validate(document.model_dump() | {"created_by": "/tmp/secret"})
    with pytest.raises(ValidationError):
        ReframePlanDocument.model_validate(document.model_dump() | {"fallback_reason": "https://example.test"})


def test_symlink_traversal_and_outside_root_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    target = root / "visual.json"
    target.write_text("{}", encoding="utf-8")
    linked = root / "linked.json"
    linked.symlink_to(target)
    with pytest.raises(ReframeError, match="unsafe_path"):
        assert_unlinked(linked, root)
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child"
    child.symlink_to(root, target_is_directory=True)
    nested = child / "visual.json"
    with pytest.raises(ReframeError, match="unsafe_path"):
        assert_unlinked(nested, parent)
    for value in ("../secret", "/tmp/visual.json", "file:///tmp/visual.json", "https://example.test/a", "a\\b"):
        with pytest.raises(ReframeError, match="unsafe_path"):
            reject_evidence_reference(value)


def test_corrupt_advanced_mp4_is_rejected(tmp_path: Path) -> None:
    video = tmp_path / "advanced.mp4"
    video.write_bytes(b"not a media file")
    with pytest.raises(MediaError):
        probe_hero(video, expected_duration_us=1_000_000)


def test_changed_trajectory_invalidates_qa(tmp_path: Path) -> None:
    document = _plan()
    workspace = SourceWorkspace(tmp_path, "project-1", "source-1")
    path = workspace.reframe_plan_file("cand-1")
    path.parent.mkdir(parents=True)
    path.write_text(document.model_dump_json(), encoding="utf-8")
    assert document.trajectory is not None
    windows = []
    samples = document.trajectory.samples
    for index, sample in enumerate(samples):
        end = samples[index + 1].output_us if index + 1 < len(samples) else _DURATION
        windows.append(
            ReframingWindow(
                window_id=f"window-{index}",
                strategy_id=ReframingStrategy(strategy_id="face_follow"),
                output_start_us=sample.output_us,
                output_end_us=end,
                source_x=sample.crop_x + (8 if index == 0 else 0),
                source_y=sample.crop_y,
                source_width=sample.crop_width,
                source_height=sample.crop_height,
                frame_width=sample.frame_width,
                frame_height=sample.frame_height,
            )
        )
    plan = AdvancedHeroPlanDocument.model_construct(
        candidate_id="cand-1",
        reframing_strategy="face_follow",
        source_sha256=_SHA,
        visual_analysis_sha256=_OTHER,
        time_map_sha256=document.time_map_sha256,
        windows=windows,
    )
    inputs = TechnicalInputs(
        database=Database(tmp_path / "missing.sqlite"),
        workspace=workspace,
        root=tmp_path,
        document=AdvancedHeroDraftSetDocument.model_construct(reframing_strategy="face_follow"),
        artifact_id="artifact-1",
        manifest_sha256=_SHA,
        plans=(plan,),
        source_sha256=_SHA,
        hero_artifact_id="hero-1",
        hero_manifest_sha256=_SHA,
        hero_alignment_sha256={},
        hero_plan_sha256={},
        visual_sha256=_OTHER,
        duration_us=_DURATION,
    )
    check = _reframing(inputs)
    assert check.status is QAStatus.FAIL
    assert "visual_analysis_stale" in check.evidence
    from clipforge.hero.reframe import windows_follow_trajectory

    assert windows_follow_trajectory(document, list(plan.windows), _DURATION) is False


def test_changed_trajectory_invalidates_final_approval_and_delivery(tmp_path: Path) -> None:
    stored = {
        "advanced_artifact_id": "artifact-1",
        "advanced_manifest_sha256": _SHA,
        "qa_set_id": "qa-1",
        "qa_set_sha256": _SHA,
        "source_sha256": _SHA,
        "trajectory_sha256": _OTHER,
        "reframing_strategy": "face_follow",
        "delivery_manifest_sha256": "",
    }
    current = dict(stored)
    current["trajectory_sha256"] = "ef" * 32
    assert _difference(stored, current) == "stale_final_review"
    document = _plan()
    workspace = SourceWorkspace(tmp_path, "project-1", "source-1")
    side = workspace.reframe_plan_file("cand-1")
    side.parent.mkdir(parents=True)
    side.write_text(document.model_dump_json(), encoding="utf-8")
    plan = AdvancedHeroPlanDocument.model_construct(
        candidate_id="cand-1",
        reframing_strategy="face_follow",
        windows=[],
    )
    with pytest.raises(PublishError) as caught:
        _reframe_binding(workspace, plan, "11" * 32, _SHA)
    assert caught.value.category == "visual_analysis_stale"


def test_delivery_fingerprint_tracks_the_trajectory(tmp_path: Path) -> None:
    from clipforge.publish.preflight import DeliveryFacts

    base = {field: "" for field in DeliveryFacts.__dataclass_fields__}
    base.update(
        {
            "source_duration_us": 1,
            "candidate_rank": 1,
            "advanced_artifact_size": 1,
            "output_duration_us": 1,
            "video_size": 1,
            "caption_cues": (),
            "broll": (),
            "sfx": (),
            "typography": (),
            "diagrams": (),
            "emphasis": (),
            "video_path": tmp_path / "video.mp4",
            "narration_path": None,
            "workspace": SourceWorkspace(tmp_path, "project-1", "source-1"),
            "reframing_strategy": "face_follow",
            "trajectory_sha256": _SHA,
        }
    )
    first = DeliveryFacts(**base)  # type: ignore[arg-type]
    second = DeliveryFacts(**(base | {"trajectory_sha256": _OTHER}))  # type: ignore[arg-type]
    assert cache_fingerprint(first) != cache_fingerprint(second)


def test_reframe_blocker_is_per_source(tmp_path: Path) -> None:
    from clipforge.campaign.production import ReframeFacts, _Bound, reframe_blocker, reframe_facts
    from clipforge.schemas.campaign_run import (
        STAGES,
        CampaignCandidateRecord,
        CampaignSourceRun,
        CampaignStageRecord,
    )

    def source(source_id: str) -> CampaignSourceRun:
        return CampaignSourceRun(
            source_id=source_id,
            source_sha256=_SHA,
            rights_state="owned",
            stages=[
                CampaignStageRecord(stage=stage, status="succeeded", reason_code="reused") for stage in STAGES
            ],
            candidates=[
                CampaignCandidateRecord(
                    candidate_id="cand-1",
                    rank=1,
                    selection_reason="kept",
                    alignment_status="alignment_not_claimed",
                    narration_status="narration_not_requested",
                    qa_status="pass",
                    delivery_status="present",
                )
            ],
            status="succeeded",
            reason_code="verified",
            cache_status="hit",
        )

    bound = _Bound(source_id="src-a", binding=None, reason=None, expected_sha256=_SHA)
    assert reframe_blocker(bound, source("src-a"), tmp_path) is None
    facts = reframe_facts(bound, source("src-b"), tmp_path)
    assert facts == ReframeFacts(cache_hit=False)
    assert facts.blocker == "none"


def test_read_only_verify_leaves_files_unchanged(tmp_path: Path) -> None:
    from clipforge.hero.reframe_inspect import verify_reframe

    database_path = tmp_path / "clipforge.sqlite"
    database = Database(database_path)
    database.initialize()
    before = database_path.read_bytes()
    with pytest.raises(MediaError):
        verify_reframe(database, "missing-source", "cand-1", tmp_path)
    assert database_path.read_bytes() == before
    assert list(tmp_path.rglob("reframe.json")) == []


def test_contain_strategy_needs_no_face_evidence(tmp_path: Path) -> None:
    plan = AdvancedHeroPlanDocument.model_construct(
        candidate_id="cand-1", reframing_strategy="contain", windows=[]
    )
    binding = _reframe_binding(SourceWorkspace(tmp_path, "project-1", "source-1"), plan, _SHA, _SHA)
    assert binding.applied == "contain"
    assert binding.trajectory_sha256 == ""
    assert not (tmp_path / "reframe.json").exists()


def test_time_map_offset_and_jump_cut_and_endpoint() -> None:
    from clipforge.hero.reframe import frame_count_for_duration

    start = 117_610_000
    duration = 2_000_000
    stamps = [start + offset for offset in (0, 500_000, 1_000_000, 1_500_000, 2_000_000)]
    samples = [_sample(index, stamp, 0.4, width=0.1) for index, stamp in enumerate(stamps)]
    document = _plan(samples=samples, time_map=_time_map(duration, start))
    assert document.trajectory is not None
    by_output = {item.output_us: item.source_us for item in document.trajectory.samples}
    assert by_output[100_000] == 117_710_000
    assert by_output[700_000] == 118_310_000
    assert by_output[1_500_000] == 119_110_000
    assert document.trajectory.samples[-1].output_us < duration
    assert frame_start_us(frame_count_for_duration(duration), FrameRate(30, 1)) >= duration
    jump = TimeMapDocument(
        time_map_id="map-jump",
        segments=[
            TimelineSegment(segment_id="seg-a", source_start_us=0, source_end_us=500_000),
            TimelineSegment(segment_id="seg-b", source_start_us=2_000_000, source_end_us=2_500_000),
        ],
    )
    first = [_sample(index, stamp, 0.4, width=0.1) for index, stamp in enumerate((0, 250_000, 500_000))]
    second = [
        _sample(index + 10, stamp, 0.42, width=0.1, track="track-1")
        for index, stamp in enumerate((2_000_000, 2_250_000, 2_500_000))
    ]
    jumped = _plan(samples=[*first, *second], time_map=jump)
    assert jumped.trajectory is not None
    jumped_map = {item.output_us: item.source_us for item in jumped.trajectory.samples}
    assert jumped_map[0] == 0
    assert jumped_map[700_000] == 2_200_000


def test_production_cadence_succeeds_and_a_longer_gap_fails() -> None:
    samples = [_sample(index, stamp, 0.4, width=0.1) for index, stamp in enumerate((0, 500_000, 1_000_000))]
    document = _plan(samples=samples, time_map=_time_map(1_000_000))
    assert document.evidence is not None
    assert document.evidence.face_sample_interval_us == 500_000
    assert document.evidence.max_gap_us == 500_000
    with pytest.raises(ReframeError, match="face_track_gap_too_long"):
        _plan(
            samples=[_sample(0, 0, 0.4, width=0.1), _sample(1, 1_000_001, 0.4, width=0.1)],
            time_map=_time_map(1_500_000),
        )


def test_ntsc_frame_clock_tolerance_covers_nearest_pts_without_hiding_long_gaps() -> None:
    from clipforge.hero.reframe import frame_period_tolerance_us

    assert frame_period_tolerance_us(30_000, 1_001) == 33_367
    stamps = (0, 500_500, 1_001_000, 1_501_500)
    samples = [_sample(index, stamp, 0.4, width=0.1) for index, stamp in enumerate(stamps)]
    with pytest.raises(ReframeError, match="face_track_gap_too_long"):
        _plan(samples=samples, time_map=_time_map(1_501_501), gap_tolerance_us=0)
    accepted = _plan(
        samples=samples,
        time_map=_time_map(1_501_501),
        gap_tolerance_us=frame_period_tolerance_us(30_000, 1_001),
    )
    assert accepted.evidence is not None
    assert accepted.evidence.gap_tolerance_us == 33_367
    with pytest.raises(ReframeError, match="face_track_gap_too_long"):
        _plan(
            samples=[_sample(0, 0, 0.4, width=0.1), _sample(1, 1_000_001, 0.4, width=0.1)],
            time_map=_time_map(1_500_000),
            gap_tolerance_us=frame_period_tolerance_us(30_000, 1_001),
        )


def test_duplicate_skipped_and_unaligned_frames_fail() -> None:
    document = _plan()
    assert document.trajectory is not None
    payload = document.trajectory.model_dump()
    duplicate = json.loads(json.dumps(payload))
    duplicate["samples"][1]["output_us"] = duplicate["samples"][0]["output_us"]
    with pytest.raises(ValidationError, match="strictly increasing"):
        FaceFollowTrajectory.model_validate(duplicate)
    skipped = json.loads(json.dumps(payload))
    skipped["samples"][1]["output_us"] = frame_start_us(2, FrameRate(30, 1))
    with pytest.raises(ValidationError, match="30/1 frame start"):
        FaceFollowTrajectory.model_validate(skipped)
    skewed = json.loads(json.dumps(payload))
    skewed["samples"][1]["output_us"] = 100
    with pytest.raises(ValidationError, match="30/1 frame start"):
        FaceFollowTrajectory.model_validate(skewed)


def test_frame_counts_match_the_canonical_time_map() -> None:
    from clipforge.hero.reframe import frame_count_for_duration

    assert frame_count_for_duration(1_000_000) == 30
    assert frame_count_for_duration(1_000_001) == 31
    assert frame_count_for_duration(18_475_000) == 555
    assert frame_count_for_duration(18_773_000) == 564


def test_recompute_matches_build_and_fingerprint_binds_inputs() -> None:
    first = _plan()
    second = _plan()
    assert first.trajectory is not None and second.trajectory is not None
    assert first.trajectory.model_dump() == second.trajectory.model_dump()
    assert first.trajectory_sha256 == second.trajectory_sha256
    assert evidence_digest(first).model_dump() == evidence_digest(second).model_dump()
    assert first.plan_fingerprint == second.plan_fingerprint
    changed_job = _plan(producer_job_id="job-other")
    assert changed_job.plan_fingerprint != first.plan_fingerprint
    with pytest.raises(ReframeError, match="time_map_stale"):
        _plan(time_map_sha256="11" * 32)


def test_explicit_face_follow_does_not_report_contain(tmp_path: Path) -> None:
    from clipforge.campaign.production import ReframeFacts

    facts = ReframeFacts(
        requested="face_follow",
        applied="none",
        status="blocked",
        blocker="visual_analysis_missing",
    )
    assert facts.applied != "contain"
    assert facts.blocker == "visual_analysis_missing"
    assert not (tmp_path / "reframe.json").exists()

