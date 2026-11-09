"""The checkpointed renderer resumes a bounded worker failure without reusing partial media."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.render_checkpoint import render_checkpointed_candidate
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import AdvancedHeroRenderInput


class CrashOnceChunkBackend:
    requires_browser = True

    def __init__(self) -> None:
        self.crash_once = True

    def render_batch(self, batch_path: Path, *, log_path: Path) -> None:
        payload = json.loads(batch_path.read_text(encoding="utf-8"))
        item = payload["items"][0]
        start, end = item["frameRange"]
        if self.crash_once and item.get("renderMode") == "video" and start == 0:
            self.crash_once = False
            raise MediaError("simulated browser crash at frame 0")
        output = Path(item["outputPath"])
        output.parent.mkdir(parents=True, exist_ok=True)
        frames = end - start + 1
        ffmpeg = resolve_ffmpeg()
        if item.get("renderMode") == "audio":
            ProcessRunner().run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=48000:cl=stereo",
                    "-t",
                    f"{frames / 30:.6f}",
                    "-ar",
                    "48000",
                    "-ac",
                    "2",
                    "-c:a",
                    "pcm_s16le",
                    str(output),
                ],
                log_path=log_path,
                check=True,
            )
        else:
            ProcessRunner().run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=0x16301a:s=1080x1920:r=30",
                    "-t",
                    f"{frames / 30:.6f}",
                    "-fps_mode",
                    "cfr",
                    "-frames:v",
                    str(frames + 1),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    str(output),
                ],
                log_path=log_path,
                check=True,
            )


def _render_input() -> AdvancedHeroRenderInput:
    digest = "a" * 64
    return AdvancedHeroRenderInput(
        candidate_id="candidate-1",
        advanced_set_id="set-1",
        duration_in_frames=125,
        reframing_strategy="contain",
        reframing_config_sha256=digest,
        profile_fingerprint=digest,
        alignment_sha256=digest,
        hero_plan_sha256=digest,
        advanced_plan_sha256=digest,
        source_sha256=digest,
    )


def test_checkpoint_records_crash_and_resumes_only_missing_units(tmp_path: Path) -> None:
    workspace = SourceWorkspace(tmp_path, "project-1", "source-1")
    run_dir = tmp_path / "run"
    (run_dir / "logs").mkdir(parents=True)
    output = run_dir / "candidates" / "candidate-1" / "advanced.mp4"
    backend = CrashOnceChunkBackend()

    with pytest.raises(MediaError, match="browser crash"):
        render_checkpointed_candidate(
            workspace=workspace,
            root=tmp_path,
            run_dir=run_dir,
            renderer=backend,
            render_input=_render_input(),
            output=output,
            dependency_sha256="b" * 64,
        )

    checkpoint_path = output.parent / "checkpoints" / "checkpoint.json"
    failed = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert failed["active_unit_id"] == "video-000000"
    assert failed["last_error_category"] == "browser_crash"
    assert failed["resume_eligibility"] == "eligible"
    assert failed["process_cleanup_status"] == "clean"
    assert failed["unit_attempts"] == {"video-000000": 1}
    assert not output.exists()

    render_checkpointed_candidate(
        workspace=workspace,
        root=tmp_path,
        run_dir=run_dir,
        renderer=backend,
        render_input=_render_input(),
        output=output,
        dependency_sha256="b" * 64,
    )

    completed = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert completed["resume_eligibility"] == "complete"
    assert completed["active_unit_id"] is None
    assert completed["last_error_category"] is None
    assert completed["process_cleanup_status"] == "clean"
    receipts = {item["unit_id"]: item for item in completed["receipts"]}
    assert receipts["video-000000"]["attempts"] == 2
    assert receipts["video-000001"]["attempts"] == 1
    assert receipts["audio"]["attempts"] == 1
    assert output.is_file() and output.stat().st_size > 0
