"""Bounded Remotion video chunks with one continuous audio render and verified resume."""

from __future__ import annotations

import json
import wave
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.hero.advanced_backend import AdvancedRenderBackend
from clipforge.hero.backend import HeroRenderBackend
from clipforge.media.hashing import sha256_file
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import SourceWorkspace
from clipforge.paths import find_repo_root
from clipforge.schemas.advanced import AdvancedHeroRenderInput, advanced_fingerprint
from clipforge.schemas.hero import HeroRenderInput
from clipforge.schemas.render_checkpoint import CandidateRenderCheckpoint, RenderUnitReceipt
from clipforge.transcription.io import publish_json

CHUNK_FRAMES = 120


def renderer_dependency_files() -> dict[str, str]:
    """Local dependencies rechecked by the worker as well as by the service."""
    repo = find_repo_root()
    renderer = repo / "apps" / "renderer"
    files = [*renderer.joinpath("src").rglob("*.ts"), *renderer.joinpath("src").rglob("*.tsx")]
    files += list(renderer.joinpath("scripts").glob("*.mjs"))
    files += [renderer / "package.json", renderer / "pnpm-lock.yaml", Path(__file__)]
    files += [Path(__file__).with_name("caption_evidence.py")]
    files += [Path(__file__).with_name("viewer_evidence.py")]
    files += [Path(__file__).with_name("render_authorization.py")]
    files += [repo / "src/clipforge/schemas/caption_evidence.py"]
    files += [repo / "src/clipforge/schemas/qa.py"]
    files += [repo / "src/clipforge/schemas/render_checkpoint.py"]
    files += [repo / "src/clipforge/campaign/speech.py", repo / "src/clipforge/hero/captions.py"]
    files += [repo / "src/clipforge/schemas/advanced.py", repo / "src/clipforge/schemas/campaign.py"]
    return {path.relative_to(repo).as_posix(): sha256_file(path) for path in sorted(files)}


def renderer_dependency_sha256() -> str:
    """Bind renderer code and evidence recipes so stale captures cannot hit cache."""
    return advanced_fingerprint(renderer_dependency_files())


def _safe(root: Path, path: Path) -> Path:
    return confine_work_path(root, path.relative_to(root).as_posix(), label="render checkpoint")


def _probe_video(path: Path, frames: int) -> None:
    payload = read_ffprobe_json(path, ProcessRunner(), None)
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is None or (
        video.get("codec_name") != "h264"
        or video.get("width") != 1080
        or video.get("height") != 1920
        or video.get("r_frame_rate") != "30/1"
        or int(video.get("nb_frames", 0)) != frames
        or any(item.get("codec_type") == "audio" for item in streams)
    ):
        raise MediaError(f"render chunk {path.name} has invalid video/frame/audio facts")
    if abs(Fraction(str(video.get("duration", "0"))) - Fraction(frames, 30)) > Fraction(1, 30):
        raise MediaError(f"render chunk {path.name} duration does not match its owned frames")


def _probe_audio(path: Path, frames: int) -> None:
    with wave.open(str(path), "rb") as audio:
        if audio.getframerate() != 48_000 or audio.getnchannels() != 2 or audio.getsampwidth() != 2:
            raise MediaError("render audio checkpoint must be stereo PCM16 at 48000 Hz")
        if abs(audio.getnframes() - frames * 1600) > 1600:
            raise MediaError("render audio checkpoint duration differs from composition")


def render_checkpointed_candidate(
    *,
    workspace: SourceWorkspace,
    root: Path,
    run_dir: Path,
    renderer: AdvancedRenderBackend,
    render_input: AdvancedHeroRenderInput,
    output: Path,
    dependency_sha256: str,
) -> None:
    """Persist only complete validated units. Resume never trusts a filename alone.

    All chunks render their GLOBAL composition frame range. Only video is
    concatenated. Audio is collected once over the complete composition, then
    encoded once at the final mix, so chunk edges cannot introduce AAC gaps.
    Every worker is a fresh bounded browser process with concurrency one.
    """
    checkpoint_dir = _safe(root, output.parent / "checkpoints")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = _safe(root, checkpoint_dir / "checkpoint.json")
    input_sha256 = advanced_fingerprint(render_input.model_dump(mode="json"))
    frames = render_input.duration_in_frames
    if checkpoint_path.exists():
        checkpoint = CandidateRenderCheckpoint.model_validate_json(checkpoint_path.read_text(encoding="utf-8"))
        if (
            checkpoint.input_sha256 != input_sha256
            or checkpoint.dependency_sha256 != dependency_sha256
            or checkpoint.duration_in_frames != frames
            or checkpoint.chunk_frames != CHUNK_FRAMES
        ):
            raise MediaError("render checkpoint is stale: source, plan, style, font, or renderer changed")
    else:
        checkpoint = CandidateRenderCheckpoint(
            input_sha256=input_sha256,
            dependency_sha256=dependency_sha256,
            duration_in_frames=frames,
            chunk_frames=CHUNK_FRAMES,
            updated_at=datetime.now(UTC),
        )
        publish_json(checkpoint_path, checkpoint, root, workspace.partial_for(checkpoint_path))
    units = [
        (f"video-{index:06d}", start, min(start + CHUNK_FRAMES, frames))
        for index, start in enumerate(range(0, frames, CHUNK_FRAMES))
    ]
    units.append(("audio", 0, frames))
    receipts = {item.unit_id: item for item in checkpoint.receipts}
    expected_units = {unit_id for unit_id, _start, _end in units}
    unknown_units = set(receipts) - expected_units
    if unknown_units:
        raise MediaError(
            "render checkpoint contains units for a different composition: " + ", ".join(sorted(unknown_units))
        )
    for unit_id, start, end in units:
        suffix = ".wav" if unit_id == "audio" else ".mp4"
        unit = _safe(root, checkpoint_dir / f"{unit_id}{suffix}")
        receipt = receipts.get(unit_id)
        if receipt is not None:
            if (
                receipt.start_frame != start
                or receipt.end_frame_exclusive != end
                or not unit.is_file()
                or unit.stat().st_size != receipt.size_bytes
                or sha256_file(unit) != receipt.sha256
            ):
                raise MediaError(f"render checkpoint {unit_id} is missing, corrupt, or stale")
        else:
            partial = _safe(root, checkpoint_dir / f"{unit_id}.partial{suffix}")
            batch = _safe(root, run_dir / "batch.json")
            batch.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "outputPath": str(partial),
                                "h264Crf": 18,
                                "renderMode": "audio" if unit_id == "audio" else "video",
                                "frameRange": [start, end - 1],
                                "input_sha256": input_sha256,
                                "input": render_input.model_dump(mode="json"),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            # Keep one append-only renderer log for the run. The unit id is
            # present in the argv/output path and the checkpoint is the
            # authoritative per-unit receipt; the consolidated log preserves
            # the long-standing review/test path (`logs/render.log`).
            renderer.render_batch(batch, log_path=run_dir / "logs" / "render.log")
            if not partial.is_file() or partial.is_symlink():
                raise MediaError(f"render unit {unit_id} did not produce a regular output")
            if unit_id == "audio":
                _probe_audio(partial, end - start)
            else:
                _probe_video(partial, end - start)
            partial.replace(unit)
            receipt = RenderUnitReceipt(
                unit_id=unit_id,
                start_frame=start,
                end_frame_exclusive=end,
                sha256=sha256_file(unit),
                size_bytes=unit.stat().st_size,
            )
            checkpoint = checkpoint.model_copy(
                update={
                    "receipts": [*checkpoint.receipts, receipt],
                    "updated_at": datetime.now(UTC),
                }
            )
            publish_json(checkpoint_path, checkpoint, root, workspace.partial_for(checkpoint_path))
        if unit_id == "audio":
            _probe_audio(unit, end - start)
        else:
            _probe_video(unit, end - start)
    concat = _safe(root, checkpoint_dir / "video.ffconcat")
    concat.write_text(
        "ffconcat version 1.0\n"
        + "".join(f"file '{unit_id}.mp4'\n" for unit_id, _start, _end in units if unit_id != "audio"),
        encoding="utf-8",
    )
    partial_output = _safe(root, output.with_name("advanced.assembled.partial.mp4"))
    ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat),
            "-i",
            str(checkpoint_dir / "audio.wav"),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(partial_output),
        ],
        log_path=run_dir / "logs" / f"{render_input.candidate_id}-assemble.log",
        check=True,
    )
    partial_output.replace(_safe(root, output))


def render_checkpointed_hero_candidate(
    *,
    workspace: SourceWorkspace,
    root: Path,
    run_dir: Path,
    renderer: HeroRenderBackend,
    render_input: HeroRenderInput,
    output: Path,
    dependency_sha256: str,
) -> None:
    """Render a legacy Hero composition in recoverable global-frame units.

    Hero previously sent the whole composition through one Chrome session. A
    browser crash therefore discarded the complete draft. This path uses the
    same checkpoint contract as Advanced Hero: each video unit owns a global
    frame range, audio is rendered once as PCM, and the final MP4 is assembled
    only after every verified unit exists. A changed input or renderer digest
    invalidates the checkpoint instead of reusing stale frames.
    """
    checkpoint_dir = _safe(root, output.parent / "checkpoints")
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = _safe(root, checkpoint_dir / "checkpoint.json")
    input_sha256 = advanced_fingerprint(render_input.model_dump(mode="json"))
    frames = render_input.duration_in_frames
    if checkpoint_path.exists():
        checkpoint = CandidateRenderCheckpoint.model_validate_json(checkpoint_path.read_text(encoding="utf-8"))
        if (
            checkpoint.input_sha256 != input_sha256
            or checkpoint.dependency_sha256 != dependency_sha256
            or checkpoint.duration_in_frames != frames
            or checkpoint.chunk_frames != CHUNK_FRAMES
        ):
            raise MediaError("Hero render checkpoint is stale: source, plan, style, font, or renderer changed")
    else:
        checkpoint = CandidateRenderCheckpoint(
            input_sha256=input_sha256,
            dependency_sha256=dependency_sha256,
            duration_in_frames=frames,
            chunk_frames=CHUNK_FRAMES,
            updated_at=datetime.now(UTC),
        )
        publish_json(checkpoint_path, checkpoint, root, workspace.partial_for(checkpoint_path))
    units = [
        (f"video-{index:06d}", start, min(start + CHUNK_FRAMES, frames))
        for index, start in enumerate(range(0, frames, CHUNK_FRAMES))
    ]
    units.append(("audio", 0, frames))
    receipts = {item.unit_id: item for item in checkpoint.receipts}
    expected_units = {unit_id for unit_id, _start, _end in units}
    unknown_units = set(receipts) - expected_units
    if unknown_units:
        raise MediaError("Hero render checkpoint contains units for a different composition")
    for unit_id, start, end in units:
        suffix = ".wav" if unit_id == "audio" else ".mp4"
        unit = _safe(root, checkpoint_dir / f"{unit_id}{suffix}")
        receipt = receipts.get(unit_id)
        if receipt is not None:
            if (
                receipt.start_frame != start
                or receipt.end_frame_exclusive != end
                or not unit.is_file()
                or unit.stat().st_size != receipt.size_bytes
                or sha256_file(unit) != receipt.sha256
            ):
                raise MediaError(f"Hero render checkpoint {unit_id} is missing, corrupt, or stale")
        else:
            partial = _safe(root, checkpoint_dir / f"{unit_id}.partial{suffix}")
            if unit_id == "audio":
                # The staged Hero audio is already the exact trimmed source
                # clock. Do not spend another long-lived Chrome session
                # rendering an audio-only composition; converting this local
                # PCM source is deterministic and avoids a second browser
                # crash surface.
                ProcessRunner().run(
                    [
                        resolve_ffmpeg(),
                        "-y",
                        "-i",
                        render_input.audio_path,
                        "-ar",
                        "48000",
                        "-ac",
                        "2",
                        "-c:a",
                        "pcm_s16le",
                        str(partial),
                    ],
                    log_path=run_dir / "logs" / "render-audio.log",
                    check=True,
                )
            else:
                batch = _safe(root, run_dir / "render-checkpoint.json")
                batch.write_text(
                    json.dumps(
                        {
                            "items": [
                                {
                                    "outputPath": str(partial),
                                    "h264Crf": 18,
                                    "renderMode": "video",
                                    "frameRange": [start, end - 1],
                                    "input": render_input.model_dump(mode="json"),
                                }
                            ]
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
                renderer.render_batch(batch, log_path=run_dir / "logs" / "render.log")
            if not partial.is_file() or partial.is_symlink():
                raise MediaError(f"Hero render unit {unit_id} did not produce a regular output")
            if unit_id == "audio":
                _probe_audio(partial, end - start)
            else:
                _probe_video(partial, end - start)
            partial.replace(unit)
            receipt = RenderUnitReceipt(
                unit_id=unit_id,
                start_frame=start,
                end_frame_exclusive=end,
                sha256=sha256_file(unit),
                size_bytes=unit.stat().st_size,
            )
            checkpoint = checkpoint.model_copy(
                update={"receipts": [*checkpoint.receipts, receipt], "updated_at": datetime.now(UTC)}
            )
            publish_json(checkpoint_path, checkpoint, root, workspace.partial_for(checkpoint_path))
        if unit_id == "audio":
            _probe_audio(unit, end - start)
        else:
            _probe_video(unit, end - start)
    concat = _safe(root, checkpoint_dir / "video.ffconcat")
    concat.write_text(
        "ffconcat version 1.0\n"
        + "".join(f"file '{unit_id}.mp4'\n" for unit_id, _start, _end in units if unit_id != "audio"),
        encoding="utf-8",
    )
    partial_output = _safe(root, output.with_name("hero.assembled.partial.mp4"))
    ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat),
            "-i",
            str(checkpoint_dir / "audio.wav"),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(partial_output),
        ],
        log_path=run_dir / "logs" / f"{render_input.candidate_id}-assemble.log",
        check=True,
    )
    partial_output.replace(_safe(root, output))
