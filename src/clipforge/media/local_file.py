"""Accept a readable local regular file. Reject remote URLs and directories."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from clipforge.errors import MediaError

_HOST_PREFIXES = (
    "www.",
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "drive.google.com",
)


def require_local_media_file(raw: str) -> Path:
    """Resolve ``raw`` to a readable file. The returned path is absolute."""
    text = raw.strip()
    if not text:
        raise MediaError("source path is empty. Pass a local video file.")
    if _looks_remote(text):
        raise MediaError(
            "source ingest accepts a local file path only. "
            f"Rejected {text!r}. Remote URLs, including YouTube, TikTok, Instagram, "
            "Google Drive, s3, and http, are not downloaded."
        )
    path = Path(text).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise MediaError(f"could not resolve source path {text!r}: {exc}") from exc
    if not resolved.exists():
        raise MediaError(f"source file does not exist: {resolved}")
    if resolved.is_dir():
        raise MediaError(f"source path is a directory, not a video file: {resolved}")
    if not resolved.is_file():
        raise MediaError(f"source path is not a regular file: {resolved}")
    if not os.access(resolved, os.R_OK):
        raise MediaError(f"source file is not readable: {resolved}")
    return resolved


def path_to_file_uri(path: Path) -> str:
    return path.resolve().as_uri()


def path_from_file_uri(uri: str) -> Path:
    if uri.startswith("file:"):
        parsed = urlparse(uri)
        return Path(unquote(parsed.path))
    return Path(uri)


def normalize_evidence_reference(raw: str) -> str:
    """Record a local evidence file or an http(s) reference. Do not download it."""
    text = raw.strip()
    if not text:
        raise MediaError(
            "rights evidence is required. Pass --rights-evidence with a local file "
            "or an http(s) reference. Editorial use stays blocked without it."
        )
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        return text
    if "://" in text:
        raise MediaError(
            "rights evidence must be a local file or an http(s) reference. "
            f"Rejected {text!r}. Nothing was downloaded."
        )
    path = Path(text).expanduser()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise MediaError(f"could not resolve rights evidence path {text!r}: {exc}") from exc
    if not resolved.is_file():
        raise MediaError(f"rights evidence file does not exist: {resolved}")
    if not os.access(resolved, os.R_OK):
        raise MediaError(f"rights evidence file is not readable: {resolved}")
    return resolved.as_uri()


def _looks_remote(text: str) -> bool:
    lowered = text.lower()
    if "://" in text:
        return True
    return lowered.startswith(_HOST_PREFIXES)
