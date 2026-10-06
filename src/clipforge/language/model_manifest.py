"""Measure the alignment model that is actually on disk.

A catalog row is the expected identity. It is not proof that those bytes were
loaded. ``verified_live`` requires a stored multi-word speech record whose
manifest matches this measurement. A matching weight hash alone is not enough.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

_INFERENCE_NAMES = frozenset(
    {
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
)
_ALLOWED_LICENSES = frozenset({"apache-2.0"})


@dataclass(frozen=True, slots=True)
class MeasuredModel:
    """Files that affect one alignment inference, and their manifest hash."""

    model_id: str
    revision: str
    manifest_sha256: str
    checkpoint_sha256: str
    files: tuple[tuple[str, int, str], ...]


def license_explicitly_allowed(license_name: str) -> bool:
    """An alignment license must be an explicit allow. Unknown is not allowed."""
    return license_name.strip().lower() in _ALLOWED_LICENSES


def manifest_sha256(files: tuple[tuple[str, int, str], ...] | list[tuple[str, int, str]]) -> str:
    """Hash sorted relative path, size, and SHA-256. Order on disk does not matter."""
    rows = [
        {"path": path, "sha256": digest, "size": size}
        for path, size, digest in sorted(files, key=lambda item: item[0])
    ]
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _regular_file(path: Path) -> Path | None:
    """Follow one Hugging Face blob symlink. Refuse a link that is not a file."""
    if path.is_symlink():
        target = path.resolve()
        if target.is_file():
            return target
        return None
    if path.is_file():
        return path
    return None


_FILE_HASHES: dict[tuple[str, int, int], str] = {}


def sha256_file(path: Path) -> str:
    """Hash one file. A repeat in this process reuses the result when the file is unchanged."""
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _FILE_HASHES.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _FILE_HASHES[key] = value
    return value


def measure_tree(root: Path, *, model_id: str, revision: str) -> MeasuredModel | None:
    """Hash inference files in one local snapshot. A missing weight file is absent."""
    if not root.is_dir() or root.is_symlink():
        return None
    files: list[tuple[str, int, str]] = []
    for path in sorted(root.iterdir()):
        target = _regular_file(path)
        if target is None or path.name not in _INFERENCE_NAMES:
            continue
        files.append((path.name, target.stat().st_size, sha256_file(target)))
    names = {item[0] for item in files}
    weight_names = ("pytorch_model.bin", "model.safetensors", "wav2vec2_fairseq_base_ls960_asr_ls960.pth")
    if not any(name in names for name in weight_names):
        return None
    weight_name = next(name for name in weight_names if name in names)
    weight = next(item for item in files if item[0] == weight_name)
    packed = tuple(files)
    return MeasuredModel(
        model_id=model_id,
        revision=revision,
        manifest_sha256=manifest_sha256(packed),
        checkpoint_sha256=weight[2],
        files=packed,
    )


def huggingface_snapshot(model_id: str, revision: str, *, cache_root: Path | None = None) -> Path | None:
    """Return the local Hugging Face snapshot for one immutable revision."""
    if not model_id or "/" not in model_id or not revision:
        return None
    root = cache_root or (Path.home() / ".cache" / "huggingface" / "hub")
    slug = "models--" + model_id.replace("/", "--")
    snapshot = root / slug / "snapshots" / revision
    if snapshot.is_dir() and not snapshot.is_symlink():
        return snapshot
    return None


def english_checkpoint_file(*, cache_root: Path | None = None) -> Path | None:
    """The torchaudio English checkpoint, if this machine has the file."""
    root = cache_root or (Path.home() / ".cache" / "torch" / "hub" / "checkpoints")
    path = root / "wav2vec2_fairseq_base_ls960_asr_ls960.pth"
    if path.is_file() and not path.is_symlink():
        return path
    return None


def measure_english_checkpoint(path: Path) -> MeasuredModel:
    """One-file manifest for the torchaudio English checkpoint."""
    digest = sha256_file(path)
    files = (("wav2vec2_fairseq_base_ls960_asr_ls960.pth", path.stat().st_size, digest),)
    return MeasuredModel(
        model_id="WAV2VEC2_ASR_BASE_960H",
        revision="3.4.5",
        manifest_sha256=manifest_sha256(files),
        checkpoint_sha256=digest,
        files=files,
    )


def speech_smoke_manifest(locale: str, *, evidence_root: Path | None = None) -> str:
    """Manifest hash recorded for a real spoken smoke, or an empty string."""
    root = evidence_root or Path(__file__).resolve().parent
    path = root / "speech_evidence.json"
    if not path.is_file() or path.is_symlink():
        return ""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ""
    if not isinstance(document, dict):
        return ""
    row = document.get(locale)
    if not isinstance(row, dict):
        return ""
    if row.get("audio_class") not in {"recorded_speech", "tts_speech"}:
        return ""
    transcript = row.get("transcript")
    tokens = row.get("token_count")
    if not isinstance(transcript, str) or not transcript.strip():
        return ""
    if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 3:
        return ""
    manifest = row.get("manifest_sha256")
    if not isinstance(manifest, str) or len(manifest) != 64:
        return ""
    return manifest
