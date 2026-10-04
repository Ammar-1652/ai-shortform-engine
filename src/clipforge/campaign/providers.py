"""Source and campaign discovery providers. Live sessions stay opt-in."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.request import Request, urlopen

from clipforge.campaign.antoine import CAMPAIGN_ID, FILES, DriveFile, file_by_id, selected_files
from clipforge.errors import ClipforgeError

_MAX_BYTES = 200_000_000
_DRIVE_FLAG = "CLIPFORGE_DRIVE_ACQUIRE"
_WHOP_FLAG = "CLIPFORGE_WHOP_LIVE"


class CampaignError(ClipforgeError):
    """A campaign operation failed closed."""

    def __init__(self, message: str, *, code: str = "campaign_error") -> None:
        super().__init__(message)
        self.code = code


class CampaignSourceProvider(Protocol):
    """Fetch only an explicitly selected source. This does not publish."""

    def doctor(self) -> str:
        """Report whether a download can run."""

    def plan(self) -> list[DriveFile]:
        """Return the catalogue. Planning does not download."""

    def acquire(self, source_id: str, destination: Path) -> str:
        """Download one selected file. Return acquired or provider_unavailable."""


class CampaignDiscoveryProvider(Protocol):
    """List campaigns the operator already authorized. No password collection."""

    def doctor(self) -> str:
        """Report whether a live session is enabled."""

    def discover(self) -> list[dict[str, str]]:
        """Return public campaign ids and titles."""


@dataclass
class FakeSourceProvider:
    """Deterministic bytes for tests. No network."""

    calls: int = 0
    payload: bytes = b"antoine-source"

    def doctor(self) -> str:
        return "provider: fake\nnetwork: none"

    def plan(self) -> list[DriveFile]:
        return list(FILES)

    def acquire(self, source_id: str, destination: Path) -> str:
        self.calls += 1
        item = file_by_id(source_id)
        if item is None or not item.selected:
            raise CampaignError("source is not selected for round 18", code="not_selected_for_round_18")
        _refuse_links(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.payload)
        return "acquired"


@dataclass
class DryRunSourceProvider:
    """Validate the selection and write nothing."""

    calls: int = 0

    def doctor(self) -> str:
        return "provider: dry_run\nnetwork: none"

    def plan(self) -> list[DriveFile]:
        return list(FILES)

    def acquire(self, source_id: str, destination: Path) -> str:
        del destination
        self.calls += 1
        item = file_by_id(source_id)
        if item is None or not item.selected:
            raise CampaignError("source is not selected for round 18", code="not_selected_for_round_18")
        return "planned"


@dataclass
class GoogleDriveSourceProvider:
    """Download two explicit files when the operator sets the acquire flag."""

    calls: int = 0
    timeout_s: float = 120
    opener: object | None = None

    def doctor(self) -> str:
        enabled = os.environ.get(_DRIVE_FLAG, "").strip() == "1"
        state = "enabled" if enabled else "provider_unavailable"
        return f"provider: google_drive\nacquire: {state}"

    def plan(self) -> list[DriveFile]:
        return list(FILES)

    def acquire(self, source_id: str, destination: Path) -> str:
        self.calls += 1
        item = file_by_id(source_id)
        if item is None or not item.selected:
            raise CampaignError("source is not selected for round 18", code="not_selected_for_round_18")
        if item.size_bytes >= _MAX_BYTES:
            raise CampaignError("selected source is not below 200 MB", code="source_too_large")
        if os.environ.get(_DRIVE_FLAG, "").strip() != "1":
            return "provider_unavailable"
        _refuse_links(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".partial")
        _refuse_links(partial)
        try:
            _download_drive(item.drive_id, partial, timeout_s=self.timeout_s, opener=self.opener)
        except CampaignError:
            partial.unlink(missing_ok=True)
            raise
        size = partial.stat().st_size
        if size >= _MAX_BYTES or size != item.size_bytes:
            partial.unlink(missing_ok=True)
            raise CampaignError("downloaded size does not match the catalogue", code="size_mismatch")
        partial.replace(destination)
        return "acquired"


def _download_drive(drive_id: str, destination: Path, *, timeout_s: float, opener: object | None) -> None:
    url = f"https://drive.google.com/uc?export=download&id={drive_id}"
    request = Request(url, headers={"User-Agent": "clipforge-campaign"})
    open_url = opener or urlopen
    try:
        with open_url(request, timeout=timeout_s) as response:  # type: ignore[operator]
            content_type = response.headers.get("Content-Type", "")
            payload = response.read(_MAX_BYTES + 1)
    except CampaignError:
        raise
    except Exception as exc:
        raise CampaignError("drive provider is unavailable", code="provider_unavailable") from exc
    if "text/html" in content_type.lower():
        raise CampaignError("drive returned a confirmation page", code="provider_unavailable")
    if len(payload) >= _MAX_BYTES:
        raise CampaignError("download exceeded 200 MB", code="source_too_large")
    destination.write_bytes(payload)


def _refuse_links(path: Path) -> None:
    cursor = path
    while True:
        if cursor.is_symlink():
            raise CampaignError("refusing a symlink in the acquisition path", code="symlink")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent


@dataclass
class FakeCampaignDiscoveryProvider:
    """A fixed public catalogue. No browser and no credentials."""

    calls: int = 0
    rows: list[dict[str, str]] = field(default_factory=list)

    def doctor(self) -> str:
        return "discovery: fake\nnetwork: none\ncredentials: not stored"

    def discover(self) -> list[dict[str, str]]:
        self.calls += 1
        if self.rows:
            return list(self.rows)
        return [
            {
                "campaign_id": CAMPAIGN_ID,
                "title": "Antoine Sallis Clipping",
                "result": "discovered",
                "error_code": "none",
            }
        ]


@dataclass
class DryRunCampaignDiscoveryProvider:
    """Show that discovery would be explicit. It does not open a session."""

    calls: int = 0

    def doctor(self) -> str:
        return "discovery: dry_run\nlive_whop: not_configured\ncredentials: not stored"

    def discover(self) -> list[dict[str, str]]:
        self.calls += 1
        return []


class WhopCampaignProvider:
    """A live Whop pass needs an already-authorized session. CI never enables it."""

    def doctor(self) -> str:
        if os.environ.get(_WHOP_FLAG, "").strip() == "1":
            return "discovery: whop\nlive: enabled\nsession: not supplied"
        return "discovery: whop\nlive: not_configured\ncredentials: not stored"

    def discover(self) -> list[dict[str, str]]:
        if os.environ.get(_WHOP_FLAG, "").strip() != "1":
            raise CampaignError("whop discovery is not configured", code="not_configured")
        raise CampaignError("authorized browser session was not supplied", code="provider_unavailable")


def selected_source_ids() -> list[str]:
    return [item.source_id for item in selected_files()]
