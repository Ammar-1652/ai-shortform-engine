"""Test double for faster-whisper. Production code does not import this module."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from clipforge.transcription.backend import InferenceHandle, InferenceInfo, RawSegment, RawWord
from clipforge.transcription.models import ModelIdentity
from clipforge.transcription.profile import DecodingProfile
from clipforge.transcription.runtime import ResolvedRuntime

HELLO = RawSegment(
    text="Hello world.",
    start_seconds=0.0,
    end_seconds=1.2,
    words=(
        RawWord(text=" Hello", start_seconds=0.0, end_seconds=0.5, probability=0.95),
        RawWord(text=" world.", start_seconds=0.5, end_seconds=1.2, probability=0.93),
    ),
    avg_logprob=-0.25,
    no_speech_prob=0.01,
    compression_ratio=1.2,
    temperature=0.0,
)
NEXT = RawSegment(
    text="Next segment.",
    start_seconds=2.0,
    end_seconds=3.0,
    words=(RawWord(text=" Next", start_seconds=2.0, end_seconds=3.0, probability=0.9),),
    avg_logprob=-0.3,
    no_speech_prob=0.02,
    compression_ratio=1.1,
    temperature=0.0,
)


class FakeTranscriptionBackend:
    """Returns fixed segments. ``fail_after`` raises once that many segments were yielded."""

    def __init__(
        self,
        segments: tuple[RawSegment, ...] | None = None,
        *,
        fail_after: int | None = None,
        interrupt_after: int | None = None,
    ) -> None:
        self.segments = (HELLO, NEXT) if segments is None else segments
        self.fail_after = fail_after
        self.interrupt_after = interrupt_after
        self.calls = 0
        self.devices: list[str] = []

    def transcribe(
        self,
        audio_path: Path,
        *,
        model: ModelIdentity,
        runtime: ResolvedRuntime,
        profile: DecodingProfile,
    ) -> InferenceHandle:
        del audio_path, model, profile
        self.calls += 1
        self.devices.append(runtime.device)
        segments = self.segments
        fail_after = self.fail_after
        interrupt_after = self.interrupt_after

        def iterate() -> Iterator[RawSegment]:
            for index, segment in enumerate(segments):
                if interrupt_after is not None and index >= interrupt_after:
                    raise KeyboardInterrupt
                if fail_after is not None and index >= fail_after:
                    raise RuntimeError("segment iterator failed")
                yield segment

        return InferenceHandle(
            info=InferenceInfo(language="en", language_probability=0.98, model_load_seconds=0.01),
            segments=iterate(),
        )
