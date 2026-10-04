"""Refuse promotion targets that leave the work root."""

from __future__ import annotations

from pathlib import Path

from clipforge.errors import MediaError
from clipforge.jobs.payload import JobPayloadError
from clipforge.media.workspace import ensure_within


def confine_reference(root: Path, reference: str) -> None:
    """Reject a remote, escaped, absolute, or symlinked promotion target.

    The source file itself may live outside the work root. This check is for
    outputs, manifests, and cache files that would be promoted.
    """
    text = reference.strip()
    if not text:
        raise JobPayloadError("empty promotion path")
    if "\\" in text or text.startswith("~"):
        raise JobPayloadError("backslash or home-relative promotion path")
    if ".." in text.split("/"):
        raise JobPayloadError("path traversal is not allowed")
    if "://" in text and not text.startswith("file:"):
        raise JobPayloadError("remote URL cannot be promoted")
    if text.startswith("file:"):
        from clipforge.media.local_file import path_from_file_uri

        path = path_from_file_uri(text)
    elif text.startswith("/"):
        path = Path(text)
    else:
        path = root / text
    if path.is_symlink():
        raise JobPayloadError("symlinked promotion path")
    try:
        ensure_within(root, path)
    except MediaError as exc:
        raise JobPayloadError(str(exc)) from exc
