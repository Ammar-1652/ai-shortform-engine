"""Official MediaPipe face-detector asset. Nothing downloads without an allow flag.

The file lives under ``CLIPFORGE_MODEL_ROOT/vision/face-detector``. A symlinked
model root is refused before any write. Unknown remote size fails closed.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.disk import read_disk, require_disk_budget
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import atomic_replace, ensure_within
from clipforge.vision.constants import FACE_MODEL_FILENAME, FACE_MODEL_URL

_UNKNOWN_SIZE = (
    "Clipforge could not determine the model download size, so it cannot prove "
    "the configured disk reserve will remain intact. Model download was not started."
)


@dataclass(frozen=True, slots=True)
class FaceModel:
    filename: str
    sha256: str
    source_url: str
    path: Path
    size_bytes: int


def face_model_path(root: Path) -> Path:
    return root / "vision" / "face-detector" / FACE_MODEL_FILENAME


def face_model_is_cached(root: Path) -> bool:
    """Report a cached file without creating directories or downloading."""
    if root.is_symlink() or not root.exists():
        return False
    path = face_model_path(root)
    return path.is_file() and not path.is_symlink()


def face_model_sha256(root: Path) -> str | None:
    if not face_model_is_cached(root):
        return None
    try:
        return sha256_file(face_model_path(root))
    except MediaError:
        return None


def resolve_face_model(root: Path) -> FaceModel | None:
    """Return the local model, or None when it is absent. Does not create the root."""
    if root.is_symlink():
        raise MediaError(f"model root {root} is a symlink. Refusing to follow it.")
    if not root.exists():
        return None
    path = face_model_path(root)
    if path.is_symlink():
        raise MediaError(f"refusing to follow a symlinked face model {path}")
    if not path.is_file():
        return None
    digest = sha256_file(path)
    manifest = _read_manifest(path.parent / "manifest.json")
    source = manifest.get("source_url", FACE_MODEL_URL) if manifest is not None else FACE_MODEL_URL
    if manifest is not None and manifest.get("sha256") not in {None, digest}:
        raise MediaError(
            "the face-detector manifest does not match the model file. Clipforge did not overwrite either file."
        )
    return FaceModel(
        filename=FACE_MODEL_FILENAME,
        sha256=digest,
        source_url=str(source),
        path=path,
        size_bytes=path.stat().st_size,
    )


def ensure_face_model(root: Path, *, allow_download: bool) -> FaceModel:
    """Return the local face model. Download only after ``allow_download``."""
    if root.is_symlink():
        raise MediaError(f"model root {root} is a symlink. Refusing to follow it.")
    cached = resolve_face_model(root) if root.exists() else None
    if cached is not None:
        return cached
    if not allow_download:
        raise MediaError(
            "The MediaPipe face detector model is not in the model cache. "
            "Run `clipforge vision model fetch face-detector --allow-model-download`. "
            "No model was downloaded."
        )
    expected = remote_face_model_size(FACE_MODEL_URL)
    status = read_disk(root if root.exists() else root.parent)
    require_face_download_budget(status.free_bytes, status.reserve_bytes, expected)
    destination = _prepare_model_dir(root)
    return _download(FACE_MODEL_URL, destination, expected_bytes=expected)


def remote_face_model_size(url: str) -> int | None:
    """Content-Length from a HEAD request. None when the size is not authoritative."""
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.headers.get("Content-Length")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if raw is None or not str(raw).strip().isdigit():
        return None
    value = int(str(raw).strip())
    if value < 0:
        return None
    return value


def require_face_download_budget(free_bytes: int, reserve_bytes: int, expected_bytes: int | None) -> None:
    """Refuse a download that is not proven to leave the reserve free."""
    if expected_bytes is None:
        raise MediaError(_UNKNOWN_SIZE)
    try:
        require_disk_budget(free_bytes, reserve_bytes, expected_bytes)
    except MediaError as exc:
        raise MediaError(
            f"refusing to download the face detector model. {exc} The model size is {expected_bytes} bytes."
        ) from exc


def _download(url: str, directory: Path, *, expected_bytes: int | None) -> FaceModel:
    final = directory / FACE_MODEL_FILENAME
    if final.is_symlink():
        raise MediaError(f"refusing to follow a symlinked face model {final}")
    if final.is_file():
        raise MediaError(f"{final.name} already exists and was not overwritten")
    partial = directory / f"{FACE_MODEL_FILENAME}.partial.download"
    descriptor = _open_exclusive_nofollow(partial)
    request = urllib.request.Request(url)
    try:
        with os.fdopen(descriptor, "wb") as handle, urllib.request.urlopen(request, timeout=60) as response:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                handle.write(block)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise MediaError(f"face detector download failed before the model was installed: {exc}") from exc
    size = partial.stat().st_size
    if expected_bytes is not None and size != expected_bytes:
        partial.unlink(missing_ok=True)
        raise MediaError(
            f"face detector download was {size} bytes, not the announced {expected_bytes} bytes. "
            "The model was not installed."
        )
    digest = sha256_file(partial)
    atomic_replace(partial, final, directory)
    manifest = {
        "filename": FACE_MODEL_FILENAME,
        "sha256": digest,
        "size_bytes": size,
        "source_url": url,
        "downloaded_at": datetime.now(UTC).isoformat(),
        "mediapipe_version": _mediapipe_version(),
    }
    manifest_path = directory / "manifest.json"
    partial_manifest = directory / "manifest.json.partial"
    try:
        descriptor = _open_exclusive_nofollow(partial_manifest)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        atomic_replace(partial_manifest, manifest_path, directory)
    except (OSError, MediaError) as exc:
        partial_manifest.unlink(missing_ok=True)
        if final.is_file() and not final.is_symlink():
            final.unlink()
        raise MediaError(
            f"face detector manifest was not published safely: {exc}. "
            "The newly downloaded model was removed."
        ) from exc
    return FaceModel(filename=FACE_MODEL_FILENAME, sha256=digest, source_url=url, path=final, size_bytes=size)


def _open_exclusive_nofollow(path: Path) -> int:
    """Create a new partial file without following a pre-existing symlink."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags, 0o600)
    except OSError as exc:
        raise MediaError(
            f"refusing to write model partial {path.name}: {exc}. "
            "Clipforge will not follow or overwrite an existing partial path."
        ) from exc


def _prepare_model_dir(root: Path) -> Path:
    if root.is_symlink():
        raise MediaError(f"model root {root} is a symlink. Refusing to follow it.")
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MediaError(f"could not create the model root {root}: {exc}") from exc
    if root.is_symlink():
        raise MediaError(f"model root {root} is a symlink. Refusing to follow it.")
    current = root.resolve()
    for part in ("vision", "face-detector"):
        current = current / part
        if current.is_symlink():
            raise MediaError(f"refusing to follow symlink {current} inside the model root")
        if current.exists() and not current.is_dir():
            raise MediaError(f"{current} exists and is not a directory")
        current.mkdir(exist_ok=True)
        ensure_within(root.resolve(), current)
    return current


def _read_manifest(path: Path) -> dict[str, object] | None:
    if not path.is_file() or path.is_symlink():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _mediapipe_version() -> str:
    import importlib.metadata

    try:
        return importlib.metadata.version("mediapipe")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"
