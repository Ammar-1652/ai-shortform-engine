"""Publishers. Fake and dry-run implementations never open a socket."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from clipforge.schemas.publish import PublishAttempt, PublishReceipt, PublishRequest


class Publisher(Protocol):
    def doctor(self) -> str:
        """Report whether this adapter can upload."""

    def capabilities(self) -> dict[str, object]:
        """Declare platforms, privacy modes, and whether scheduling is supported."""

    def validate(self, request: PublishRequest) -> None:
        """Reject a request this adapter cannot represent."""

    def dry_run(self, request: PublishRequest) -> PublishRequest:
        """Return the request that would be sent. Do not contact a platform."""

    def submit(self, request: PublishRequest) -> PublishReceipt | None:
        """Ask the provider to accept the package. None means no verified receipt."""

    def status(self, attempt: PublishAttempt) -> str:
        """Read a prior attempt. This must not submit again."""

    def cancel(self, attempt: PublishAttempt) -> str:
        """Stop an attempt. Cancellation is not success."""


@dataclass
class FakePublisher:
    """Deterministic stand-in. ``mode`` selects the fixture. No network."""

    mode: str = "success"
    calls: int = 0

    def doctor(self) -> str:
        return "platform_adapter: available\nexternal_upload: not_configured"

    def capabilities(self) -> dict[str, object]:
        return {
            "platforms": ["fake"],
            "privacy": ["public"],
            "scheduling": False,
            "network": False,
        }

    def validate(self, request: PublishRequest) -> None:
        if request.target.platform != "fake":
            raise ValueError("unknown platform")
        if request.target.scheduled_at is not None:
            raise ValueError("unsupported scheduling")
        if request.target.privacy != "public":
            raise ValueError("unsupported privacy")

    def dry_run(self, request: PublishRequest) -> PublishRequest:
        self.validate(request)
        self.calls += 1
        return request

    def submit(self, request: PublishRequest) -> PublishReceipt | None:
        self.validate(request)
        self.calls += 1
        if self.mode == "timeout":
            raise TimeoutError("provider timed out")
        if self.mode == "reject":
            raise ValueError("provider rejected the package")
        if self.mode == "malformed":
            return None
        if self.mode == "secret":
            raise ValueError("bearer secret-token")
        if self.mode == "cancel":
            raise ValueError("provider cancelled the attempt")
        return PublishReceipt(
            platform="fake",
            remote_item_id="item-1",
            public_url="https://example.invalid/v/item-1",
            manifest_sha256=request.manifest_sha256,
            submitted_at=request.created_at,
            provider_version="fake-1",
            status="published",
        )

    def status(self, attempt: PublishAttempt) -> str:
        self.calls += 1
        return attempt.state

    def cancel(self, attempt: PublishAttempt) -> str:
        del attempt
        self.calls += 1
        return "cancelled"


@dataclass
class DryRunPublisher:
    """Validate the request and stop. This class does not upload."""

    calls: int = 0

    def doctor(self) -> str:
        return "platform_adapter: available\nexternal_upload: not_configured"

    def capabilities(self) -> dict[str, object]:
        return {
            "platforms": ["fake"],
            "privacy": ["public"],
            "scheduling": False,
            "network": False,
        }

    def validate(self, request: PublishRequest) -> None:
        FakePublisher().validate(request)

    def dry_run(self, request: PublishRequest) -> PublishRequest:
        self.validate(request)
        self.calls += 1
        return request

    def submit(self, request: PublishRequest) -> PublishReceipt | None:
        del request
        raise ValueError("dry-run publisher cannot submit")

    def status(self, attempt: PublishAttempt) -> str:
        self.calls += 1
        return attempt.state

    def cancel(self, attempt: PublishAttempt) -> str:
        del attempt
        self.calls += 1
        return "cancelled"


def live_upload_enabled() -> bool:
    """Real uploads stay off unless the operator sets the live-smoke flag."""
    return os.environ.get("CLIPFORGE_PLATFORM_LIVE_SMOKE", "").strip() == "1"


def adapter_status() -> str:
    if live_upload_enabled() and os.environ.get("CLIPFORGE_PLATFORM_ID", "").strip():
        return "external_upload: not_run"
    return "platform_adapter: available\nexternal_upload: not_configured"
