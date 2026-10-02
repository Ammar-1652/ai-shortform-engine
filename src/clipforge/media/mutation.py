"""Detect a referenced source whose bytes no longer match the stored SHA-256."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.schemas.ingest import SourceIngestManifest


@dataclass(frozen=True, slots=True)
class StatDrift:
    """Size or mtime changed, and a rehash showed the same content."""

    size_bytes: int
    mtime_ns: int


def inspect_mutation(path: Path, manifest: SourceIngestManifest) -> StatDrift | None:
    """Return stat drift, or None when size and mtime still match.

    A different SHA-256 raises. The stored digest is not updated by this function.
    """
    if not path.is_file():
        raise MediaError(
            "FAIL: registered source file is missing. "
            f"Expected {path}. The original is referenced in place and was not copied. "
            "Restore the file or ingest the replacement as a new source."
        )
    try:
        stat = path.stat()
    except OSError as exc:
        raise MediaError(f"could not stat the registered source {path}: {exc}") from exc
    if stat.st_size == manifest.size_bytes and stat.st_mtime_ns == manifest.mtime_ns:
        return None
    digest = sha256_file(path)
    if digest != manifest.content_sha256:
        raise MediaError(
            "FAIL: source file changed since ingest. "
            "The registered source content changed and must be ingested as a new source. "
            "The stored digest was not updated."
        )
    return StatDrift(size_bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
