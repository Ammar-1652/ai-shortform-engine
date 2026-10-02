"""Streaming SHA-256. The file is never read into one buffer."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.process import MediaCancelled

_CHUNK = 1024 * 1024
_PROGRESS_EVERY = 256 * _CHUNK


def sha256_file(
    path: Path,
    *,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> str:
    """Hash ``path`` in 1 MiB chunks. ``on_progress`` receives the byte count."""
    digest = hashlib.sha256()
    done = 0
    next_report = _PROGRESS_EVERY
    try:
        handle = path.open("rb")
    except OSError as exc:
        raise MediaError(f"could not read {path} to hash it: {exc}") from exc
    with handle:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise MediaCancelled(f"hashing cancelled before {path} was finished")
            try:
                block = handle.read(_CHUNK)
            except OSError as exc:
                raise MediaError(f"could not read {path} to hash it: {exc}") from exc
            if not block:
                break
            digest.update(block)
            done += len(block)
            if on_progress is not None and done >= next_report:
                on_progress(done)
                next_report += _PROGRESS_EVERY
    return digest.hexdigest()
