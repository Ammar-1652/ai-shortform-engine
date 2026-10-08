"""Forced word alignment for one approved candidate.

The production adapter calls WhisperX on the candidate span only. Tests inject
``FakeForcedAlignment``. Provisional transcript times are not copied into a
Hero alignment.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from clipforge.errors import MediaError
from clipforge.hero.constants import FAKE_MODEL_NAME, FAKE_WHISPERX_VERSION
from clipforge.hero.selection import review_digest
from clipforge.preview.timing import frame_at_or_after
from clipforge.schemas.candidates import CandidateEvidenceBundle
from clipforge.schemas.editorial import CandidateClip
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument
from clipforge.schemas.media import Transcript, TranscriptWord
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import TimelineSegment
from clipforge.timeline.framerate import FrameRate

_MIN_FORCED_WORD_US = 5_000


class ForcedAlignmentBackend(Protocol):
    model_name: str
    whisperx_version: str
    device: str
    needs_staged_audio: bool

    def align_words(
        self,
        words: list[TranscriptWord],
        *,
        source_start_us: int,
        source_end_us: int,
    ) -> list[tuple[int, int]]:
        """Return source ``(start_us, end_us)`` for each word, in the same order."""


@dataclass
class FakeForcedAlignment:
    """Deterministic stand-in. It does not read provisional word timestamps."""

    model_name: str = FAKE_MODEL_NAME
    whisperx_version: str = FAKE_WHISPERX_VERSION
    device: str = "cpu"
    needs_staged_audio: bool = False

    def align_words(
        self,
        words: list[TranscriptWord],
        *,
        source_start_us: int,
        source_end_us: int,
    ) -> list[tuple[int, int]]:
        count = len(words)
        span = source_end_us - source_start_us
        if count < 1 or span < count:
            raise MediaError("the candidate is too short to place one forced interval per word")
        bounds: list[tuple[int, int]] = []
        for index in range(count):
            start = source_start_us + (span * index) // count
            end = source_start_us + (span * (index + 1)) // count
            if end <= start:
                raise MediaError("forced alignment produced a zero-length word")
            bounds.append((start, end))
        return bounds


class WhisperXAlignment:
    """Selected-clip WhisperX alignment. This does not transcribe the full source."""

    model_name: str = "WAV2VEC2_ASR_BASE_960H"
    device: str = "cpu"
    needs_staged_audio: bool = True

    def __init__(
        self,
        *,
        allow_model_download: bool = False,
        audio_path: str | None = None,
        language_code: str = "en",
        model_name: str | None = None,
        locale: str = "en-US",
        model_revision: str = "3.4.5",
        checkpoint_sha256: str = "",
        model_license: str = "Apache-2.0",
        audio_is_source_clock: bool = False,
    ) -> None:
        self.allow_model_download = allow_model_download
        self.audio_path = audio_path
        self.language_code = language_code
        self.locale = locale
        self.model_revision = model_revision
        self.checkpoint_sha256 = checkpoint_sha256
        self.model_license = model_license
        self.audio_is_source_clock = audio_is_source_clock
        if model_name:
            self.model_name = model_name
        self.whisperx_version = _whisperx_version()

    def align_words(
        self,
        words: list[TranscriptWord],
        *,
        source_start_us: int,
        source_end_us: int,
    ) -> list[tuple[int, int]]:
        if not self.audio_path:
            raise MediaError(
                "WhisperX clip alignment needs the staged candidate audio path. "
                "Provisional timings were not used."
            )
        if self.audio_is_source_clock:
            return align_span_with_whisperx(
                self.audio_path,
                words,
                source_start_us=source_start_us,
                source_end_us=source_end_us,
                allow_model_download=self.allow_model_download,
                language_code=self.language_code,
                model_name=self.model_name,
            )
        return align_trimmed_with_whisperx(
            self.audio_path,
            words,
            source_start_us=source_start_us,
            source_end_us=source_end_us,
            allow_model_download=self.allow_model_download,
            language_code=self.language_code,
            model_name=self.model_name,
        )


def production_alignment_backend(
    language: str | None,
    *,
    allow_model_download: bool = False,
) -> WhisperXAlignment:
    """Pick the live aligner for one language. A missing model is not a pass.

    Unit tests inject ``FakeForcedAlignment`` themselves. A production campaign
    does not. A non-English request never falls back to the English checkpoint.
    """
    from clipforge.language.providers import license_is_allowed, provider_for

    requested = "en-US" if language in {None, ""} else language
    record = provider_for(requested)
    if record.live_status in {"unsupported_language", "alignment_not_claimed"}:
        raise MediaError(record.live_status)
    if not license_is_allowed(record.model_license, record.model_id):
        raise MediaError("model_license_unknown")
    runnable = record.live_status in {"verified_live", "available_not_smoked"}
    download_missing = allow_model_download and record.live_status == "model_missing"
    if not runnable and not download_missing:
        raise MediaError(record.live_status)
    return WhisperXAlignment(
        allow_model_download=allow_model_download,
        language_code=record.normalized_language,
        model_name=record.model_id,
        locale=record.locale,
        model_revision=record.model_revision,
        checkpoint_sha256=record.checkpoint_sha256,
        model_license=record.model_license,
    )


def alignment_config_sha256(*, model_name: str, whisperx_version: str, device: str) -> str:
    payload = {"device": device, "model_name": model_name, "whisperx_version": whisperx_version}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def alignment_binding_sha256(**parts: str) -> str:
    """Identity of one alignment. A changed component is a cache miss."""
    from clipforge.language.providers import alignment_cache_key

    return alignment_cache_key(**parts)


def build_alignment(
    *,
    alignment_id: str,
    transcript: Transcript,
    transcript_sha256: str,
    candidate: CandidateClip,
    bundle: CandidateEvidenceBundle,
    review: ReviewDecision,
    rough_artifact_id: str,
    asr_audio_sha256: str,
    backend: ForcedAlignmentBackend,
    created_by: str,
    tool_version: str,
    source_sha256: str = "",
) -> ForcedAlignmentDocument:
    """Align the candidate's own words. Missing word ids are a hard failure."""
    if not bundle.transcript_word_ids:
        raise MediaError(
            f"candidate {candidate.candidate_id} has no transcript word ids. "
            "Hero alignment does not invent words from segment text."
        )
    if not candidate.time_map.segments:
        raise MediaError(f"candidate {candidate.candidate_id} has no TimeMap segments")
    ordered = _evidence_words(transcript, bundle)
    _validate_cut_boundaries(ordered, candidate.time_map.segments)
    _reject_transcript_language(transcript, backend)
    time_map = candidate.time_map.to_time_map()
    frame_count = time_map.output_frame_count(FrameRate(30, 1))
    bounds = _align_groups(ordered, candidate.time_map.segments, backend)
    if len(bounds) != len(ordered):
        raise MediaError("forced alignment did not return one interval per evidence word")
    aligned: list[AlignedWord] = []
    previous_output_end = -1
    duration = time_map.total_output_duration()
    for word, (start, end, segment_index) in zip(ordered, bounds, strict=True):
        segment = candidate.time_map.segments[segment_index]
        if start < segment.source_start_us or start >= segment.source_end_us or end > segment.source_end_us:
            raise MediaError(f"aligned word {word.word_id} is outside its TimeMap segment")
        if end <= start:
            raise MediaError(f"aligned word {word.word_id} has no positive duration")
        if end - start < _MIN_FORCED_WORD_US:
            raise MediaError(
                f"aligned word {word.word_id} is only {end - start} us; "
                "the alignment would be unreadable and can lose its leading phoneme"
            )
        output_start = time_map.source_to_output(start)
        output_end = time_map.source_to_output(end)
        if output_end > duration or output_start < 0 or output_start >= duration:
            raise MediaError(f"aligned word {word.word_id} leaves the output TimeMap")
        if output_start < previous_output_end:
            raise MediaError(f"aligned word {word.word_id} overlaps the previous word on the output clock")
        previous_output_end = output_end
        start_frame = frame_at_or_after(output_start, frame_count)
        end_frame = frame_at_or_after(output_end, frame_count)
        if start_frame >= end_frame:
            # A sub-frame word still occupies the frame that contains its start.
            if start_frame < frame_count:
                end_frame = start_frame + 1
            elif start_frame > 0:
                start_frame -= 1
            else:
                raise MediaError(
                    f"aligned word {word.word_id} has no Hero frame. Provisional timing was not substituted."
                )
        aligned.append(
            AlignedWord(
                word_id=word.word_id,
                candidate_id=candidate.candidate_id,
                text=word.text,
                source_start_us=start,
                source_end_us=end,
                output_start_us=output_start,
                output_end_us=output_end,
                output_start_frame=start_frame,
                output_end_frame_exclusive=end_frame,
                segment_index=segment_index,
            )
        )
    from datetime import UTC, datetime

    stamp = datetime.now(UTC)
    return ForcedAlignmentDocument(
        alignment_id=alignment_id,
        project_id=candidate.project_id,
        source_asset_id=candidate.source_asset_id,
        candidate_id=candidate.candidate_id,
        transcript_id=transcript.transcript_id,
        transcript_sha256=transcript_sha256,
        asr_audio_sha256=asr_audio_sha256,
        time_map_sha256=_time_map_sha(candidate),
        review_id=review.review_id,
        review_digest=review_digest(review),
        rough_preview_artifact_id=rough_artifact_id,
        model_name=backend.model_name,
        whisperx_version=backend.whisperx_version,
        device="cuda" if backend.device == "cuda" else "cpu",
        config_sha256=alignment_config_sha256(
            model_name=backend.model_name,
            whisperx_version=backend.whisperx_version,
            device=backend.device,
        ),
        words=aligned,
        locale=_stored_locale(backend),
        normalized_language=_stored_language(backend, transcript),
        model_revision=_observed_revision(backend),
        checkpoint_sha256=_observed_checkpoint(backend),
        model_license=str(getattr(backend, "model_license", "")),
        alignment_status=_stored_alignment_status(backend),
        alignment_scope="selected_clip",
        alignment_recipe="hero-align-v1",
        binding_sha256=_binding_for(
            backend,
            candidate,
            transcript_sha256,
            asr_audio_sha256,
            transcript_language=transcript.detected_language or "",
            source_sha256=source_sha256,
        ),
        manifest_sha256=_observed_manifest(backend),
        unavailable_reason="none",
        provenance=ArtifactProvenance(
            created_at=stamp,
            created_by=created_by,
            tool="clipforge-hero",
            tool_version=tool_version,
            source_asset_ids=[candidate.source_asset_id],
            inputs_sha256=alignment_config_sha256(
                model_name=backend.model_name,
                whisperx_version=backend.whisperx_version,
                device=backend.device,
            ),
        ),
    )


def _align_groups(
    words: list[TranscriptWord],
    segments: list[TimelineSegment],
    backend: ForcedAlignmentBackend,
) -> list[tuple[int, int, int]]:
    """Align each TimeMap segment on its own source interval. One segment stays one call."""
    if len(segments) == 1:
        segment = segments[0]
        bounds = backend.align_words(
            words,
            source_start_us=segment.source_start_us,
            source_end_us=segment.source_end_us,
        )
        return [(start, end, 0) for start, end in bounds]
    grouped = _partition_words(words, segments)
    grouped_bounds: list[tuple[int, int, int]] = []
    for segment, group in grouped:
        index = segments.index(segment)
        for start, end in backend.align_words(
            group,
            source_start_us=segment.source_start_us,
            source_end_us=segment.source_end_us,
        ):
            grouped_bounds.append((start, end, index))
    return grouped_bounds


def _partition_words(
    words: list[TranscriptWord],
    segments: list[TimelineSegment],
) -> list[tuple[TimelineSegment, list[TranscriptWord]]]:
    """Keep evidence order. Do not sort by source time."""
    indexes: list[int] = []
    for word in words:
        found = None
        for index, segment in enumerate(segments):
            if (
                segment.source_start_us <= word.start_us < segment.source_end_us
                and word.end_us <= segment.source_end_us
            ):
                found = index
                break
        if found is None:
            raise MediaError(f"transcript word {word.word_id} is outside the candidate TimeMap")
        indexes.append(found)
    if indexes != sorted(indexes):
        raise MediaError("evidence words are not in TimeMap output order")
    groups: list[tuple[TimelineSegment, list[TranscriptWord]]] = []
    cursor = 0
    while cursor < len(words):
        index = indexes[cursor]
        group = [words[cursor]]
        cursor += 1
        while cursor < len(words) and indexes[cursor] == index:
            group.append(words[cursor])
            cursor += 1
        groups.append((segments[index], group))
    return groups


def _validate_cut_boundaries(words: list[TranscriptWord], segments: list[TimelineSegment]) -> None:
    """Reject editorial cuts through a spoken word.

    A cut inside ``How`` can leave the encoded picture beginning on the /ow/
    while the audio still contains the word onset.  Such a map is not repaired
    by a caption change; it must be reselected at a phonetic boundary.
    """
    for segment in segments:
        for boundary, label in (
            (segment.source_start_us, "start"),
            (segment.source_end_us, "end"),
        ):
            if any(word.start_us < boundary < word.end_us for word in words):
                raise MediaError(
                    f"TimeMap {label} {boundary} us falls inside a transcript word; "
                    "reselect the cut at a complete-word boundary"
                )


def _owner_segment(segments: list[TimelineSegment], start: int, end: int) -> TimelineSegment | None:
    for segment in segments:
        if start >= segment.source_start_us and end <= segment.source_end_us:
            return segment
    return None


def _stored_locale(backend: ForcedAlignmentBackend) -> str:
    from clipforge.language.providers import canonical_locale

    raw = str(getattr(backend, "locale", "en-US"))
    return canonical_locale(raw) or "en-US"


def _stored_language(backend: ForcedAlignmentBackend, transcript: Transcript) -> str:
    from clipforge.language.providers import normalized_language

    detected = normalized_language(transcript.detected_language or "")
    if detected:
        return detected
    return str(getattr(backend, "language_code", "en"))


def _reject_transcript_language(transcript: Transcript, backend: ForcedAlignmentBackend) -> None:
    detected = transcript.detected_language
    if not detected:
        return
    from clipforge.language.providers import normalized_language

    requested = str(getattr(backend, "language_code", "en"))
    found = normalized_language(detected)
    if found and found != requested:
        raise MediaError("transcript_language_mismatch")


def _stored_alignment_status(backend: ForcedAlignmentBackend) -> str:
    if backend.model_name == FAKE_MODEL_NAME:
        return "available_not_smoked"
    from clipforge.language.providers import provider_for

    record = provider_for(str(getattr(backend, "locale", "en-US")))
    checkpoint = str(getattr(backend, "checkpoint_sha256", ""))
    if (
        record.live_status == "verified_live"
        and backend.model_name == record.model_id
        and checkpoint == record.checkpoint_sha256
    ):
        return "verified_live"
    if record.live_status == "verified_live":
        return "available_not_smoked"
    return record.live_status


def _binding_for(
    backend: ForcedAlignmentBackend,
    candidate: CandidateClip,
    transcript_sha256: str,
    asr_audio_sha256: str,
    *,
    transcript_language: str = "",
    source_sha256: str = "",
) -> str:
    from clipforge.language.providers import canonical_locale, normalized_language

    provider = "fake" if backend.model_name == FAKE_MODEL_NAME else "whisperx"
    stored_locale = canonical_locale(str(getattr(backend, "locale", "en-US"))) or "en-US"
    detected = normalized_language(transcript_language) if transcript_language else ""
    language = detected or str(getattr(backend, "language_code", "en"))
    return alignment_binding_sha256(
        alignment_recipe="hero-align-v1",
        asr_audio_sha256=asr_audio_sha256,
        candidate_id=candidate.candidate_id,
        checkpoint_sha256=_observed_checkpoint(backend),
        locale=stored_locale,
        manifest_sha256=_observed_manifest(backend),
        model_id=backend.model_name,
        model_revision=_observed_revision(backend),
        normalized_language=language,
        provider_name=provider,
        provider_version=backend.whisperx_version,
        source_asset_id=candidate.source_asset_id,
        source_sha256=source_sha256,
        time_map_sha256=_time_map_sha(candidate),
        transcript_language=language,
        transcript_sha256=transcript_sha256,
    )


def expected_binding(
    alignment: ForcedAlignmentDocument,
    *,
    candidate: CandidateClip,
    transcript_sha256: str,
    asr_audio_sha256: str,
    transcript_language: str,
    source_sha256: str,
    aligner: ForcedAlignmentBackend | None,
) -> str:
    """Recompute the cache key. A missing production identity is incomplete."""
    from clipforge.language.providers import canonical_locale, normalized_language, provider_for

    if aligner is not None:
        return _binding_for(
            aligner,
            candidate,
            transcript_sha256,
            asr_audio_sha256,
            transcript_language=transcript_language,
            source_sha256=source_sha256,
        )
    locale = canonical_locale(alignment.locale)
    if not alignment.binding_sha256 or not locale:
        raise MediaError("stored alignment identity is incomplete")
    detected = normalized_language(transcript_language) if transcript_language else ""
    language = detected or normalized_language(locale)
    if alignment.model_name == FAKE_MODEL_NAME:
        return alignment_binding_sha256(
            alignment_recipe=alignment.alignment_recipe or "hero-align-v1",
            asr_audio_sha256=asr_audio_sha256,
            candidate_id=candidate.candidate_id,
            checkpoint_sha256=alignment.checkpoint_sha256,
            locale=locale,
            manifest_sha256=alignment.manifest_sha256,
            model_id=alignment.model_name,
            model_revision=alignment.model_revision,
            normalized_language=language,
            provider_name="fake",
            provider_version=alignment.whisperx_version,
            source_asset_id=candidate.source_asset_id,
            source_sha256=source_sha256,
            time_map_sha256=_time_map_sha(candidate),
            transcript_language=language,
            transcript_sha256=transcript_sha256,
        )
    if (
        not alignment.model_revision
        or not alignment.checkpoint_sha256
        or not alignment.whisperx_version
        or not alignment.manifest_sha256
    ):
        raise MediaError("stored alignment identity is incomplete")
    record = provider_for(locale)
    if record.provider_name != "whisperx":
        raise MediaError("alignment_not_claimed")
    if alignment.model_name != record.model_id or alignment.model_revision != record.model_revision:
        raise MediaError("stale_alignment")
    if alignment.checkpoint_sha256 != record.checkpoint_sha256:
        raise MediaError("stale_alignment")
    if alignment.whisperx_version != record.provider_version:
        raise MediaError("stale_alignment")
    if alignment.alignment_status != record.live_status:
        raise MediaError("stale_alignment")
    manifest = _manifest_for_model(record.model_id, record.normalized_language, record.model_revision)
    if alignment.manifest_sha256 != manifest:
        raise MediaError("stale_alignment")
    return alignment_binding_sha256(
        alignment_recipe=alignment.alignment_recipe or "hero-align-v1",
        asr_audio_sha256=asr_audio_sha256,
        candidate_id=candidate.candidate_id,
        checkpoint_sha256=record.checkpoint_sha256,
        locale=locale,
        manifest_sha256=manifest,
        model_id=record.model_id,
        model_revision=record.model_revision,
        normalized_language=language,
        provider_name=record.provider_name,
        provider_version=record.provider_version,
        source_asset_id=candidate.source_asset_id,
        source_sha256=source_sha256,
        time_map_sha256=_time_map_sha(candidate),
        transcript_language=language,
        transcript_sha256=transcript_sha256,
    )


def _observed_revision(backend: ForcedAlignmentBackend) -> str:
    return str(getattr(backend, "model_revision", ""))


def _measured_pair(backend: ForcedAlignmentBackend) -> tuple[str, str]:
    """Observed checkpoint and manifest. Catalog pins are compared, not trusted."""
    if backend.model_name == FAKE_MODEL_NAME:
        return (
            str(getattr(backend, "checkpoint_sha256", "")),
            str(getattr(backend, "manifest_sha256", "")),
        )
    cached = getattr(backend, "_measured_pair", None)
    if isinstance(cached, tuple) and len(cached) == 2:
        return cached
    from clipforge.language.providers import provider_for

    locale = str(getattr(backend, "locale", "en-US"))
    record = provider_for(locale)
    if record.model_id != backend.model_name:
        raise MediaError("stale_alignment")
    checkpoint, manifest = _measure_checkpoint_and_manifest(
        record.model_id,
        record.normalized_language,
        record.model_revision,
        record.checkpoint_sha256,
    )
    pair = (checkpoint, manifest)
    backend._measured_pair = pair  # type: ignore[attr-defined]
    return pair


def _observed_checkpoint(backend: ForcedAlignmentBackend) -> str:
    return _measured_pair(backend)[0]


def _observed_manifest(backend: ForcedAlignmentBackend) -> str:
    return _measured_pair(backend)[1]


def _measure_checkpoint_and_manifest(
    model_id: str,
    language_code: str,
    revision: str,
    expected_checkpoint: str,
) -> tuple[str, str]:
    """Return the on-disk checkpoint and manifest. A mismatch is stale."""
    from clipforge.language.model_manifest import (
        english_checkpoint_file,
        huggingface_snapshot,
        measure_english_checkpoint,
        measure_tree,
        sha256_file,
    )

    if model_id == "WAV2VEC2_ASR_BASE_960H" or language_code == "en":
        path = english_checkpoint_file()
        if path is None:
            raise MediaError("model_missing")
        digest = sha256_file(path)
        if expected_checkpoint and digest != expected_checkpoint:
            raise MediaError("stale_alignment")
        return digest, measure_english_checkpoint(path).manifest_sha256
    snapshot = huggingface_snapshot(model_id, revision)
    if snapshot is None:
        raise MediaError("model_missing")
    tree = measure_tree(snapshot, model_id=model_id, revision=revision)
    if tree is None:
        raise MediaError("model_missing")
    if expected_checkpoint and tree.checkpoint_sha256 != expected_checkpoint:
        raise MediaError("stale_alignment")
    return tree.checkpoint_sha256, tree.manifest_sha256


def _manifest_for_model(model_id: str, language_code: str, revision: str) -> str:
    """Hash the local snapshot. A missing weight file is model_missing."""
    from clipforge.language.providers import provider_for_model

    row = provider_for_model(model_id)
    expected = "" if row is None else row.checkpoint_sha256
    _checkpoint, manifest = _measure_checkpoint_and_manifest(model_id, language_code, revision, expected)
    return manifest


def _evidence_words(transcript: Transcript, bundle: CandidateEvidenceBundle) -> list[TranscriptWord]:
    wanted = list(bundle.transcript_word_ids)
    found: dict[str, TranscriptWord] = {}
    for segment in transcript.segments:
        for word in segment.words:
            if word.word_id in wanted:
                found[word.word_id] = word
    missing = [word_id for word_id in wanted if word_id not in found]
    if missing:
        raise MediaError("Hero alignment references unknown transcript words: " + ", ".join(missing))
    return [found[word_id] for word_id in wanted]


def _time_map_sha(candidate: CandidateClip) -> str:
    from clipforge.schemas.time import digest_time_map

    return digest_time_map(candidate.time_map)


def align_trimmed_with_whisperx(
    audio_path: str,
    words: list[TranscriptWord],
    *,
    source_start_us: int,
    source_end_us: int,
    allow_model_download: bool,
    language_code: str = "en",
    model_name: str = "WAV2VEC2_ASR_BASE_960H",
) -> list[tuple[int, int]]:
    """Align one already-trimmed ASR span. Returned times are on the source clock."""
    span = source_end_us - source_start_us
    relative = align_span_with_whisperx(
        audio_path,
        words,
        source_start_us=0,
        source_end_us=span,
        allow_model_download=allow_model_download,
        language_code=language_code,
        model_name=model_name,
    )
    return [(source_start_us + start, source_start_us + end) for start, end in relative]


def align_span_with_whisperx(
    audio_path: str,
    words: list[TranscriptWord],
    *,
    source_start_us: int,
    source_end_us: int,
    allow_model_download: bool,
    language_code: str = "en",
    model_name: str = "WAV2VEC2_ASR_BASE_960H",
) -> list[tuple[int, int]]:
    """Run WhisperX on one candidate span. The full source is not transcribed."""
    import os

    _reject_alignment_model(language_code, model_name)
    model_path, _checkpoint_path, _revision = _local_identity(language_code, model_name)
    if not allow_model_download:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
        english = model_name == "WAV2VEC2_ASR_BASE_960H"
        if english and not _checkpoint_path:
            raise MediaError("model_missing")
        if not english and (not model_path or not _revision):
            raise MediaError("model_missing")
    try:
        import whisperx  # type: ignore[import-not-found]
    except ImportError:
        return _align_with_side_python(
            audio_path,
            words,
            source_start_us=source_start_us,
            source_end_us=source_end_us,
            allow_model_download=allow_model_download,
            language_code=language_code,
            model_name=model_name,
        )
    if not allow_model_download and language_code == "en":
        _require_cached_punkt()
    audio = whisperx.load_audio(audio_path)
    start_sample = (source_start_us * 16) // 1000
    end_sample = (source_end_us * 16) // 1000
    clip = audio[start_sample:end_sample]
    if getattr(clip, "size", 0) == 0:
        raise MediaError(
            "WhisperX received no audio samples for this candidate. Provisional timings were not used."
        )
    text = "".join(word.text for word in words).strip()
    duration_s = (source_end_us - source_start_us) / 1_000_000
    segments = [{"text": text, "start": 0.0, "end": duration_s}]
    try:
        with _block_model_downloads(allow_model_download):
            model, metadata = _load_align_model(
                whisperx,
                allow_model_download=allow_model_download,
                language_code=language_code,
                model_name=model_path or model_name,
            )
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(
            "WhisperX could not load the alignment model. "
            "Run hero doctor and install the model locally, or use --allow-model-download explicitly."
        ) from exc
    aligned = whisperx.align(segments, model, metadata, clip, "cpu", return_char_alignments=False)
    returned = []
    for segment in aligned.get("segments", []):
        for word in segment.get("words", []):
            token = word.get("word")
            start = word.get("start")
            end = word.get("end")
            token_ok = isinstance(token, str)
            times_ok = isinstance(start, (int, float)) and isinstance(end, (int, float))
            if not token_ok or not times_ok:
                raise MediaError(
                    "WhisperX returned a word without text or times. Provisional timings were not used."
                )
            start_us = round(float(start) * 1_000_000)
            end_us = round(float(end) * 1_000_000)
            returned.append((token, start_us, end_us))
    return _collapse_alignment_tokens(words, returned, source_offset=source_start_us)


def _reject_alignment_model(language_code: str, model_name: str) -> None:
    """Refuse an English checkpoint for another language and refuse non-commercial weights."""
    from clipforge.language.providers import license_is_allowed

    if language_code != "en" and model_name == "WAV2VEC2_ASR_BASE_960H":
        raise MediaError("alignment_not_claimed")
    if not license_is_allowed("Apache-2.0", model_name):
        raise MediaError("model_license_unknown")


def _load_align_model(
    whisperx: Any,
    *,
    allow_model_download: bool,
    language_code: str,
    model_name: str,
) -> tuple[object, object]:
    """Load the requested aligner. Cache-only builds must not fetch weights."""
    loader: Callable[..., Any] = whisperx.load_align_model
    kwargs: dict[str, object] = {
        "language_code": language_code,
        "device": "cpu",
        "model_name": model_name,
    }
    if _declares_model_cache_only(loader):
        kwargs["model_cache_only"] = not allow_model_download
    loaded = loader(**kwargs)
    if not isinstance(loaded, tuple) or len(loaded) != 2:
        raise MediaError("WhisperX load_align_model did not return a model and metadata")
    return loaded[0], loaded[1]


def _declares_model_cache_only(loader: Callable[..., Any]) -> bool:
    """True only when the function itself names the cache-only argument.

    WhisperX's public wrapper accepts ``**kwargs`` and forwards them. That is
    not evidence the installed aligner implements ``model_cache_only``.
    """
    try:
        parameters = inspect.signature(loader).parameters
    except (TypeError, ValueError):
        return False
    if any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
        return False
    return "model_cache_only" in parameters


def _require_cached_punkt() -> None:
    """Fail before WhisperX can invoke nltk.download in offline mode."""
    try:
        import nltk  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MediaError(
            "WhisperX requires NLTK punkt data for offline alignment. "
            "Install the WhisperX runtime and its local punkt data first."
        ) from exc
    for resource in ("tokenizers/punkt_tab/english/", "tokenizers/punkt/english.pickle"):
        try:
            nltk.data.find(resource)
            return
        except LookupError:
            continue
    raise MediaError(
        "WhisperX English punkt data is not cached. The normal Hero run will not download it; "
        "install the data locally or run with --allow-model-download."
    )


@contextmanager
def _block_model_downloads(allow_model_download: bool) -> Iterator[None]:
    """Block torchaudio/torch.hub downloads that HF offline flags cannot stop."""
    if allow_model_download:
        yield
        return
    try:
        import torch.hub  # type: ignore[import-not-found]
    except ImportError:
        yield
        return

    original = torch.hub.download_url_to_file

    def blocked(*_args: object, **_kwargs: object) -> None:
        raise MediaError(
            "the WhisperX alignment model is not cached. The normal Hero run will not download it; "
            "install the model locally or run with --allow-model-download."
        )

    torch.hub.download_url_to_file = blocked
    try:
        yield
    finally:
        torch.hub.download_url_to_file = original


def _align_python() -> Path | None:
    configured = os.environ.get("CLIPFORGE_ALIGN_PYTHON", "").strip()
    default = Path.home() / ".local" / "clipforge-hero-align" / "bin" / "python"
    candidate = Path(configured) if configured else default
    # A venv interpreter is commonly a symlink. Keep that path so its site-packages load.
    if candidate.is_file():
        return candidate
    return None


def _align_with_side_python(
    audio_path: str,
    words: list[TranscriptWord],
    *,
    source_start_us: int,
    source_end_us: int,
    allow_model_download: bool,
    language_code: str,
    model_name: str,
) -> list[tuple[int, int]]:
    """Run the optional alignment interpreter. The result is still production WhisperX."""
    import subprocess

    model_path, checkpoint_path, revision = _local_identity(language_code, model_name)
    if not allow_model_download:
        english = model_name == "WAV2VEC2_ASR_BASE_960H"
        if english and not checkpoint_path:
            raise MediaError("model_missing")
        if not english and (not model_path or not revision):
            raise MediaError("model_missing")
    python = _align_python()
    if python is None:
        raise MediaError(
            "WhisperX is not installed. Hero alignment does not fall back to provisional timings. "
            "Install WhisperX locally before hero align. Clipforge does not download it automatically."
        )
    worker = Path(__file__).with_name("align_worker.py")
    env = dict(os.environ)
    nltk_data = python.parent.parent / "nltk_data"
    if nltk_data.is_dir():
        env["NLTK_DATA"] = str(nltk_data)
    if not allow_model_download:
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["HF_DATASETS_OFFLINE"] = "1"
    payload = {
        "audio_path": audio_path,
        "source_start_us": source_start_us,
        "source_end_us": source_end_us,
        "allow_model_download": allow_model_download,
        "language_code": language_code,
        "model_name": model_name,
        "model_path": model_path,
        "checkpoint_path": checkpoint_path,
        "revision": revision,
        "words": [{"text": word.text} for word in words],
    }
    completed = subprocess.run(
        [str(python), str(worker)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise MediaError(
            "WhisperX alignment failed. Provisional timings were not used. "
            "The transcript text was not rewritten."
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError("WhisperX returned a malformed result. Provisional timings were not used.") from exc
    returned = document.get("words")
    if not isinstance(returned, list):
        raise MediaError("WhisperX returned no words. Provisional timings were not used.")
    pairs: list[tuple[str, int, int]] = []
    for item in returned:
        if not isinstance(item, dict):
            raise MediaError("WhisperX returned a word without text or times.")
        token = item.get("text")
        start = item.get("start_us")
        end = item.get("end_us")
        if not isinstance(token, str) or isinstance(start, bool) or isinstance(end, bool):
            raise MediaError("WhisperX returned a word without text or times.")
        if not isinstance(start, int) or not isinstance(end, int):
            raise MediaError("WhisperX returned a word without text or times.")
        pairs.append((token, start, end))
    _require_worker_identity(
        language_code=language_code,
        model_name=model_name,
        revision=revision,
        model_path=model_path,
        checkpoint_path=checkpoint_path,
        reported=document if isinstance(document, dict) else {},
    )
    return _collapse_alignment_tokens(words, pairs, source_offset=source_start_us)


def _local_identity(language_code: str, model_name: str) -> tuple[str, str, str]:
    """Local snapshot or English checkpoint. An empty path means the weight is missing."""
    from clipforge.language.model_manifest import english_checkpoint_file, huggingface_snapshot
    from clipforge.language.providers import provider_for_model

    if language_code == "en" and model_name == "WAV2VEC2_ASR_BASE_960H":
        path = english_checkpoint_file()
        return "", "" if path is None else str(path), "3.4.5"
    row = provider_for_model(model_name)
    revision = "" if row is None else row.model_revision
    snapshot = None if row is None else huggingface_snapshot(row.model_id, row.model_revision)
    return "" if snapshot is None else str(snapshot), "", revision


def _require_worker_identity(
    *,
    language_code: str,
    model_name: str,
    revision: str,
    model_path: str,
    checkpoint_path: str,
    reported: dict[str, object],
) -> None:
    """The worker's report must match a fresh local measurement."""
    from clipforge.language.model_manifest import measure_tree, sha256_file
    from clipforge.language.providers import WHISPERX_VERSION

    if reported.get("revision") != revision or reported.get("model") != model_name:
        raise MediaError("stale_alignment")
    if reported.get("language_code") != language_code:
        raise MediaError("stale_alignment")
    if reported.get("whisperx") != WHISPERX_VERSION or reported.get("device") != "cpu":
        raise MediaError("stale_alignment")
    if checkpoint_path:
        measured = sha256_file(Path(checkpoint_path))
        if reported.get("checkpoint_sha256") != measured:
            raise MediaError("stale_alignment")
        tree = measure_tree(
            Path(checkpoint_path).parent,
            model_id=model_name,
            revision=revision,
        )
        if tree is None or reported.get("manifest_sha256") != tree.manifest_sha256:
            raise MediaError("stale_alignment")
    if model_path:
        measured_tree = measure_tree(Path(model_path), model_id=model_name, revision=revision)
        if measured_tree is None or reported.get("manifest_sha256") != measured_tree.manifest_sha256:
            raise MediaError("model_missing")


def _collapse_alignment_tokens(
    words: list[TranscriptWord],
    returned: list[tuple[str, int, int]],
    *,
    source_offset: int,
) -> list[tuple[int, int]]:
    """Group aligner pieces back onto transcript words. Stored text is not rewritten."""
    cursor = 0
    bounds: list[tuple[int, int]] = []
    for expected in words:
        target = expected.text.strip()
        if not target:
            raise MediaError(f"transcript word {expected.word_id} is empty")
        collected = ""
        start: int | None = None
        end: int | None = None
        while cursor < len(returned) and collected != target:
            token, token_start, token_end = returned[cursor]
            piece = token.strip()
            cursor += 1
            if not piece:
                continue
            if token_end <= token_start:
                raise MediaError("WhisperX returned a word with no positive duration.")
            if not target.startswith(collected + piece):
                raise MediaError(
                    f"WhisperX text {token!r} does not match transcript word {expected.text!r}. "
                    "The transcript text was not rewritten."
                )
            if start is None:
                start = token_start
            collected += piece
            end = token_end
        if collected != target or start is None or end is None or end <= start:
            raise MediaError(
                "WhisperX word count does not match the transcript evidence. "
                "Hero alignment does not invent or drop words."
            )
        bounds.append((source_offset + start, source_offset + end))
    if cursor != len(returned):
        raise MediaError("WhisperX returned extra tokens. Hero alignment does not invent or drop words.")
    return bounds


def _whisperx_version() -> str:
    try:
        import whisperx
    except ImportError:
        whisperx = None
    if whisperx is not None:
        del whisperx
        return _installed_whisperx_version()
    python = _align_python()
    if python is None:
        raise MediaError(
            "WhisperX is not installed. Hero alignment does not fall back to provisional timings. "
            "Install WhisperX locally before hero align. Clipforge does not download it automatically."
        )
    import subprocess

    completed = subprocess.run(
        [str(python), "-c", "import importlib.metadata as meta; print(meta.version('whisperx'))"],
        text=True,
        capture_output=True,
        check=False,
    )
    found = completed.stdout.strip()
    if completed.returncode != 0 or not found or "/" in found or len(found) > 40:
        raise MediaError("WhisperX is installed but its version could not be read.")
    return found


def _installed_whisperx_version() -> str:
    try:
        from importlib.metadata import version

        found = version("whisperx")
    except Exception:
        found = ""
    if not found:
        return "unknown"
    return found
