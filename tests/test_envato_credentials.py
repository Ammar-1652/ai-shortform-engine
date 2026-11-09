"""OS-keyring credential boundary tests. No real keyring or portal is contacted."""

from __future__ import annotations

import subprocess

import pytest

from clipforge.assets.credentials import PortalCredentials, PortalCredentialStore
from clipforge.assets.mcp_client import AssetError


def test_keyring_round_trip_never_uses_a_file(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = b""
    calls: list[tuple[list[str], bytes | None]] = []

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/test-bus")
    monkeypatch.setattr("clipforge.assets.credentials.shutil.which", lambda name: "/usr/bin/secret-tool")

    def run(argv: list[str], *, input: bytes | None, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal stored
        del kwargs
        action = argv[1]
        calls.append((argv, input))
        if action == "store":
            stored = input or b""
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        if action == "lookup":
            return subprocess.CompletedProcess(argv, 0, stored, b"")
        stored = b""
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr("clipforge.assets.credentials.subprocess.run", run)
    credentials = PortalCredentials("user@example.test", "secret-value")
    store = PortalCredentialStore()
    store.save(credentials)
    assert store.load() == credentials
    assert calls[0][0][1] == "lookup"
    assert all(argv[1] in {"lookup", "store"} for argv, _ in calls)
    assert all("secret-value" not in argv for argv, _ in calls)


def test_keyring_errors_are_not_relabelled_as_bad_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/tmp/test-bus")
    monkeypatch.setattr("clipforge.assets.credentials.shutil.which", lambda name: "/usr/bin/secret-tool")

    def fail(*args: object, **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        del args, kwargs
        return subprocess.CompletedProcess(["secret-tool"], 1, b"", b"locked")

    monkeypatch.setattr("clipforge.assets.credentials.subprocess.run", fail)
    with pytest.raises(AssetError, match="OS keyring operation failed") as caught:
        PortalCredentialStore().load()
    assert caught.value.code == "keyring_unavailable"


def test_credentials_reject_newline_and_repr_is_redacted() -> None:
    with pytest.raises(AssetError, match="malformed"):
        PortalCredentials("user@example.test", "secret\nvalue")
    assert "secret-value" not in repr(PortalCredentials("user@example.test", "secret-value"))
