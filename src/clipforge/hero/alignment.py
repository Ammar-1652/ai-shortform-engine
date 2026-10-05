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


def production_alignment_backend(
    language: str | None,
    *,
    allow_model_download: bool = False,
) -> WhisperXAlignment:
    """Pick the live aligner for one language. A missing model is not a pass.

    Unit tests inject ``FakeForcedAlignment`` themselves. A production campaign
    does not.
    """
    from clipforge.language.registry import alignment_claim

    normalized = "en-US" if language in {None, "", "en"} else language
    try:
        claim = alignment_claim(normalized)
    except ValueError as exc:
        raise MediaError("unsupported_language") from exc
    if claim != "whisperx":
        raise MediaError("alignment_not_claimed")
    return WhisperXAlignment(allow_model_download=allow_model_download)


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
    try:
        import whisperx  # type: ignore[import-not-found]
    except ImportError:
        return _align_with_side_python(
            audio_path,
            words,
            source_start_us=source_start_us,
            source_end_us=source_end_us,
            allow_model_download=allow_model_download,
        )
    if not allow_model_download:
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
            model, metadata = _load_align_model(whisperx, allow_model_download=allow_model_download)
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


def _load_align_model(whisperx: Any, *, allow_model_download: bool) -> tuple[object, object]:
    """Load the English aligner. Cache-only builds must not fetch weights."""
    loader: Callable[..., Any] = whisperx.load_align_model
    kwargs: dict[str, object] = {"language_code": "en", "device": "cpu"}
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
) -> list[tuple[int, int]]:
    """Run the optional alignment interpreter. The result is still production WhisperX."""
    import subprocess

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
    if len(pairs) != len(words):
        raise MediaError(
            "WhisperX word count does not match the transcript evidence. "
            "Hero alignment does not invent or drop words."
        )
    bounds: list[tuple[int, int]] = []
    for expected, (token, start, end) in zip(words, pairs, strict=True):
        if token.strip() != expected.text.strip():
            raise MediaError(
                f"WhisperX text {token!r} does not match transcript word {expected.text!r}. "
                "The transcript text was not rewritten."
            )
        if end <= start:
            raise MediaError("WhisperX returned a word with no positive duration.")
        bounds.append((source_start_us + start, source_start_us + end))
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
