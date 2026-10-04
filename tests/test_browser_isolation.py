"""Browser renders do not share a temp directory or leave the process group behind."""

from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.backend import RemotionHeroRenderBackend
from clipforge.media.process import ProcessResult, ProcessRunner
from clipforge.preview.isolation import browser_render_lock, chrome_socket_fits


def test_each_render_gets_a_private_temp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, object] = {}
    seen: list[str] = []

    def fake_run(self: ProcessRunner, argv: list[str], **kwargs: object) -> ProcessResult:
        del self
        recorded["argv"] = argv
        recorded["env"] = kwargs.get("env")
        recorded["reap_group"] = kwargs.get("reap_group")
        env = kwargs.get("env")
        assert isinstance(env, dict)
        private = str(env["TMPDIR"])
        seen.append(private)
        assert Path(private).is_dir()
        assert chrome_socket_fits(Path(private))
        return ProcessResult(tuple(argv), 0, "", "", 0.0, tmp_path / "render.log")

    monkeypatch.setattr(ProcessRunner, "run", fake_run)
    browser = Path("/usr/bin/google-chrome-stable")
    monkeypatch.setattr("clipforge.preview.isolation.resolve_browser", lambda: browser)
    monkeypatch.setattr("clipforge.preview.isolation.resolve_executable", lambda *_args: "node")
    batch = tmp_path / "batch.json"
    batch.write_text("{}", encoding="utf-8")
    before = os.environ.get("TMPDIR")
    RemotionHeroRenderBackend().render_batch(batch, log_path=tmp_path / "render.log")
    RemotionHeroRenderBackend().render_batch(batch, log_path=tmp_path / "render.log")
    env = recorded["env"]
    assert isinstance(env, dict)
    private = Path(str(env["TMPDIR"]))
    assert private.parent == Path("/tmp")
    assert private.name.startswith("cfb")
    assert seen[0] != seen[1]
    assert not Path(seen[0]).exists()
    assert not private.exists()
    argv = recorded["argv"]
    assert isinstance(argv, list)
    assert argv[-1] == str(private)
    assert recorded["reap_group"] is True
    assert os.environ.get("TMPDIR") == before
    script = Path("apps/renderer/scripts/render-hero.mjs").read_text(encoding="utf-8")
    assert "process.env.TMPDIR" in script
    assert 'import("@remotion/renderer")' in script


def test_long_temp_base_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    long = tmp_path / ("d" * 80)
    long.mkdir()
    monkeypatch.setattr("clipforge.preview.isolation._temp_base", lambda: long)

    def explode(*_args: object, **_kwargs: object) -> ProcessResult:
        raise AssertionError("browser render started")

    monkeypatch.setattr(ProcessRunner, "run", explode)
    batch = tmp_path / "batch.json"
    batch.write_text("{}", encoding="utf-8")
    with pytest.raises(MediaError, match="socket path"):
        RemotionHeroRenderBackend().render_batch(batch, log_path=tmp_path / "render.log")
    assert list(long.glob("cfb*")) == []


def test_browser_lock_serializes_renders() -> None:
    entered = threading.Event()
    release = threading.Event()
    second = threading.Event()

    def hold() -> None:
        with browser_render_lock():
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert entered.wait(timeout=2)

    def other() -> None:
        with browser_render_lock():
            second.set()

    waiter = threading.Thread(target=other)
    waiter.start()
    waiter.join(timeout=0.2)
    assert not second.is_set()
    release.set()
    waiter.join(timeout=2)
    thread.join(timeout=2)
    assert second.is_set()


def test_node_failure_includes_the_renderer_log() -> None:
    from clipforge.media.process import _failure_message

    message = _failure_message(
        ProcessResult(
            ("node", "render-hero.mjs"),
            1,
            "",
            "Page crashed while rendering",
            1.0,
            Path("render.log"),
        )
    )
    assert "renderer log" in message
    assert "Page crashed" in message
