"""Deterministic quality and editing-opportunity scores.

Quality asks whether the interval looks like a coherent short-form idea.
Editing opportunity asks how much visible structure a later edit could use.
Neither score is a virality probability, and they are not added together.

Missing measurements stay ``None``. Weighted totals use
``weighted_score``, which renormalizes over the measurements that exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from clipforge.candidates.constants import (
    DENSITY_HIGH_FULL,
    DENSITY_HIGH_ZERO,
    DENSITY_LOW_FULL,
    DENSITY_LOW_ZERO,
    SCENE_CUTS_PER_SECOND_CAP,
)
from clipforge.candidates.overlap import intersection_us, union_us
from clipforge.candidates.tokenize import tokenize
from clipforge.candidates.windows import RawWindow, source_bounds
from clipforge.schemas.candidates import (
    CandidateMiningProfile,
    quantize_unit,
    weighted_score,
)
from clipforge.schemas.media import FaceObservation, Scene, TranscriptSegment, TranscriptWord
from clipforge.schemas.vision import FaceDetectionSample, FrameEvidence

_CLOSING = frozenset(".?!…\u3002\uff1f\uff01:")
_EMPHASIS = "?!\uff1f\uff01"


@dataclass(frozen=True, slots=True)
class VisualHit:
    """Round 4 evidence that actually overlaps one candidate interval."""

    scene_ids: tuple[str, ...]
    frame_ids: tuple[str, ...]
    face_observation_ids: tuple[str, ...]
    differences: tuple[float, ...]
    face_samples: tuple[tuple[float, float, float], ...]
    track_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MeasuredWindow:
    window: RawWindow
    segments: tuple[TranscriptSegment, ...]
    words: tuple[TranscriptWord, ...]
    visual: VisualHit
    duration_fit: float
    speech_coverage: float
    boundary_completeness: float
    transcript_reliability: float | None
    information_density: float | None
    opening_structure: float
    visual_evidence_coverage: float
    scene_change_signal: float
    visual_difference_signal: float | None
    face_layout_variation: float | None
    numeric_token_signal: float
    punctuation_emphasis_signal: float
    multi_scene_signal: float


def measure_window(
    window: RawWindow,
    segments: list[TranscriptSegment],
    known_words: list[TranscriptWord],
    scenes: list[Scene],
    frames: list[FrameEvidence],
    samples: list[FaceDetectionSample],
    observations: list[FaceObservation],
    profile: CandidateMiningProfile,
    *,
    duration_us: int,
) -> MeasuredWindow:
    """Measure one window from transcript text and overlapping visual evidence."""
    included = [segment for segment in segments if segment.segment_id in set(window.segment_ids)]
    words = tuple(word for segment in included for word in segment.words)
    visual = _visual_hit(window, scenes, frames, samples, observations)
    spoken = _speech_union(included, window.start_us, window.end_us)
    return MeasuredWindow(
        window=window,
        segments=tuple(included),
        words=words,
        visual=visual,
        duration_fit=duration_fit(window.end_us - window.start_us, profile),
        speech_coverage=_speech_coverage(spoken, window.end_us - window.start_us),
        boundary_completeness=_boundary(
            window,
            included,
            known_words,
            profile.boundary_padding_us,
            duration_us,
        ),
        transcript_reliability=_reliability(words, included),
        information_density=_density(window.word_count, spoken),
        opening_structure=_opening(window.text),
        visual_evidence_coverage=_visual_coverage(len(visual.scene_ids), len(visual.frame_ids)),
        scene_change_signal=_scene_change(len(visual.scene_ids), window.end_us - window.start_us),
        visual_difference_signal=_mean_unit(visual.differences),
        face_layout_variation=_face_layout(visual),
        numeric_token_signal=_numeric(window.text),
        punctuation_emphasis_signal=_emphasis(window.text),
        multi_scene_signal=1.0 if len(visual.scene_ids) >= 2 else 0.0,
    )


def hard_duration_reason(duration_us: int, profile: CandidateMiningProfile) -> str | None:
    """Return ``too_short`` or ``too_long`` when the duration is outside the hard limits."""
    if duration_us < profile.hard_min_duration_us:
        return "too_short"
    if duration_us > profile.hard_max_duration_us:
        return "too_long"
    return None


def duration_fit(duration_us: int, profile: CandidateMiningProfile) -> float:
    """Peak inside the preferred range and fall linearly to the hard edges.

    The value is 0 at the hard minimum and the hard maximum, and 1 from the
    preferred minimum through the preferred maximum. Hard-invalid durations are
    filtered before this function is used for a published candidate.
    """
    hard_min = profile.hard_min_duration_us
    preferred_min = profile.preferred_min_duration_us
    preferred_max = profile.preferred_max_duration_us
    hard_max = profile.hard_max_duration_us
    if duration_us <= hard_min or duration_us >= hard_max:
        return 0.0
    if preferred_min <= duration_us <= preferred_max:
        return 1.0
    if duration_us < preferred_min:
        return _line(duration_us, hard_min, preferred_min, 0.0, 1.0)
    return _line(duration_us, preferred_max, hard_max, 1.0, 0.0)


def score_quality(measured: MeasuredWindow, profile: CandidateMiningProfile) -> tuple[float, float]:
    values = {
        "duration_fit": measured.duration_fit,
        "speech_coverage": measured.speech_coverage,
        "boundary_completeness": measured.boundary_completeness,
        "transcript_reliability": measured.transcript_reliability,
        "information_density": measured.information_density,
        "opening_structure": measured.opening_structure,
        "visual_evidence_coverage": measured.visual_evidence_coverage,
    }
    return weighted_score(profile.quality_weights.pairs(values))


def score_edit(measured: MeasuredWindow, profile: CandidateMiningProfile) -> tuple[float, float]:
    values = {
        "scene_change_signal": measured.scene_change_signal,
        "visual_difference_signal": measured.visual_difference_signal,
        "face_layout_variation": measured.face_layout_variation,
        "numeric_token_signal": measured.numeric_token_signal,
        "punctuation_emphasis_signal": measured.punctuation_emphasis_signal,
        "multi_scene_signal": measured.multi_scene_signal,
    }
    return weighted_score(profile.edit_weights.pairs(values))


def _visual_hit(
    window: RawWindow,
    scenes: list[Scene],
    frames: list[FrameEvidence],
    samples: list[FaceDetectionSample],
    observations: list[FaceObservation],
) -> VisualHit:
    start, end = window.start_us, window.end_us
    scene_ids = tuple(
        scene.scene_id
        for scene in scenes
        if intersection_us(start, end, scene.time_range.start_us, scene.time_range.end_us) > 0
    )
    scene_set = set(scene_ids)
    frame_ids: list[str] = []
    differences: list[float] = []
    for frame in frames:
        if frame.scene_id not in scene_set:
            continue
        if start <= frame.actual_timestamp_us < end:
            frame_ids.append(frame.frame_id)
            if frame.metrics.difference_from_previous_sample is not None:
                differences.append(frame.metrics.difference_from_previous_sample)
    face_ids: list[str] = []
    track_ids: list[str] = []
    for observation in observations:
        if intersection_us(start, end, observation.time_range.start_us, observation.time_range.end_us) <= 0:
            continue
        face_ids.append(observation.observation_id)
        if observation.track_id is not None:
            track_ids.append(observation.track_id)
    face_samples: list[tuple[float, float, float]] = []
    for sample in samples:
        if start <= sample.timestamp_us < end:
            face_samples.append((sample.center_x, sample.center_y, sample.area_ratio))
            if sample.track_id is not None:
                track_ids.append(sample.track_id)
    unique_tracks = tuple(dict.fromkeys(track_ids))
    return VisualHit(
        scene_ids=scene_ids,
        frame_ids=tuple(frame_ids),
        face_observation_ids=tuple(face_ids),
        differences=tuple(differences),
        face_samples=tuple(face_samples),
        track_ids=unique_tracks,
    )


def _speech_union(segments: list[TranscriptSegment], start: int, end: int) -> int:
    clipped: list[tuple[int, int]] = []
    for segment in segments:
        low = max(segment.start_us, start)
        high = min(segment.end_us, end)
        if high > low:
            clipped.append((low, high))
    return union_us(clipped)


def _speech_coverage(spoken_us: int, duration_us: int) -> float:
    if duration_us <= 0:
        return 0.0
    covered = min(spoken_us, duration_us)
    return quantize_unit(float(covered) / float(duration_us))


def _boundary(
    window: RawWindow,
    segments: list[TranscriptSegment],
    known_words: list[TranscriptWord],
    padding_us: int,
    duration_us: int,
) -> float:
    if not segments:
        return 0.0
    expected_start, expected_end = source_bounds(
        segments,
        padding_us=padding_us,
        duration_us=duration_us,
        known_words=known_words,
    )
    signals = [
        1.0 if window.start_us == expected_start else 0.0,
        1.0 if window.end_us == expected_end else 0.0,
    ]
    if known_words:
        signals.append(0.0 if _inside_word(window.start_us, known_words) else 1.0)
        signals.append(0.0 if _inside_word(window.end_us, known_words) else 1.0)
    stripped = window.text.rstrip()
    signals.append(1.0 if stripped and stripped[-1] in _CLOSING else 0.0)
    return quantize_unit(sum(signals) / len(signals))


def _inside_word(instant: int, words: list[TranscriptWord]) -> bool:
    return any(word.start_us < instant < word.end_us for word in words)


def _reliability(
    words: tuple[TranscriptWord, ...],
    segments: list[TranscriptSegment],
) -> float | None:
    confidences = [word.confidence for word in words if word.confidence is not None]
    if confidences:
        return quantize_unit(sum(confidences) / len(confidences))
    diagnostics = [segment.diagnostics for segment in segments if segment.diagnostics is not None]
    if not diagnostics:
        return None
    speech = sum(1.0 - item.no_speech_prob for item in diagnostics) / len(diagnostics)
    logprob = sum(_logprob_unit(item.avg_logprob) for item in diagnostics) / len(diagnostics)
    compression = sum(_compression_unit(item.compression_ratio) for item in diagnostics) / len(diagnostics)
    return quantize_unit((speech + logprob + compression) / 3.0)


def _logprob_unit(value: float) -> float:
    """Map a Whisper avg_logprob onto 0..1. At or above 0 is 1. At or below -1 is 0."""
    if value >= 0:
        return 1.0
    if value <= -1:
        return 0.0
    return value + 1.0


def _compression_unit(value: float) -> float:
    """1 at a compression ratio of 2 or below, 0 at 4 or above."""
    if value <= 2.0:
        return 1.0
    if value >= 4.0:
        return 0.0
    return (4.0 - value) / 2.0


def _density(word_count: int, spoken_us: int) -> float | None:
    """Words per spoken second. This is a density heuristic, not information value."""
    if spoken_us <= 0:
        return None
    rate = word_count / (spoken_us / 1_000_000)
    if rate <= DENSITY_LOW_ZERO or rate >= DENSITY_HIGH_ZERO:
        return 0.0
    if rate < DENSITY_LOW_FULL:
        return quantize_unit((rate - DENSITY_LOW_ZERO) / (DENSITY_LOW_FULL - DENSITY_LOW_ZERO))
    if rate <= DENSITY_HIGH_FULL:
        return 1.0
    return quantize_unit((DENSITY_HIGH_ZERO - rate) / (DENSITY_HIGH_ZERO - DENSITY_HIGH_FULL))


def _opening(text: str) -> float:
    """Small structural bonus from the observed opening text. No topic keywords."""
    head = text[:80]
    score = 0.0
    if "?" in head or "\uff1f" in head:
        score += 0.4
    if any(any(character.isdigit() for character in token) for token in tokenize(head)[:8]):
        score += 0.3
    clause = text
    for index, character in enumerate(text):
        if character in _CLOSING:
            clause = text[:index]
            break
    clause_tokens = tokenize(clause)
    if 0 < len(clause_tokens) <= 12:
        score += 0.3
    return quantize_unit(min(1.0, score))


def _visual_coverage(scene_count: int, frame_count: int) -> float:
    """Whether Round 4 evidence overlaps the interval. Faces add nothing here."""
    scene_term = 1.0 if scene_count >= 1 else 0.0
    frame_term = 1.0 if frame_count >= 1 else 0.0
    return quantize_unit((0.6 * scene_term) + (0.4 * frame_term))


def _scene_change(scene_count: int, duration_us: int) -> float:
    if duration_us <= 0 or scene_count <= 1:
        return 0.0
    cuts = scene_count - 1
    per_second = cuts / (duration_us / 1_000_000)
    if per_second >= SCENE_CUTS_PER_SECOND_CAP:
        return 1.0
    return quantize_unit(per_second / SCENE_CUTS_PER_SECOND_CAP)


def _mean_unit(values: tuple[float, ...]) -> float | None:
    if not values:
        return None
    return quantize_unit(sum(values) / len(values))


def _face_layout(visual: VisualHit) -> float | None:
    """Geometry variation only. A face track is not a speaker change."""
    if not visual.face_samples and not visual.face_observation_ids:
        return None
    track_term = min(1.0, max(0, len(visual.track_ids) - 1) / 2)
    if len(visual.face_samples) < 2:
        return quantize_unit(track_term)
    centers_x = [sample[0] for sample in visual.face_samples]
    centers_y = [sample[1] for sample in visual.face_samples]
    areas = [sample[2] for sample in visual.face_samples]
    span = (
        (max(centers_x) - min(centers_x)) + (max(centers_y) - min(centers_y)) + (max(areas) - min(areas))
    ) / 3
    return quantize_unit(min(1.0, (span + track_term) / 2))


def _numeric(text: str) -> float:
    count = sum(1 for token in tokenize(text) if any(character.isdigit() for character in token))
    return quantize_unit(min(1.0, count / 2))


def _emphasis(text: str) -> float:
    count = sum(text.count(character) for character in _EMPHASIS)
    return quantize_unit(min(1.0, count / 2))


def _line(value: int, left: int, right: int, left_value: float, right_value: float) -> float:
    span = right - left
    if span <= 0:
        return quantize_unit(left_value)
    position = (value - left) / span
    return quantize_unit(left_value + (right_value - left_value) * position)
