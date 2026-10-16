"""Private portal credentials in Linux Secret Service, never in work artifacts.

Do not use ProcessRunner here: its argv/stdout diagnostics are appropriate for
media tools, not a process whose pipes carry a password. No file fallback is
provided, even when an OS keyring is missing or locked.
"""

from __future__ import annotations

import hmac
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Literal

from clipforge.assets.mcp_client import AssetError

PORTAL_ORIGIN = "https://app.mytoolsplan.com"
_ATTRIBUTES = ("application", "clipforge", "service", "mytoolsplan-portal-v1")
_TIMEOUT_S = 15
_MAX_RECORD_BYTES = 32_768


@dataclass(frozen=True, slots=True)
class PortalCredentials:
    """In-memory secret, deliberately excluded from repr and product schemas."""

    username: str = field(repr=False)
    password: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not self.username.strip()
            or self.username != self.username.strip()
            or len(self.username) > 320
            or any(ord(char) < 32 for char in self.username)
            or not self.password.strip()
            or len(self.password) > 4096
            or any(char in self.password for char in ("\x00", "\r", "\n"))
        ):
            raise AssetError("portal credentials are empty or malformed", code="invalid_credentials")


class PortalCredentialStore:
    """One scoped keyring entry. Passwords travel through private pipes only."""

    def _execute(self, action: Literal["store", "lookup", "clear"], value: bytes | None = None) -> bytes:
        executable = shutil.which("secret-tool")
        if executable is None:
            raise AssetError(
                "Linux secret-tool is missing; install libsecret and enable an OS Secret Service",
                code="keyring_unavailable",
            )
        if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            raise AssetError(
                "the desktop session bus is unavailable; run from the logged-in desktop session",
                code="keyring_unavailable",
            )
        arguments = [executable, action]
        if action == "store":
            arguments.append("--label=Clipforge MyToolsPlan portal login")
        arguments.extend(_ATTRIBUTES)
        # Never allow libsecret's file/testing backend to turn this into a
        # plaintext-file fallback through inherited environment overrides.
        environment = dict(os.environ)
        for key in ("SECRET_BACKEND", "SECRET_FILE_TEST_PATH"):
            environment.pop(key, None)
        try:
            result = subprocess.run(
                arguments,
                input=value,
                capture_output=True,
                timeout=_TIMEOUT_S,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            # Neither a chained subprocess exception nor stderr may escape:
            # either could contain captured credential data.
            raise AssetError(
                "OS keyring did not respond; unlock the desktop keyring and retry",
                code="keyring_unavailable",
            ) from None
        if action in {"lookup", "clear"} and result.returncode == 1 and not result.stdout:
            error = result.stderr.decode("utf-8", errors="replace").casefold()
            if not error.strip() or "no such secret" in error or "not found" in error:
                return b""
        if result.returncode != 0:
            raise AssetError(
                "OS keyring operation failed; unlock the desktop keyring and retry",
                code="keyring_unavailable",
            )
        if len(result.stdout) > _MAX_RECORD_BYTES:
            raise AssetError("portal keyring record is invalid", code="invalid_credentials")
        return result.stdout

    def load(self) -> PortalCredentials | None:
        """Retrieve for a portal consumer. This does not log in or make HTTP calls."""
        raw = self._execute("lookup")
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"version", "origin", "username", "password"}
                or type(payload["version"]) is not int
                or payload["version"] != 1
                or payload["origin"] != PORTAL_ORIGIN
                or not isinstance(payload["username"], str)
                or not isinstance(payload["password"], str)
            ):
                raise ValueError
            return PortalCredentials(payload["username"], payload["password"])
        except (ValueError, UnicodeError):
            raise AssetError(
                "portal keyring record is invalid; rerun auth setup --replace",
                code="invalid_credentials",
            ) from None

    def save(self, credentials: PortalCredentials, *, replace: bool = False) -> None:
        """Store once, then verify readback. No credential file or DB row exists."""
        previous = self.load()
        if previous is not None and not replace:
            raise AssetError(
                "portal credentials are already saved; use auth setup --replace to update them",
                code="credentials_exist",
            )
        payload = json.dumps(
            {
                "version": 1,
                "origin": PORTAL_ORIGIN,
                "username": credentials.username,
                "password": credentials.password,
            },
            ensure_ascii=True,
        ).encode("utf-8")
        self._execute("store", payload)
        checked = self.load()
        if checked is None or not (
            hmac.compare_digest(checked.username.encode(), credentials.username.encode())
            and hmac.compare_digest(checked.password.encode(), credentials.password.encode())
        ):
            raise AssetError(
                "OS keyring readback did not match; credentials were not verified",
                code="keyring_write_unverified",
            )

    def forget(self) -> None:
        """Remove only Clipforge's portal credential. Not a remote logout."""
        self._execute("clear")
        if self.load() is not None:
            raise AssetError("OS keyring still contains the portal login", code="keyring_clear_unverified")


def require_portal_credentials() -> PortalCredentials:
    """Single retrieval boundary for a future audited portal downloader."""
    credentials = PortalCredentialStore().load()
    if credentials is None:
        raise AssetError(
            "portal credentials are missing; run `clipforge assets envato auth setup` in a terminal",
            code="credentials_missing",
        )
    return credentials


def credential_doctor_text() -> str:
    """Local availability only: no secret lookup, unlocking, login, or network."""
    available = shutil.which("secret-tool") is not None
    session = bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
    return "\n".join(
        (
            "credential_backend: linux-secret-service",
            f"secret_tool: {'found' if available else 'missing'}",
            f"desktop_session: {'available' if session else 'missing'}",
            "credential_lookup: not_run",
            "portal_login: not_verified",
            "portal_download: not_implemented",
            "mcp_authentication: delegated",
        )
    )


def credential_status_text() -> str:
    """Explicit protected lookup: presence is not a live authentication claim."""
    configured = PortalCredentialStore().load() is not None
    return "\n".join(
        (
            "credential_backend: linux-secret-service",
            f"credentials: {'configured' if configured else 'missing'}",
            "portal_login: not_verified",
            "portal_session: not_created",
            "portal_download: not_implemented",
            "mcp_authentication: delegated",
        )
    )
