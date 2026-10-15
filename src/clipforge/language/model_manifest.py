"""Measure the alignment model that is actually on disk.

A catalog row is the expected identity. It is not proof that those bytes were
loaded. ``verified_live`` requires an external speech file whose hash, WAV
facts, locale, and model identity match this measurement. A JSON row alone
is not enough.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.workspace import ensure_within
from clipforge.schemas.language import SpeechEvidenceCatalog, SpeechEvidenceRecord

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


_WHISPERX_VERSION: tuple[str, str] | None = None


def speech_catalog_path() -> Path:
    """The committed speech index. Audio bytes are not in this file."""
    override = os.environ.get("CLIPFORGE_SPEECH_EVIDENCE_CATALOG", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "speech_evidence.json"


def speech_evidence_root() -> Path | None:
    """Locate external evidence without substituting for an explicit override.

    Discovery selects a directory only. The provider still measures its WAV
    bytes, catalog binding and model identity before granting live status.
    """
    raw = os.environ.get("CLIPFORGE_SPEECH_EVIDENCE_ROOT", "").strip()
    root = Path(raw) if raw else Path.home() / ".local" / "clipforge-speech-evidence"
    if not root.is_dir() or root.is_symlink():
        return None
    return root


def load_speech_catalog(path: Path | None = None) -> SpeechEvidenceCatalog | None:
    """Read the typed catalog. An old or partial document is not evidence."""
    catalog = path or speech_catalog_path()
    if not catalog.is_file() or catalog.is_symlink():
        return None
    try:
        return SpeechEvidenceCatalog.model_validate_json(catalog.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None


def resolve_speech_audio(root: Path, filename: str) -> Path | None:
    """Resolve one relative filename under the evidence root. Escapes and links fail closed."""
    if not filename or filename.startswith(("/", "\\")) or "\\" in filename or ".." in filename.split("/"):
        return None
    if "/" in filename or root.is_symlink() or not root.is_dir():
        return None
    candidate = root / filename
    if candidate.is_symlink() or not candidate.is_file():
        return None
    try:
        ensure_within(root, candidate)
    except MediaError:
        return None
    return candidate


def wav_signature(path: Path) -> tuple[int, int, int] | None:
    """Return sample rate, channels, and duration from the bytes that are actually present.

    Some writers store a placeholder data-chunk size. The duration uses the
    bytes that follow the data header when that declared size overruns the file.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    offset = 12
    rate = channels = bits = None
    while offset + 8 <= len(data):
        chunk = data[offset : offset + 4]
        declared = int.from_bytes(data[offset + 4 : offset + 8], "little")
        body = offset + 8
        if chunk == b"fmt " and declared >= 16 and body + 16 <= len(data):
            channels = int.from_bytes(data[body + 2 : body + 4], "little")
            rate = int.from_bytes(data[body + 4 : body + 8], "little")
            bits = int.from_bytes(data[body + 14 : body + 16], "little")
        elif chunk == b"data":
            available = len(data) - body
            used = available if declared > available else declared
            if rate is None or channels is None or bits is None or bits < 8 or channels < 1:
                return None
            frame = channels * (bits // 8)
            if frame <= 0 or used <= 0 or rate <= 0:
                return None
            return rate, channels, (used * 1_000_000) // (rate * frame)
        step = declared + (declared % 2)
        if body + step < body or body + step > len(data):
            return None
        offset = body + step
    return None


def measured_whisperx_version() -> str:
    """Version reported by the alignment interpreter. An unread version is empty.

    A missing interpreter is not cached. One test can point
    ``CLIPFORGE_ALIGN_PYTHON`` at a file that does not exist, and the next
    call must still be able to read the real interpreter.
    """
    global _WHISPERX_VERSION
    configured = os.environ.get("CLIPFORGE_ALIGN_PYTHON", "").strip()
    default = Path.home() / ".local" / "clipforge-hero-align" / "bin" / "python"
    python = Path(configured) if configured else default
    key = str(python)
    if _WHISPERX_VERSION is not None and _WHISPERX_VERSION[0] == key:
        return _WHISPERX_VERSION[1]
    if not python.is_file():
        return ""
    try:
        completed = subprocess.run(
            [str(python), "-c", "import importlib.metadata as meta; print(meta.version('whisperx'))"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    found = completed.stdout.strip()
    if completed.returncode != 0 or not found or "/" in found or len(found) > 40:
        return ""
    _WHISPERX_VERSION = (key, found)
    return found


def bound_speech_record(
    locale: str,
    *,
    evidence_root: Path | None = None,
    catalog_path: Path | None = None,
) -> SpeechEvidenceRecord | None:
    """The speech record whose external file matches the stored hash and WAV facts."""
    catalog = load_speech_catalog(catalog_path)
    if catalog is None:
        return None
    record = next((item for item in catalog.records if item.locale == locale), None)
    if record is None:
        return None
    root = evidence_root if evidence_root is not None else speech_evidence_root()
    if root is None:
        return None
    audio = resolve_speech_audio(root, record.audio_filename)
    if audio is None:
        return None
    if sha256_file(audio) != record.audio_sha256:
        return None
    signature = wav_signature(audio)
    if signature is None:
        return None
    rate, channels, duration_us = signature
    if rate != record.sample_rate or channels != record.channels or duration_us != record.duration_us:
        return None
    if record.audio_class not in {"recorded_speech", "tts_speech"}:
        return None
    if not record.transcript.strip() or record.token_count < 3:
        return None
    return record


def packaged_speech_catalog_path() -> Path:
    """The speech index shipped with this build. An override cannot replace it."""
    return Path(__file__).resolve().parent / "speech_evidence.json"


def packaged_speech_record(locale: str) -> SpeechEvidenceRecord | None:
    """The committed speech record for one locale, if this build has one."""
    catalog = load_speech_catalog(packaged_speech_catalog_path())
    if catalog is None:
        return None
    return next((item for item in catalog.records if item.locale == locale), None)


def speech_identity_matches(
    record: SpeechEvidenceRecord,
    *,
    locale: str,
    model_id: str,
    model_revision: str,
    checkpoint_sha256: str,
    manifest_sha256: str,
    whisperx_version: str,
    device: str,
) -> bool:
    """True when one speech record is the same locale and model the caller measured."""
    if record.locale != locale or record.audio_class not in {"recorded_speech", "tts_speech"}:
        return False
    if not record.transcript.strip() or record.token_count < 3:
        return False
    if record.model_id != model_id or record.model_revision != model_revision:
        return False
    if record.checkpoint_sha256 != checkpoint_sha256 or record.manifest_sha256 != manifest_sha256:
        return False
    return record.whisperx_version == whisperx_version and record.device == device


def speech_record_matches_package(record: SpeechEvidenceRecord) -> bool:
    """A forged catalog row is not evidence, even when its file hash is self-consistent."""
    packaged = packaged_speech_record(record.locale)
    return packaged is not None and record.model_dump() == packaged.model_dump()


def speech_evidence_grants_live(
    locale: str,
    *,
    model_id: str,
    model_revision: str,
    checkpoint_sha256: str,
    manifest_sha256: str,
    whisperx_version: str,
    device: str,
    evidence_root: Path | None = None,
    catalog_path: Path | None = None,
) -> bool:
    """True only when the external file, the packaged record, and the measured model agree."""
    record = bound_speech_record(locale, evidence_root=evidence_root, catalog_path=catalog_path)
    if record is None or not speech_record_matches_package(record):
        return False
    if not speech_identity_matches(
        record,
        locale=locale,
        model_id=model_id,
        model_revision=model_revision,
        checkpoint_sha256=checkpoint_sha256,
        manifest_sha256=manifest_sha256,
        whisperx_version=whisperx_version,
        device=device,
    ):
        return False
    installed = measured_whisperx_version()
    return bool(installed) and installed == record.whisperx_version


def speech_smoke_manifest(locale: str, *, evidence_root: Path | None = None) -> str:
    """Manifest of a fully bound speech record, or an empty string when evidence is incomplete."""
    record = bound_speech_record(locale, evidence_root=evidence_root)
    if record is None:
        return ""
    return record.manifest_sha256
