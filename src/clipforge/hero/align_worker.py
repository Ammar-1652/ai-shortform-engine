"""WhisperX worker for the optional alignment environment. It prints JSON only."""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys
from collections.abc import Callable
from typing import Any


def _sha256_path(path: str) -> str:
    if not path:
        return ""
    import hashlib
    from pathlib import Path

    file_path = Path(path)
    if not file_path.is_file() or file_path.is_symlink():
        return ""
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(model_path: str, checkpoint_path: str) -> str:
    import json
    from pathlib import Path

    names = {
        "config.json",
        "preprocessor_config.json",
        "vocab.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "pytorch_model.bin",
        "model.safetensors",
        "wav2vec2_fairseq_base_ls960_asr_ls960.pth",
    }
    roots = [Path(model_path)] if model_path else []
    if checkpoint_path:
        roots.append(Path(checkpoint_path).parent)
    files: list[tuple[str, int, str]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            target = path.resolve() if path.is_symlink() else path
            if path.name not in names or not target.is_file():
                continue
            files.append((path.name, target.stat().st_size, _sha256_path(str(target))))
    if not files:
        return ""
    rows = [{"path": path, "sha256": digest, "size": size} for path, size, digest in sorted(files)]
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def install_offline_guards() -> None:
    """Block weight downloads. Passing model_cache_only is not this guard."""
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

    def _blocked(kind: str) -> Callable[..., None]:
        def _raise(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError(f"{kind} download is blocked")

        return _raise

    try:
        import torch.hub  # type: ignore[import-not-found]

        hub: Any = torch.hub
        hub.download_url_to_file = _blocked("torch.hub")
    except ImportError:
        pass
    try:
        import huggingface_hub

        hf: Any = huggingface_hub
        hf.hf_hub_download = _blocked("Hugging Face")
        hf.snapshot_download = _blocked("Hugging Face")
    except ImportError:
        pass
    try:
        import nltk  # type: ignore[import-not-found]

        tokenizer: Any = nltk
        tokenizer.download = _blocked("nltk")
    except ImportError:
        pass


def main() -> int:
    request = json.loads(sys.stdin.read())
    allow = bool(request.get("allow_model_download"))
    if not allow:
        install_offline_guards()
    language_code = request.get("language_code")
    model_name = request.get("model_name")
    model_path = request.get("model_path") if isinstance(request.get("model_path"), str) else ""
    checkpoint_path = request.get("checkpoint_path") if isinstance(request.get("checkpoint_path"), str) else ""
    revision = request.get("revision") if isinstance(request.get("revision"), str) else ""
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
    loaded_name = model_path or model_name
    model, metadata = whisperx.load_align_model(
        language_code=language_code,
        device="cpu",
        model_name=loaded_name,
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
        "revision": revision,
        "checkpoint_sha256": _sha256_path(checkpoint_path),
        "manifest_sha256": _manifest(model_path, checkpoint_path),
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
