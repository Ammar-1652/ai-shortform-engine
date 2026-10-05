"""Local narration providers. The live provider is off unless the operator enables it."""

from __future__ import annotations

import json
import os
import re
from typing import Protocol
from urllib.parse import urlsplit

from clipforge.schemas.voice import NarrationRequest
from clipforge.voice.audio import VoiceError, wav_bytes

_LOOPBACK = "127.0.0.1"
_ENGINE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,40}$")
_DEFAULT_MAX_BYTES = 20_000_000


class VoiceProvider(Protocol):
    """A narration engine. Implementations must not approve a Hero."""

    def doctor(self) -> str:
        """Report whether this provider is required and reachable."""

    def capabilities(self) -> dict[str, str]:
        """Return a small public description. No waveforms."""

    def generate(self, request: NarrationRequest) -> bytes:
        """Return WAV bytes. This does not write a Clipforge artifact."""

    def verify_audio(self, payload: bytes) -> None:
        """Reject audio that is empty or not PCM WAV."""


class FakeVoiceProvider:
    """Deterministic silence. Tests use this. It does not open a network connection."""

    provider_id = "fake"

    def __init__(self) -> None:
        self.calls = 0

    def doctor(self) -> str:
        return "PASS voice: fake provider"

    def capabilities(self) -> dict[str, str]:
        return {"provider": "fake", "format": "wav", "network": "none"}

    def generate(self, request: NarrationRequest) -> bytes:
        self.calls += 1
        return wav_bytes(request.target_duration_us, request.sample_rate, request.channels)

    def verify_audio(self, payload: bytes) -> None:
        from clipforge.voice.audio import parse_wav

        parse_wav(payload)


class VoiceStudioProvider:
    """HTTP client for a local VoiceStudio process. Models are not downloaded."""

    provider_id = "voicestudio"

    def __init__(
        self,
        *,
        url: str = "http://127.0.0.1:3900",
        enabled: bool = False,
        timeout_s: float = 300,
        allow_remote: bool = False,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self.url = url.rstrip("/")
        self.enabled = enabled
        self.timeout_s = timeout_s
        self.allow_remote = allow_remote
        self.max_bytes = max_bytes
        self.calls = 0
        self.service_version = ""
        self.capability_names = ""
        self.engine_summary = ""

    def doctor(self) -> str:
        if not self.enabled:
            return "PASS voice: provider disabled; health: not_called; capabilities: not_called"
        self._require_endpoint()
        health = self._get("/health")
        status = health.get("status") if isinstance(health, dict) else None
        if status != "ok":
            raise VoiceError(
                "VoiceStudio health or discovery protocol was not recognized",
                code="discovery_failure",
            )
        document = self._get("/.well-known/voicestudio-speech")
        protocol = document.get("protocol") if isinstance(document, dict) else None
        version = document.get("service_version") if isinstance(document, dict) else None
        endpoints = document.get("endpoints") if isinstance(document, dict) else None
        if protocol != "voicestudio.speech.v1":
            raise VoiceError(
                "VoiceStudio health or discovery protocol was not recognized",
                code="discovery_failure",
            )
        if not isinstance(version, str) or not version or len(version) > 40:
            raise VoiceError("VoiceStudio service version was not recognized", code="discovery_failure")
        names = sorted(endpoints) if isinstance(endpoints, dict) else []
        if not names or any(not isinstance(name, str) for name in names):
            raise VoiceError("VoiceStudio capabilities were not recognized", code="discovery_failure")
        self.service_version = version
        self.capability_names = ",".join(names)
        return (
            "PASS voice: local endpoint answered; "
            f"health: ok; protocol: {protocol}; service_version: {version}; "
            f"capabilities: {self.capability_names}"
        )

    def capabilities(self) -> dict[str, str]:
        if not self.enabled:
            return {"provider": "voicestudio", "enabled": "0", "network": "none"}
        self.doctor()
        catalogue = self._get("/engines")
        self.engine_summary = _engine_summary(catalogue)
        return {
            "provider": "voicestudio",
            "enabled": "1",
            "network": "loopback",
            "protocol": "voicestudio.speech.v1",
            "service_version": self.service_version,
            "capabilities": self.capability_names,
            "engines": self.engine_summary,
        }

    def generate(self, request: NarrationRequest) -> bytes:
        if not self.enabled:
            raise VoiceError("VoiceStudio is disabled", code="provider_disabled")
        self._reject_rights(request)
        self._require_endpoint()
        if not _ENGINE_NAME.fullmatch(request.profile.engine_id):
            raise VoiceError("VoiceStudio engine id was not recognized", code="unknown_engine")
        if not _ENGINE_NAME.fullmatch(request.voice_profile_id):
            raise VoiceError("VoiceStudio voice id was not recognized", code="unknown_voice")
        self.calls += 1
        language = request.language.split("-", 1)[0]
        body = json.dumps(
            {
                "model": request.profile.engine_id,
                "voice": request.voice_profile_id,
                "input": request.script_text,
                "language": language,
                "response_format": "wav",
            }
        ).encode("utf-8")
        payload, content_type = self._post("/v1/audio/speech", body)
        if not payload:
            raise VoiceError("VoiceStudio returned an empty response", code="empty_response")
        if payload.startswith(b"{") or "json" in content_type.lower():
            raise VoiceError("VoiceStudio returned an error document instead of audio", code="json_body")
        self.verify_audio(payload)
        return payload

    def _reject_rights(self, request: NarrationRequest) -> None:
        license_state = request.profile.model_license
        commercial = request.profile.commercial_use
        if license_state in {"unknown", "prohibited"} or commercial in {"unknown", "prohibited"}:
            raise VoiceError("narration model rights are not allowed", code="license_blocked")
        blocked_family = request.profile.model_id.lower().startswith("k2-fsa/")
        if request.output_use == "commercial" and (
            license_state != "allowed" or commercial != "allowed" or blocked_family
        ):
            raise VoiceError("narration model rights are not allowed", code="license_blocked")

    def verify_audio(self, payload: bytes) -> None:
        from clipforge.voice.audio import parse_wav

        if not payload:
            raise VoiceError("narration audio is empty")
        parse_wav(payload)

    def _require_endpoint(self) -> None:
        if self.timeout_s <= 0 or self.timeout_s > 3600:
            raise VoiceError("VoiceStudio timeout is not usable")
        parts = urlsplit(self.url)
        host = parts.hostname or ""
        if parts.username or parts.password or parts.query or "@" in self.url:
            raise VoiceError("VoiceStudio endpoint must not carry a secret")
        if host == _LOOPBACK and parts.scheme == "http":
            return
        if self.allow_remote and parts.scheme == "https" and host and host != _LOOPBACK:
            return
        raise VoiceError("VoiceStudio endpoint must be loopback HTTP or an explicitly allowed HTTPS host")

    def _get(self, path: str) -> object:
        raw, _content_type = self._request("GET", path, None)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise VoiceError("VoiceStudio discovery document was not JSON") from exc

    def _post(self, path: str, body: bytes) -> tuple[bytes, str]:
        return self._request("POST", path, body)

    def _request(self, method: str, path: str, body: bytes | None) -> tuple[bytes, str]:
        import http.client

        parts = urlsplit(self.url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        connection: http.client.HTTPConnection
        if parts.scheme == "https":
            connection = http.client.HTTPSConnection(parts.hostname or "", port, timeout=self.timeout_s)
        else:
            connection = http.client.HTTPConnection(parts.hostname or "", port, timeout=self.timeout_s)
        try:
            headers = {"Accept": "application/json, audio/wav"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read(self.max_bytes + 1)
            content_type = response.headers.get("Content-Type", "")
            status = response.status
        except TimeoutError as exc:
            raise VoiceError("VoiceStudio timed out", code="timeout") from exc
        except OSError as exc:
            raise VoiceError("VoiceStudio did not answer", code="provider_unavailable") from exc
        finally:
            connection.close()
        if len(payload) > self.max_bytes:
            raise VoiceError("VoiceStudio response exceeded the size limit", code="response_too_large")
        if status >= 400:
            raise VoiceError(_sanitized_http_error(status, payload), code=f"http_{status}")
        return payload, content_type


def provider_from_env() -> VoiceStudioProvider:
    """Read the operator's local endpoint. The default is disabled."""
    enabled = os.environ.get("CLIPFORGE_VOICESTUDIO_ENABLED", "0") == "1"
    url = os.environ.get("CLIPFORGE_VOICESTUDIO_URL", "http://127.0.0.1:3900")
    try:
        timeout = float(os.environ.get("CLIPFORGE_VOICESTUDIO_TIMEOUT_S", "300"))
    except ValueError as exc:
        raise VoiceError("VoiceStudio timeout is not a number") from exc
    allow_remote = os.environ.get("CLIPFORGE_VOICESTUDIO_ALLOW_REMOTE", "0") == "1"
    try:
        max_bytes = int(os.environ.get("CLIPFORGE_VOICESTUDIO_MAX_BYTES", str(_DEFAULT_MAX_BYTES)))
    except ValueError as exc:
        raise VoiceError("VoiceStudio size limit is not a number") from exc
    return VoiceStudioProvider(
        url=url,
        enabled=enabled,
        timeout_s=timeout,
        allow_remote=allow_remote,
        max_bytes=max_bytes,
    )


def _engine_summary(document: object) -> str:
    if not isinstance(document, dict):
        raise VoiceError("VoiceStudio engine catalogue was not recognized", code="discovery_failure")
    family = document.get("tts")
    if not isinstance(family, dict):
        raise VoiceError("VoiceStudio engine catalogue was not recognized", code="discovery_failure")
    backends = family.get("backends")
    if not isinstance(backends, list) or not backends:
        raise VoiceError("VoiceStudio engine catalogue was not recognized", code="discovery_failure")
    parts: list[str] = []
    for item in backends:
        if not isinstance(item, dict):
            continue
        name = item.get("id")
        if not isinstance(name, str) or _ENGINE_NAME.fullmatch(name) is None:
            continue
        rate = item.get("output_sample_rate")
        channels = item.get("output_channels")
        cloning = item.get("supports_cloning")
        if isinstance(rate, bool) or isinstance(channels, bool):
            continue
        if not isinstance(rate, int) or not isinstance(channels, int):
            parts.append(name)
            continue
        kind = "clone" if cloning is True else "preset"
        parts.append(f"{name}:{rate}:{channels}:{kind}")
    if not parts:
        raise VoiceError("VoiceStudio engine catalogue was not recognized", code="discovery_failure")
    return ",".join(parts)


def _sanitized_http_error(status: int, payload: bytes) -> str:
    """A short public message. Paths, tokens, and long bodies stay out."""
    text = ""
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        document = None
    if isinstance(document, dict):
        error = document.get("error")
        detail = document.get("detail")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            text = error["message"]
        elif isinstance(detail, str):
            text = detail
    lowered = text.lower()
    if (
        not text
        or len(text) > 180
        or any(token in lowered for token in ("/home/", "/tmp/", "/users/", "bearer ", "token=", "://"))
    ):
        return f"VoiceStudio rejected the request with status {status}"
    return f"VoiceStudio rejected the request with status {status}: {text}"
