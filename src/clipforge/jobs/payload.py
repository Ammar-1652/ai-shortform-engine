"""Public job payloads. Identifiers and hashes only."""

from __future__ import annotations

from clipforge.errors import ClipforgeError

_HIDDEN = ("path", "uri", "home", "token", "secret", "password", "env", "command", "argv")


class JobPayloadError(ClipforgeError):
    """A job payload is not safe to store or show."""


def assert_public_payload(payload: dict[str, str]) -> None:
    """Reject absolute paths, URLs, and secret-like fields before they are stored."""
    for key, value in payload.items():
        lowered = key.lower()
        if any(part in lowered for part in _HIDDEN):
            raise JobPayloadError(f"job payload field {key} is not public")
        if _looks_secret(value):
            raise JobPayloadError(f"job payload field {key} contains a local path or secret")


def public_payload(payload: dict[str, str]) -> dict[str, str]:
    """Return the fields that are safe to print."""
    visible: dict[str, str] = {}
    for key, value in sorted(payload.items()):
        lowered = key.lower()
        if any(part in lowered for part in _HIDDEN) or _looks_secret(value):
            continue
        visible[key] = value
    return visible


def _looks_secret(value: str) -> bool:
    stripped = value.strip()
    return (
        stripped.startswith("/")
        or stripped.startswith("~")
        or stripped.startswith("\\")
        or stripped.startswith("file:")
        or "\\" in stripped
        or ".." in stripped.split("/")
        or "://" in stripped
        or "/tmp/" in stripped
        or "/home/" in stripped
        or "/Users/" in stripped
    )
