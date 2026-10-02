"""Model cache. Weights download only after an explicit allow flag.

A hub snapshot is identified by its revision directory name. A local model
directory has no revision, so Clipforge fingerprints file names, sizes,
mtimes, and the hashes of the small metadata files. ``model.bin`` is not
re-hashed on every run. A same-size, same-mtime replacement of that file
would not change the fingerprint. Hub snapshots do not depend on that
shortcut: a new commit is a new snapshot directory.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.errors import MediaError
from clipforge.media.disk import read_disk, require_disk_budget

_METADATA_NAMES = frozenset(
    {
        "config.json",
        "preprocessor_config.json",
        "tokenizer.json",
        "vocabulary.json",
        "vocabulary.txt",
    }
)
_METADATA_LIMIT = 5_000_000


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    requested: str
    source: Literal["hub_snapshot", "local_directory"]
    local_path: str
    revision: str


def model_root_status(root: Path) -> tuple[Path, int, int]:
    """Return the resolved root, free bytes, and reserve bytes. Does not download."""
    path = _prepare_root(root)
    status = read_disk(path)
    return path, status.free_bytes, status.reserve_bytes


def resolve_cached_model(requested: str, root: Path, *, create_root: bool = True) -> ModelIdentity | None:
    """Return a local identity, or None when the model is not cached. No download."""
    if root.is_symlink():
        raise MediaError(f"model root {root} is a symlink. Refusing to follow it.")
    if not create_root and not root.exists():
        return None
    path = _prepare_root(root, create=create_root)
    local = _local_directory(requested)
    if local is not None:
        return _identity(requested, local, source="local_directory")
    snapshot = _cached_snapshot(requested, path)
    if snapshot is None:
        return None
    return _identity(requested, snapshot, source="hub_snapshot")


def ensure_model(requested: str, root: Path, *, allow_download: bool) -> ModelIdentity:
    """Return a local model. Download only when ``allow_download`` is true."""
    cached = resolve_cached_model(requested, root)
    if cached is not None:
        return cached
    if _local_directory(requested) is not None:
        raise MediaError(f"local model directory {requested} is not readable")
    if not allow_download:
        raise MediaError(
            f"Model {requested} is not available in the configured Clipforge model cache. "
            "Re-run with --allow-model-download to explicitly permit model acquisition."
        )
    _require_download_room(root, requested)
    downloaded = _download(requested, _prepare_root(root))
    return _identity(requested, downloaded, source="hub_snapshot")


def _prepare_root(root: Path, *, create: bool = True) -> Path:
    """Reject a symlinked model root before following it. Optionally create a real directory."""
    if root.is_symlink():
        raise MediaError(f"model root {root} is a symlink. Refusing to follow it.")
    if create:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise MediaError(f"could not create the model root {root}: {exc}") from exc
    if root.is_symlink():
        raise MediaError(f"model root {root} is a symlink. Refusing to follow it.")
    if not root.exists():
        raise MediaError(f"model root {root} does not exist")
    return root.resolve()


def _local_directory(requested: str) -> Path | None:
    if "/" not in requested and not requested.startswith((".", "~")):
        return None
    candidate = Path(requested).expanduser()
    if candidate.is_symlink():
        raise MediaError(f"refusing to follow a symlinked model path {candidate}")
    if candidate.is_dir():
        return candidate.resolve()
    if candidate.exists():
        raise MediaError(f"model path {candidate} is not a directory")
    raise MediaError(f"local model directory does not exist: {candidate}")


def _cached_snapshot(requested: str, root: Path) -> Path | None:
    try:
        from faster_whisper.utils import download_model
    except ImportError as exc:
        raise MediaError("faster-whisper is not installed. Run uv sync. A model was not downloaded.") from exc
    try:
        found = download_model(requested, local_files_only=True, cache_dir=str(root))
    except Exception:
        return None
    path = Path(found)
    if not path.is_dir():
        return None
    return path.resolve()


def _download(requested: str, root: Path) -> Path:
    try:
        from faster_whisper.utils import download_model
    except ImportError as exc:
        raise MediaError("faster-whisper is not installed. Run uv sync.") from exc
    try:
        found = download_model(requested, local_files_only=False, cache_dir=str(root))
    except Exception as exc:
        raise MediaError(
            f"could not download model {requested} into {root}: {exc.__class__.__name__}: {exc}. "
            "No transcript was started."
        ) from exc
    path = Path(found).resolve()
    if not path.is_dir():
        raise MediaError(f"model download for {requested} did not produce a directory")
    return path


def _require_download_room(root: Path, requested: str) -> None:
    status = read_disk(_prepare_root(root))
    require_download_budget(status.free_bytes, status.reserve_bytes, _remote_size_bytes(requested), requested)


def require_download_budget(
    free_bytes: int, reserve_bytes: int, expected_bytes: int | None, requested: str
) -> None:
    """Refuse a download that is not proven to leave the reserve free.

    ``expected_bytes`` is the sum of the model files Hugging Face reports with
    ``files_metadata=True``. Unknown size fails closed. A local model directory
    does not call this.
    """
    if expected_bytes is None:
        raise MediaError(
            "Clipforge could not determine the model download size, so it cannot prove "
            "the configured disk reserve will remain intact. Model download was not started."
        )
    try:
        require_disk_budget(free_bytes, reserve_bytes, expected_bytes)
    except MediaError as exc:
        raise MediaError(
            f"refusing to download model {requested}. {exc} The model size is {expected_bytes} bytes."
        ) from exc


def _remote_size_bytes(requested: str) -> int | None:
    """Sum the files faster-whisper would fetch. None when any size is missing."""
    try:
        from faster_whisper.utils import _MODELS
        from huggingface_hub import HfApi
    except Exception:
        return None
    repo_id = _MODELS.get(requested, requested if "/" in requested else None)
    if not isinstance(repo_id, str):
        return None
    try:
        info = HfApi().model_info(repo_id, files_metadata=True)
    except Exception:
        return None
    siblings = getattr(info, "siblings", None) or []
    total = 0
    saw_file = False
    for sibling in siblings:
        name = str(getattr(sibling, "rfilename", "") or "")
        if not _is_downloaded_model_file(name):
            continue
        size = getattr(sibling, "size", None)
        if not isinstance(size, int) or size < 0:
            return None
        total += size
        saw_file = True
    if not saw_file:
        return None
    return total


def _is_downloaded_model_file(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    if base in {"config.json", "preprocessor_config.json", "model.bin", "tokenizer.json"}:
        return True
    return base.startswith("vocabulary.")


def _identity(
    requested: str, path: Path, *, source: Literal["hub_snapshot", "local_directory"]
) -> ModelIdentity:
    if path.is_symlink():
        raise MediaError(f"refusing to follow symlinked model directory {path}")
    resolved = path.resolve()
    revision_name = _revision(resolved) if source == "hub_snapshot" else None
    if revision_name is not None:
        origin: Literal["hub_snapshot", "local_directory"] = "hub_snapshot"
        revision = revision_name
    else:
        origin = "local_directory"
        revision = fingerprint_directory(resolved)
    return ModelIdentity(requested=requested, source=origin, local_path=str(resolved), revision=revision)


def _revision(path: Path) -> str | None:
    name = path.name
    hex_name = len(name) == 40 and all(character in "0123456789abcdef" for character in name)
    if path.parent.name == "snapshots" and hex_name:
        return name
    return None


def fingerprint_directory(path: Path) -> str:
    """Hash names, sizes, mtimes, and small metadata. Do not hash ``model.bin``."""
    lines: list[str] = []
    try:
        files = sorted(item for item in path.iterdir() if item.is_file() and not item.is_symlink())
    except OSError as exc:
        raise MediaError(f"could not fingerprint model directory {path}: {exc}") from exc
    if not files:
        raise MediaError(f"model directory {path} has no files")
    for item in files:
        try:
            stat = item.stat()
        except OSError as exc:
            raise MediaError(f"could not stat model file {item}: {exc}") from exc
        extra = ""
        if item.name in _METADATA_NAMES and stat.st_size <= _METADATA_LIMIT:
            extra = hashlib.sha256(item.read_bytes()).hexdigest()
        lines.append(f"{item.name}\t{stat.st_size}\t{stat.st_mtime_ns}\t{extra}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def model_is_cached(requested: str, root: Path) -> bool:
    """Report a cached model without creating the model root or downloading."""
    try:
        return resolve_cached_model(requested, root, create_root=False) is not None
    except MediaError:
        return False
