"""Local faster-whisper smoke. Not used by CI.

Run from the repository root:

    uv run python scripts/transcription_smoke.py

This downloads tiny.en into var/models when it is not cached. It does not
upload audio. Silence or a local espeak phrase only checks that the stack
runs. It is not a word-error measurement.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from clipforge.paths import resolve_model_root
from clipforge.transcription.backend import FasterWhisperBackend
from clipforge.transcription.models import ensure_model
from clipforge.transcription.profile import decoding_profile
from clipforge.transcription.runtime import probe_runtime, resolve_runtime


def main() -> None:
    root = resolve_model_root(None)
    print(f"model_root: {root}")
    facts = probe_runtime()
    print(f"cuda_device_count: {facts.cuda_device_count}")
    print(f"cpu_compute_types: {', '.join(facts.cpu_compute_types)}")
    print(f"cuda_compute_types: {', '.join(facts.cuda_compute_types) or 'none'}")
    print(f"cuda_error: {facts.cuda_error or 'none'}")
    identity = ensure_model("tiny.en", root, allow_download=True)
    print(f"model_path: {identity.local_path}")
    print(f"model_revision: {identity.revision}")
    print(f"model_source: {identity.source}")
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "smoke.flac"
        _silence(audio)
        _run("cpu", audio, identity)
        if facts.cuda_usable:
            try:
                _run("cuda", audio, identity)
            except Exception as exc:
                print(f"gpu_result: FAIL {exc.__class__.__name__}: {exc}")
        else:
            print("gpu_result: not attempted; CTranslate2 CUDA is not usable")
        auto = resolve_runtime(requested_device="auto", requested_compute_type="auto", facts=facts)
        print(f"auto_device: {auto.device}")
        print(f"auto_compute_type: {auto.compute_type}")
        print(f"auto_warning: {auto.warning or 'none'}")
        phrase = _speech(Path(tmp))
        if phrase is not None:
            _run("cpu", phrase, identity, label="speech")


def _silence(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is required for the smoke FLAC")
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            "1",
            "-c:a",
            "flac",
            str(path),
        ],
        check=True,
    )


def _speech(directory: Path) -> Path | None:
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak is None:
        print("speech_synth: not installed; skipped")
        return None
    wav = directory / "phrase.wav"
    subprocess.run([espeak, "-w", str(wav), "Clipforge transcription test"], check=True)
    flac = directory / "phrase.flac"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(flac),
        ],
        check=True,
    )
    return flac


def _run(device: str, audio: Path, identity: object, label: str = "silence") -> None:
    from clipforge.transcription.models import ModelIdentity

    if not isinstance(identity, ModelIdentity):
        raise SystemExit("model identity was lost")
    runtime = resolve_runtime(requested_device=device, requested_compute_type="auto")
    backend = FasterWhisperBackend()
    started = time.perf_counter()
    handle = backend.transcribe(
        audio,
        model=identity,
        runtime=runtime,
        profile=decoding_profile("en"),
    )
    segments = list(handle.segments)
    infer = time.perf_counter() - started
    words = sum(len(segment.words) for segment in segments)
    text = "".join(segment.text for segment in segments)
    print(f"{label}_{device}_compute: {runtime.compute_type}")
    print(f"{label}_{device}_load_s: {handle.info.model_load_seconds:.3f}")
    print(f"{label}_{device}_infer_s: {infer:.3f}")
    print(f"{label}_{device}_segments: {len(segments)}")
    print(f"{label}_{device}_words: {words}")
    print(f"{label}_{device}_text: {text!r}")


if __name__ == "__main__":
    main()
