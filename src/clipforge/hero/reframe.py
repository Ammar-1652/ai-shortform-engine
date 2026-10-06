"""Deterministic face-follow crops. A track is geometry, not a person and not a speaker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.schemas.advanced import ReframingWindow
from clipforge.schemas.reframe import (
    FaceFollowSample,
    FaceFollowTrajectory,
    FaceTrackEvidence,
    ReframeEvidenceDigest,
    ReframePlanDocument,
)
from clipforge.schemas.time import TimeMapDocument, digest_time_map
from clipforge.schemas.vision import FaceDetectionSample
from clipforge.timeline import FrameRate, SegmentSpec, TimeMap, frame_start_us

_MIN_CONFIDENCE = 0.55
_GAP_TOLERANCE_US = 0
_MAX_STEP_PX = 12
_HEADROOM = 120
_SMOOTHING = 4
_OUTPUT_W = 1080
_OUTPUT_H = 1920
_RATE = FrameRate(30, 1)


class ReframeError(MediaError):
    """face_follow cannot be applied. The message is the blocker code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def frame_count_for_duration(duration_us: int) -> int:
    """How many 30/1 frames start strictly before ``duration_us``."""
    if duration_us <= 0:
        return 0
    timeline = TimeMap([SegmentSpec(segment_id="duration", source_start_us=0, source_end_us=duration_us)])
    return timeline.output_frame_count(_RATE)


def build_face_follow(
    *,
    samples: list[FaceDetectionSample],
    source_width: int,
    source_height: int,
    time_map: TimeMapDocument,
    time_map_sha256: str,
    source_sha256: str,
    analysis_source_sha256: str,
    analysis_present: bool,
    producer_succeeded: bool,
    visual_analysis_id: str,
    visual_analysis_sha256: str,
    producer_job_id: str,
    plan_id: str,
    source_asset_id: str,
    created_by: str,
    tool_version: str,
    profile_fingerprint: str,
    face_sample_interval_us: int,
    gap_tolerance_us: int = _GAP_TOLERANCE_US,
) -> ReframePlanDocument:
    """Return a face-follow plan or raise a specific blocker. There is no contain fallback."""
    if not analysis_present:
        raise ReframeError("visual_analysis_missing")
    if analysis_source_sha256 != source_sha256:
        raise ReframeError("visual_analysis_stale")
    if not producer_succeeded or not producer_job_id:
        raise ReframeError("visual_analysis_producer_failed")
    if digest_time_map(time_map) != time_map_sha256:
        raise ReframeError("time_map_stale")
    if face_sample_interval_us < 1 or gap_tolerance_us < 0:
        raise ReframeError("face_track_gap_too_long")
    mapped = time_map.to_time_map()
    duration_us = mapped.total_output_duration()
    if duration_us < 1 or frame_count_for_duration(duration_us) < 1:
        raise ReframeError("time_map_stale")
    permitted = face_sample_interval_us + gap_tolerance_us
    chosen = _one_track(samples, mapped, permitted)
    trajectory = _trajectory(chosen, source_width, source_height, mapped)
    evidence = _evidence(chosen, duration_us, face_sample_interval_us, gap_tolerance_us)
    track_id = chosen[0].track_id or ""
    body = {
        "applied_strategy": "face_follow",
        "face_sample_interval_us": face_sample_interval_us,
        "fps_denominator": 1,
        "fps_numerator": 30,
        "gap_tolerance_us": gap_tolerance_us,
        "headroom_permille": _HEADROOM,
        "max_step_px": _MAX_STEP_PX,
        "output_height": _OUTPUT_H,
        "output_width": _OUTPUT_W,
        "producer_job_id": producer_job_id,
        "profile_fingerprint": profile_fingerprint,
        "requested_strategy": "face_follow",
        "smoothing_divisor": _SMOOTHING,
        "source_height": source_height,
        "source_sha256": source_sha256,
        "source_width": source_width,
        "time_map_sha256": time_map_sha256,
        "tool_version": tool_version,
        "track_id": track_id,
        "trajectory_sha256": trajectory.digest(),
        "visual_analysis_id": visual_analysis_id,
        "visual_analysis_sha256": visual_analysis_sha256,
    }
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ReframePlanDocument(
        plan_id=plan_id,
        source_asset_id=source_asset_id,
        source_sha256=source_sha256,
        visual_analysis_id=visual_analysis_id,
        visual_analysis_sha256=visual_analysis_sha256,
        producer_job_id=producer_job_id,
        time_map_sha256=time_map_sha256,
        profile_fingerprint=profile_fingerprint,
        face_sample_interval_us=face_sample_interval_us,
        gap_tolerance_us=gap_tolerance_us,
        smoothing_divisor=_SMOOTHING,
        max_step_px=_MAX_STEP_PX,
        headroom_permille=_HEADROOM,
        source_width=source_width,
        source_height=source_height,
        output_width=_OUTPUT_W,
        output_height=_OUTPUT_H,
        fps_numerator=30,
        fps_denominator=1,
        requested_strategy="face_follow",
        applied_strategy="face_follow",
        face_track_id=track_id,
        evidence=evidence,
        trajectory=trajectory,
        trajectory_sha256=trajectory.digest(),
        safe_margin_px=max(1, trajectory.samples[0].crop_height * _HEADROOM // 1000),
        created_by=created_by,
        tool_version=tool_version,
        plan_fingerprint=fingerprint,
    )


def evidence_digest(document: ReframePlanDocument) -> ReframeEvidenceDigest:
    return ReframeEvidenceDigest(
        source_sha256=document.source_sha256,
        visual_analysis_sha256=document.visual_analysis_sha256,
        time_map_sha256=document.time_map_sha256,
        trajectory_sha256=document.trajectory_sha256 or "0" * 64,
        plan_fingerprint=document.plan_fingerprint,
    )


def _one_track(
    samples: list[FaceDetectionSample],
    time_map: TimeMap,
    permitted_gap_us: int,
) -> list[FaceDetectionSample]:
    if not samples:
        raise ReframeError("visual_analysis_missing")
    ranges = [(segment.source_start_us, segment.source_end_us) for segment in time_map.segments]
    chosen: list[FaceDetectionSample] = []
    for start, end in ranges:
        inside = [item for item in samples if start <= item.timestamp_us <= end and item.track_id]
        if not inside:
            raise ReframeError("face_track_coverage_insufficient")
        ordered = sorted(inside, key=lambda item: item.timestamp_us)
        opening = ordered[0].timestamp_us - start
        closing = end - ordered[-1].timestamp_us
        if opening > permitted_gap_us or closing > permitted_gap_us:
            raise ReframeError("face_track_coverage_insufficient")
        previous = ordered[0].timestamp_us
        for item in ordered[1:]:
            if item.timestamp_us - previous > permitted_gap_us:
                raise ReframeError("face_track_gap_too_long")
            previous = item.timestamp_us
        chosen.extend(ordered)
    unique: dict[str, FaceDetectionSample] = {}
    for item in chosen:
        unique.setdefault(item.detection_id, item)
    tracks = {item.track_id for item in unique.values()}
    if len(tracks) != 1:
        raise ReframeError("face_follow_requires_one_track")
    ordered = sorted(unique.values(), key=lambda item: (item.timestamp_us, item.detection_id))
    if any(item.confidence < _MIN_CONFIDENCE for item in ordered):
        raise ReframeError("face_track_confidence_insufficient")
    return ordered


def _trajectory(
    samples: list[FaceDetectionSample],
    width: int,
    height: int,
    time_map: TimeMap,
) -> FaceFollowTrajectory:
    crop_w, crop_h = _crop_size(width, height)
    duration_us = time_map.total_output_duration()
    frames = frame_count_for_duration(duration_us)
    first_source = time_map.output_to_source(0)
    first_face = _face_at(samples, first_source, width, height)
    smooth_x = first_face[0] - (crop_w // 2)
    smooth_y = first_face[1] - (crop_h // 2)
    built: list[FaceFollowSample] = []
    previous_x = _clamp(smooth_x, 0, width - crop_w)
    previous_y = _clamp(smooth_y, 0, height - crop_h)
    for index in range(frames):
        output_us = frame_start_us(index, _RATE)
        if output_us >= duration_us:
            raise ReframeError("time_map_stale")
        source_us = time_map.output_to_source(output_us)
        face = _face_at(samples, source_us, width, height)
        desired_x = face[0] - (crop_w // 2)
        desired_y = face[1] - (crop_h // 2)
        smooth_x += (desired_x - smooth_x) // _SMOOTHING
        smooth_y += (desired_y - smooth_y) // _SMOOTHING
        crop_x = _clamp(smooth_x, 0, width - crop_w)
        crop_y = _clamp(smooth_y, 0, height - crop_h)
        if index and (abs(crop_x - previous_x) > _MAX_STEP_PX or abs(crop_y - previous_y) > _MAX_STEP_PX):
            raise ReframeError("face_follow_motion_too_fast")
        if not _face_inside(face, crop_x, crop_y, crop_w, crop_h):
            raise ReframeError("face_follow_crop_out_of_bounds")
        if not _face_in_safe(face, crop_x, crop_y, crop_w, crop_h):
            raise ReframeError("face_follow_crop_out_of_bounds")
        built.append(
            FaceFollowSample(
                sample_index=index,
                output_us=output_us,
                source_us=source_us,
                crop_x=crop_x,
                crop_y=crop_y,
                crop_width=crop_w,
                crop_height=crop_h,
                face_x=face[2],
                face_y=face[3],
                face_width=face[4],
                face_height=face[5],
                confidence=face[6],
                frame_width=width,
                frame_height=height,
            )
        )
        previous_x = crop_x
        previous_y = crop_y
    return FaceFollowTrajectory(
        track_id=samples[0].track_id or "track",
        samples=built,
        smoothing_divisor=_SMOOTHING,
        max_step_px=_MAX_STEP_PX,
        headroom_permille=_HEADROOM,
        source_width=width,
        source_height=height,
        output_width=_OUTPUT_W,
        output_height=_OUTPUT_H,
    )


def _evidence(
    samples: list[FaceDetectionSample],
    duration_us: int,
    cadence_us: int,
    tolerance_us: int,
) -> FaceTrackEvidence:
    gaps = [samples[index].timestamp_us - samples[index - 1].timestamp_us for index in range(1, len(samples))]
    mean = sum(item.confidence for item in samples) / len(samples)
    return FaceTrackEvidence(
        track_id=samples[0].track_id or "track",
        sample_count=len(samples),
        mean_confidence_permille=int(mean * 1000),
        coverage_permille=1000 if duration_us > 0 else 0,
        max_gap_us=max(gaps, default=0),
        face_sample_interval_us=cadence_us,
        gap_tolerance_us=tolerance_us,
    )


def _face_at(
    samples: list[FaceDetectionSample],
    source_us: int,
    width: int,
    height: int,
) -> tuple[int, int, int, int, int, int, float]:
    previous = samples[0]
    nxt = samples[-1]
    for item in samples:
        if item.timestamp_us <= source_us:
            previous = item
        if item.timestamp_us >= source_us:
            nxt = item
            break
    span = max(1, nxt.timestamp_us - previous.timestamp_us)
    weight = 0 if previous is nxt else (source_us - previous.timestamp_us) / span
    ax, ay, aw, ah, aconf = _box(previous, width, height)
    bx, by, bw, bh, bconf = _box(nxt, width, height)
    cx = int(ax + (bx - ax) * weight)
    cy = int(ay + (by - ay) * weight)
    fw = max(1, int(aw + (bw - aw) * weight))
    fh = max(1, int(ah + (bh - ah) * weight))
    left = max(0, min(width - 1, cx - fw // 2))
    top = max(0, min(height - 1, cy - fh // 2))
    fw = max(1, min(fw, width - left))
    fh = max(1, min(fh, height - top))
    return cx, cy, left, top, fw, fh, min(aconf, bconf)


def _box(sample: FaceDetectionSample, width: int, height: int) -> tuple[int, int, int, int, float]:
    box = sample.bounding_box
    fw = max(1, int(box.width * width))
    fh = max(1, int(box.height * height))
    left = max(0, int(box.x * width))
    top = max(0, int(box.y * height))
    if left + fw > width:
        fw = width - left
    if top + fh > height:
        fh = height - top
    return left + fw // 2, top + fh // 2, fw, fh, sample.confidence


def _crop_size(width: int, height: int) -> tuple[int, int]:
    if width * _OUTPUT_H > height * _OUTPUT_W:
        crop_h = height
        crop_w = max(1, height * _OUTPUT_W // _OUTPUT_H)
    else:
        crop_w = width
        crop_h = max(1, width * _OUTPUT_H // _OUTPUT_W)
    if crop_w > width or crop_h > height:
        raise ReframeError("face_follow_crop_out_of_bounds")
    return crop_w, crop_h


def _face_inside(
    face: tuple[int, int, int, int, int, int, float], x: int, y: int, width: int, height: int
) -> bool:
    _cx, _cy, left, top, fw, fh, _confidence = face
    return left >= x and top >= y and left + fw <= x + width and top + fh <= y + height


def _face_in_safe(
    face: tuple[int, int, int, int, int, int, float],
    x: int,
    y: int,
    width: int,
    height: int,
) -> bool:
    """The face box must sit inside the headroom inset. A face is still not a speaker."""
    _cx, _cy, left, top, fw, fh, _confidence = face
    margin_x = width * _HEADROOM // 1000
    margin_y = height * _HEADROOM // 1000
    if fw > width - (2 * margin_x) or fh > height - (2 * margin_y):
        return False
    return (
        left >= x + margin_x
        and top >= y + margin_y
        and left + fw <= x + width - margin_x
        and top + fh <= y + height - margin_y
    )


def max_crop_movement(document: ReframePlanDocument) -> int:
    trajectory = document.trajectory
    if trajectory is None or len(trajectory.samples) < 2:
        return 0
    movement = 0
    previous = trajectory.samples[0]
    for sample in trajectory.samples[1:]:
        movement = max(movement, abs(sample.crop_x - previous.crop_x), abs(sample.crop_y - previous.crop_y))
        previous = sample
    return movement


def facts_line(document: ReframePlanDocument, *, blocker: str = "") -> str:
    """One QA/review line. It has no filesystem path."""
    trajectory = document.trajectory
    crop_w = 0 if trajectory is None else trajectory.samples[0].crop_width
    crop_h = 0 if trajectory is None else trajectory.samples[0].crop_height
    evidence = document.evidence
    coverage = 0 if evidence is None else evidence.coverage_permille
    confidence = 0 if evidence is None else evidence.mean_confidence_permille
    fallback = document.fallback_reason or "none"
    track = document.face_track_id or "none"
    digest = document.trajectory_sha256 or "none"
    return (
        f"requested={document.requested_strategy} applied={document.applied_strategy} "
        f"fallback={fallback} track={track} trajectory={digest} crop={crop_w}x{crop_h} "
        f"safe=yes movement={max_crop_movement(document)} coverage={coverage} "
        f"confidence={confidence} blocker={blocker or 'none'}"
    )


def window_end_us(document: ReframePlanDocument, index: int, duration_us: int) -> int:
    trajectory = document.trajectory
    if trajectory is None:
        raise ReframeError("visual_analysis_missing")
    if index + 1 < len(trajectory.samples):
        return trajectory.samples[index + 1].output_us
    return duration_us


def windows_follow_trajectory(
    document: ReframePlanDocument,
    windows: list[ReframingWindow],
    duration_us: int,
) -> bool:
    """True when every window is the stored crop for that output frame."""
    trajectory = document.trajectory
    if trajectory is None or len(windows) != len(trajectory.samples) or not windows:
        return False
    if windows[0].output_start_us != 0 or windows[-1].output_end_us != duration_us:
        return False
    for index, (window, sample) in enumerate(zip(windows, trajectory.samples, strict=True)):
        strategy = window.strategy_id.strategy_id
        expected_end = window_end_us(document, index, duration_us)
        if strategy != "face_follow" or window.output_start_us != sample.output_us:
            return False
        if window.output_end_us != expected_end:
            return False
        if (
            window.source_x != sample.crop_x
            or window.source_y != sample.crop_y
            or window.source_width != sample.crop_width
            or window.source_height != sample.crop_height
            or window.frame_width != sample.frame_width
            or window.frame_height != sample.frame_height
        ):
            return False
    return True


def reject_evidence_reference(relative: str) -> None:
    """Reject a path or URL before any filesystem call. The message is unsafe_path."""
    text = relative.strip()
    lowered = text.lower()
    if (
        not text
        or text != relative
        or text.startswith(("/", "\\"))
        or "\\" in text
        or ".." in text.split("/")
        or "://" in lowered
        or lowered.startswith("file:")
        or any(part in {"", "."} for part in text.split("/"))
    ):
        raise ReframeError("unsafe_path")


def assert_unlinked(path: Path, root: Path) -> None:
    """Reject a symlink at the file or any parent before the work root."""
    if path.is_symlink():
        raise ReframeError("unsafe_path")
    root_resolved = root.resolve()
    current = path.parent
    while True:
        if current.is_symlink():
            raise ReframeError("unsafe_path")
        try:
            if current.resolve() == root_resolved:
                return
        except OSError as exc:
            raise ReframeError("unsafe_path") from exc
        if current.parent == current:
            raise ReframeError("unsafe_path")
        current = current.parent


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
