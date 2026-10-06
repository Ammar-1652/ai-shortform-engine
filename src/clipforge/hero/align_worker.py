"""WhisperX worker for the optional alignment environment. It prints JSON only."""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys


def main() -> int:
    request = json.loads(sys.stdin.read())
    allow = bool(request.get("allow_model_download"))
    if not allow:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_DATASETS_OFFLINE"] = "1"
    language_code = request.get("language_code")
    model_name = request.get("model_name")
    if not isinstance(language_code, str) or not isinstance(model_name, str):
        raise RuntimeError("alignment request is missing a language or a model")
    if language_code != "en" and model_name == "WAV2VEC2_ASR_BASE_960H":
        raise RuntimeError("refusing to fall back to the English alignment model")
    if model_name.startswith("VOXPOPULI_") or model_name.lower().startswith("k2-fsa/"):
        raise RuntimeError("alignment model license is not permitted")
    import whisperx  # type: ignore[import-not-found]

    audio = whisperx.load_audio(request["audio_path"])
    start = int(request["source_start_us"])
    end = int(request["source_end_us"])
    clip = audio[(start * 16) // 1000 : (end * 16) // 1000]
    words = request["words"]
    text = "".join(str(item["text"]) for item in words).strip()
    duration_s = (end - start) / 1_000_000
    segments = [{"text": text, "start": 0.0, "end": duration_s}]
    model, metadata = whisperx.load_align_model(
        language_code=language_code,
        device="cpu",
        model_name=model_name,
    )
    aligned = whisperx.align(segments, model, metadata, clip, "cpu", return_char_alignments=False)
    returned = []
    for segment in aligned.get("segments", []):
        for word in segment.get("words", []):
            returned.append(
                {
                    "text": word.get("word"),
                    "start_us": round(float(word["start"]) * 1_000_000),
                    "end_us": round(float(word["end"]) * 1_000_000),
                }
            )
    payload = {
        "words": returned,
        "whisperx": importlib.metadata.version("whisperx"),
        "torch": importlib.metadata.version("torch"),
        "torchaudio": importlib.metadata.version("torchaudio"),
        "device": "cpu",
        "model": model_name,
        "language_code": language_code,
    }
    sys.stdout.write(json.dumps(payload))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write(f"whisperx worker failed: {exc.__class__.__name__}\n")
        raise SystemExit(1) from exc
