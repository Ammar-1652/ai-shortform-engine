"""VoiceStudio protocol checks. The server is local and fake. No live call."""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from clipforge.errors import ClipforgeError
from clipforge.voice.audio import VoiceError, wav_bytes
from clipforge.voice.plan import build_plan, render_plan
from clipforge.voice.provider import VoiceStudioProvider
from clipforge.voice.service import generate_narration, verify_narration
from tests.test_round15 import _chain, _narration


def _handler(responses: queue.Queue[tuple[int, bytes, str]]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, _format: str, *_args: object) -> None:
            return None

        def _reply(self) -> None:
            status, body, content_type = responses.get_nowait()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._reply()

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self._reply()

    return Handler


def _server(script: list[tuple[int, bytes, str]]) -> tuple[ThreadingHTTPServer, str]:
    responses: queue.Queue[tuple[int, bytes, str]] = queue.Queue()
    for item in script:
        responses.put(item)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(responses))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}"


def test_unavailable_provider_fails_closed() -> None:
    provider = VoiceStudioProvider(url="http://127.0.0.1:9", enabled=True, timeout_s=1)
    with pytest.raises(VoiceError, match="did not answer") as caught:
        provider.doctor()
    assert caught.value.code == "provider_unavailable"


def test_health_and_discovery_failures() -> None:
    bad_health, url = _server([(200, b'{"status":"down"}', "application/json")])
    try:
        provider = VoiceStudioProvider(url=url, enabled=True, timeout_s=2)
        with pytest.raises(VoiceError, match="health") as caught:
            provider.doctor()
        assert caught.value.code == "discovery_failure"
    finally:
        bad_health.shutdown()
    bad_discovery, url = _server(
        [
            (200, b'{"status":"ok"}', "application/json"),
            (200, b'{"protocol":"other"}', "application/json"),
        ]
    )
    try:
        provider = VoiceStudioProvider(url=url, enabled=True, timeout_s=2)
        with pytest.raises(VoiceError, match="discovery") as caught:
            provider.doctor()
        assert caught.value.code == "discovery_failure"
    finally:
        bad_discovery.shutdown()


def test_commercial_rights_fail_before_a_request() -> None:
    provider = VoiceStudioProvider(url="http://127.0.0.1:9", enabled=True, timeout_s=1)
    with pytest.raises(ValueError, match="CC-BY-NC"):
        _narration("Café costs $12.50 today.", model_license="cc_by_nc")
    with pytest.raises(ValueError, match="prohibited"):
        _narration("Café costs $12.50 today.", model_license="unknown")
    with pytest.raises(ClipforgeError, match="rights"):
        build_plan(
            project_id="project-1",
            source_asset_id="source-1",
            candidate_id="cand-1",
            script_text="Café costs $12.50 today.",
            language="en-US",
            enabled=True,
            operator_reason="rights check",
            provider="voicestudio",
            voice_id="expr-voice-2-f",
            engine_id="kittentts",
            model_id="k2-fsa/OmniVoice",
            model_revision="c02725660cea441db4c383af69f1f26f5cd00947",
            provider_version="0.5.7",
            model_license="allowed",
            license_evidence_id="not-commercial",
            consent_record_id="round19-kittentts-preset",
            sample_rate=24_000,
            channels=1,
        )
    assert provider.calls == 0


def test_http_errors_are_sanitized() -> None:
    secret = "bearer secret-token /home/private"
    server, url = _server([(400, json.dumps({"error": {"message": secret}}).encode(), "application/json")])
    try:
        provider = VoiceStudioProvider(url=url, enabled=True, timeout_s=2)
        with pytest.raises(VoiceError, match="status 400") as caught:
            provider.generate(_narration("Café costs $12.50 today."))
        assert "secret" not in str(caught.value)
        assert "/home/" not in str(caught.value)
        assert caught.value.code == "http_400"
    finally:
        server.shutdown()
    server, url = _server([(500, b"nope", "text/plain")])
    try:
        provider = VoiceStudioProvider(url=url, enabled=True, timeout_s=2)
        with pytest.raises(VoiceError, match="status 500") as caught:
            provider.generate(_narration("Café costs $12.50 today."))
        assert caught.value.code == "http_500"
    finally:
        server.shutdown()


def test_empty_json_and_bad_wav_fail() -> None:
    cases = [
        (200, b"", "audio/wav", "empty"),
        (200, b'{"audio":"abc"}', "application/json", "error document"),
        (200, b"not-a-wav", "audio/wav", "WAV"),
    ]
    for status, body, content_type, message in cases:
        server, url = _server([(status, body, content_type)])
        try:
            provider = VoiceStudioProvider(url=url, enabled=True, timeout_s=2)
            with pytest.raises(VoiceError, match=message):
                provider.generate(_narration("Café costs $12.50 today."))
        finally:
            server.shutdown()


def test_response_size_limit() -> None:
    server, url = _server([(200, b"x" * 32, "audio/wav")])
    try:
        provider = VoiceStudioProvider(url=url, enabled=True, timeout_s=2, max_bytes=8)
        with pytest.raises(VoiceError, match="size") as caught:
            provider.generate(_narration("Café costs $12.50 today."))
        assert caught.value.code == "response_too_large"
    finally:
        server.shutdown()


def test_successful_wav_and_cache_identity(tmp_path: Path) -> None:
    audio = wav_bytes(1_000_000, 16_000, 1)
    server, url = _server([(200, audio, "audio/wav")])
    database, work = _chain(tmp_path, evidence=False)
    try:
        provider = VoiceStudioProvider(url=url, enabled=True, timeout_s=2)
        request = _narration("Café costs $12.50 today.")
        first = generate_narration(database, work, request, provider)
        assert provider.calls == 1
        assert first.audio_sha256
        assert verify_narration(database, work, first.artifact_id).startswith("PASS")
        again = generate_narration(database, work, request, provider)
        assert again.artifact_id == first.artifact_id
        assert provider.calls == 1
        changed = request.model_copy(
            update={
                "profile": request.profile.model_copy(update={"engine_id": "other-engine"}),
            }
        )
        other_audio = wav_bytes(1_000_000, 16_000, 1)
        follow, follow_url = _server([(200, other_audio, "audio/wav")])
        changed_provider = VoiceStudioProvider(url=follow_url, enabled=True, timeout_s=2)
        second = generate_narration(database, work, changed, changed_provider)
        follow.shutdown()
        assert second.artifact_id != first.artifact_id
        path = work / "voice" / "audio" / f"{first.artifact_id}.wav"
        path.unlink()
        link = path
        link.symlink_to(path.with_name("missing.wav"))
        with pytest.raises(VoiceError, match="missing"):
            verify_narration(database, work, first.artifact_id)
    finally:
        server.shutdown()


def test_unknown_engine_does_not_call_the_service() -> None:
    provider = VoiceStudioProvider(url="http://127.0.0.1:9", enabled=True, timeout_s=1)
    request = _narration("Café costs $12.50 today.")
    request = request.model_copy(
        update={"profile": request.profile.model_copy(update={"engine_id": "bad engine"})}
    )
    with pytest.raises(VoiceError, match="engine") as caught:
        provider.generate(request)
    assert caught.value.code == "unknown_engine"
    assert provider.calls == 0


def test_render_plan_does_not_call_a_disabled_provider(tmp_path: Path) -> None:
    database, work = _chain(tmp_path)
    provider = VoiceStudioProvider(enabled=False)
    plan = build_plan(
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="cand-1",
        script_text="Café costs $12.50 today.",
        language="en-US",
        enabled=False,
        operator_reason="leave narration off",
    )
    held = render_plan(database, work, plan, provider, script_text="Café costs $12.50 today.")
    assert held.enabled is False
    assert provider.calls == 0
