"""Forced word alignment for one approved candidate.

The production adapter calls WhisperX on the candidate span only. Tests inject
``FakeForcedAlignment``. Provisional transcript times are not copied into a
Hero alignment.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

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
from clipforge.timeline.framerate import FrameRate


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

    def __init__(self, *, allow_model_download: bool = False, audio_path: str | None = None) -> None:
        self.allow_model_download = allow_model_download
        self.audio_path = audio_path
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
        return align_trimmed_with_whisperx(
            self.audio_path,
            words,
            source_start_us=source_start_us,
            source_end_us=source_end_us,
            allow_model_download=self.allow_model_download,
        )


def alignment_config_sha256(*, model_name: str, whisperx_version: str, device: str) -> str:
    payload = {"device": device, "model_name": model_name, "whisperx_version": whisperx_version}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


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
) -> ForcedAlignmentDocument:
    """Align the candidate's own words. Missing word ids are a hard failure."""
    if not bundle.transcript_word_ids:
        raise MediaError(
            f"candidate {candidate.candidate_id} has no transcript word ids. "
            "Hero alignment does not invent words from segment text."
        )
    if len(candidate.time_map.segments) != 1:
        raise MediaError(
            f"candidate {candidate.candidate_id} has {len(candidate.time_map.segments)} TimeMap segments. "
            "Hero alignment v1 aligns one segment and does not invent a join."
        )
    ordered = _evidence_words(transcript, bundle)
    segment = candidate.time_map.segments[0]
    time_map = candidate.time_map.to_time_map()
    frame_count = time_map.output_frame_count(FrameRate(30, 1))
    bounds = backend.align_words(
        ordered,
        source_start_us=segment.source_start_us,
        source_end_us=segment.source_end_us,
    )
    if len(bounds) != len(ordered):
        raise MediaError("forced alignment did not return one interval per evidence word")
    aligned: list[AlignedWord] = []
    previous_output_end = -1
    duration = time_map.total_output_duration()
    for word, (start, end) in zip(ordered, bounds, strict=True):
        if end <= start:
            raise MediaError(f"aligned word {word.word_id} has no positive duration")
        if start < segment.source_start_us or end > segment.source_end_us:
            raise MediaError(f"aligned word {word.word_id} leaves the candidate TimeMap")
        output_start = time_map.source_to_output(start)
        output_end = time_map.source_to_output(end)
        if output_end > duration or output_start < 0:
            raise MediaError(f"aligned word {word.word_id} leaves the output TimeMap")
        if output_start < previous_output_end:
            raise MediaError(f"aligned word {word.word_id} overlaps the previous word on the output clock")
        previous_output_end = output_end
        start_frame = frame_at_or_after(output_start, frame_count)
        end_frame = frame_at_or_after(output_end, frame_count)
        if start_frame >= end_frame:
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
) -> list[tuple[int, int]]:
    """Align one already-trimmed ASR span. Returned times are on the source clock."""
    span = source_end_us - source_start_us
    relative = align_span_with_whisperx(
        audio_path,
        words,
        source_start_us=0,
        source_end_us=span,
        allow_model_download=allow_model_download,
    )
    return [(source_start_us + start, source_start_us + end) for start, end in relative]


def align_span_with_whisperx(
    audio_path: str,
    words: list[TranscriptWord],
    *,
    source_start_us: int,
    source_end_us: int,
    allow_model_download: bool,
) -> list[tuple[int, int]]:
    """Run WhisperX on one candidate span. The full source is not transcribed."""
    import os

    if not allow_model_download:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
        _require_cached_punkt()
    try:
        import whisperx  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MediaError(
            "WhisperX is not installed. Hero alignment does not fall back to provisional timings. "
            "Install WhisperX locally before hero align. Clipforge does not download it automatically."
        ) from exc
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
            model, metadata = whisperx.load_align_model(
                language_code="en",
                device="cpu",
                model_cache_only=not allow_model_download,
            )
    except TypeError as exc:
        raise MediaError(
            "the installed WhisperX does not support its cache-only alignment option. "
            "Upgrade WhisperX before running Hero alignment."
        ) from exc
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(
            "WhisperX could not load the English alignment model. "
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
    if len(returned) != len(words):
        raise MediaError(
            "WhisperX word count does not match the transcript evidence. "
            "Hero alignment does not invent or drop words."
        )
    bounds: list[tuple[int, int]] = []
    for expected, (token, start, end) in zip(words, returned, strict=True):
        if token.strip() != expected.text.strip():
            raise MediaError(
                f"WhisperX text {token!r} does not match transcript word {expected.text!r}. "
                "The transcript text was not rewritten."
            )
        bounds.append((source_start_us + start, source_start_us + end))
    return bounds


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


def _whisperx_version() -> str:
    try:
        import whisperx
    except ImportError as exc:
        raise MediaError(
            "WhisperX is not installed. Hero alignment does not fall back to provisional timings. "
            "Install WhisperX locally before hero align. Clipforge does not download it automatically."
        ) from exc
    version = getattr(whisperx, "__version__", "")
    if not isinstance(version, str) or not version:
        return "unknown"
    return version
