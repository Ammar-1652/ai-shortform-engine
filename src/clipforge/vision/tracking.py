"""Geometry-only face association inside one scene.

A track id is continuity of boxes across nearby samples. It is not a person
and it does not cross a scene boundary. No embedding is computed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from clipforge.vision.constants import (
    TRACKING_CENTER_DISTANCE,
    TRACKING_IOU_THRESHOLD,
    TRACKING_MAX_GAP_US,
)
from clipforge.vision.geometry import NormalizedFace


@dataclass(frozen=True, slots=True)
class TimedFace:
    scene_ordinal: int
    timestamp_us: int
    face: NormalizedFace
    detection_ordinal: int


@dataclass
class _Track:
    ordinal: int
    faces: list[TimedFace]

    @property
    def last(self) -> TimedFace:
        return self.faces[-1]


@dataclass(frozen=True, slots=True)
class TrackedDetection:
    scene_ordinal: int
    timestamp_us: int
    detection_ordinal: int
    face: NormalizedFace
    track_ordinal: int
    track_id: str


@dataclass(frozen=True, slots=True)
class TrackInterval:
    scene_ordinal: int
    track_id: str
    start_us: int
    end_us: int
    confidence: float
    timestamps: tuple[int, ...]


def associate_scene(
    detections: list[TimedFace],
    *,
    scene_ordinal: int,
    iou_threshold: float = TRACKING_IOU_THRESHOLD,
    center_distance_threshold: float = TRACKING_CENTER_DISTANCE,
    max_gap_us: int = TRACKING_MAX_GAP_US,
) -> tuple[list[TrackedDetection], list[TrackInterval]]:
    """Greedy one-to-one matching. Unmatched boxes start a new scene-local track."""
    ordered = sorted(detections, key=lambda item: (item.timestamp_us, item.detection_ordinal))
    tracks: list[_Track] = []
    for timestamp in sorted({item.timestamp_us for item in ordered}):
        group = [item for item in ordered if item.timestamp_us == timestamp]
        group.sort(
            key=lambda item: (
                -item.face.confidence,
                item.face.x,
                item.face.y,
                item.face.width,
                item.face.height,
            )
        )
        _assign_group(
            tracks,
            group,
            iou_threshold=iou_threshold,
            center_distance_threshold=center_distance_threshold,
            max_gap_us=max_gap_us,
        )
    tracked: list[TrackedDetection] = []
    intervals: list[TrackInterval] = []
    for track in tracks:
        track_id = f"scene-{scene_ordinal:04d}-face-track-{track.ordinal:04d}"
        times = tuple(sorted({item.timestamp_us for item in track.faces}))
        intervals.append(
            TrackInterval(
                scene_ordinal=scene_ordinal,
                track_id=track_id,
                start_us=times[0],
                end_us=times[-1],
                confidence=sum(item.face.confidence for item in track.faces) / len(track.faces),
                timestamps=times,
            )
        )
        for item in track.faces:
            tracked.append(
                TrackedDetection(
                    scene_ordinal=scene_ordinal,
                    timestamp_us=item.timestamp_us,
                    detection_ordinal=item.detection_ordinal,
                    face=item.face,
                    track_ordinal=track.ordinal,
                    track_id=track_id,
                )
            )
    return tracked, intervals


def _assign_group(
    tracks: list[_Track],
    group: list[TimedFace],
    *,
    iou_threshold: float,
    center_distance_threshold: float,
    max_gap_us: int,
) -> None:
    pairs: list[tuple[float, float, int, int]] = []
    for track_index, track in enumerate(tracks):
        gap = group[0].timestamp_us - track.last.timestamp_us
        if gap < 0 or gap > max_gap_us:
            continue
        for detection_index, detection in enumerate(group):
            overlap = _iou(track.last.face, detection.face)
            distance = _center_distance(track.last.face, detection.face)
            if overlap >= iou_threshold and distance <= center_distance_threshold:
                pairs.append((-overlap, distance, track_index, detection_index))
    pairs.sort()
    used_tracks: set[int] = set()
    used_detections: set[int] = set()
    for _overlap, _distance, track_index, detection_index in pairs:
        if track_index in used_tracks or detection_index in used_detections:
            continue
        tracks[track_index].faces.append(group[detection_index])
        used_tracks.add(track_index)
        used_detections.add(detection_index)
    for detection_index, detection in enumerate(group):
        if detection_index in used_detections:
            continue
        tracks.append(_Track(ordinal=len(tracks), faces=[detection]))


def _iou(left: NormalizedFace, right: NormalizedFace) -> float:
    left_x2 = left.x + left.width
    left_y2 = left.y + left.height
    right_x2 = right.x + right.width
    right_y2 = right.y + right.height
    inter_w = max(0.0, min(left_x2, right_x2) - max(left.x, right.x))
    inter_h = max(0.0, min(left_y2, right_y2) - max(left.y, right.y))
    intersection = inter_w * inter_h
    union = left.area_ratio + right.area_ratio - intersection
    if union <= 0:
        return 0.0
    return intersection / union


def _center_distance(left: NormalizedFace, right: NormalizedFace) -> float:
    return math.hypot(left.center_x - right.center_x, left.center_y - right.center_y)
