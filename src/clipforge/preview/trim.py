"""Trim one candidate span out of a long proxy. Remotion then starts at frame 0.

The canonical start and end stay on the TimeMap. This file re-encodes a bounded
clip so a non-keyframe start does not require seeking through the whole source.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.clock import seconds_text_to_us, us_to_seconds_str
from clipforge.media.hashing import sha256_file
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg, resolve_ffprobe
from clipforge.media.workspace import ensure_within
from clipforge.preview.constants import DURATION_TOLERANCE_US

# Enough to land on a prior keyframe for a typical long-GOP H.264 proxy.
_KEYFRAME_PAD_US = 10_000_000
_NAME = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,78}$"


@dataclass(frozen=True, slots=True)
class StagedSpan:
    video_path: Path
    audio_path: Path
    video_sha256: str
    audio_sha256: str
    duration_us: int
    ffmpeg_version: str
    source_start_us: int
    source_end_us: int


def stage_candidate_span(
    video: Path,
    audio: Path,
    staging: Path,
    *,
    stem: str,
    start_us: int,
    end_us: int,
    frame_count: int,
    root: Path,
    log_path: Path | None,
) -> StagedSpan:
    """Write a short H.264/FLAC pair. The caller deletes ``staging`` later."""
    if end_us <= start_us or frame_count < 1:
        raise MediaError("candidate span must have a positive duration")
    if not _safe_name(f"{stem}.mp4") or not _safe_name(f"{stem}.flac"):
        raise MediaError("candidate staging name is not safe")
    _require_local(video, root)
    _require_local(audio, root)
    ensure_within(root, staging)
    if staging.is_symlink():
        raise MediaError("refusing to stage into a symlink")
    staging.mkdir(parents=True, exist_ok=True)
    destination_video = staging / f"{stem}.mp4"
    destination_audio = staging / f"{stem}.flac"
    for path in (destination_video, destination_audio):
        ensure_within(root, path)
        if path.exists() or path.is_symlink():
            raise MediaError(f"refusing to replace staged media {path.name}")
    ffmpeg = resolve_ffmpeg()
    runner = ProcessRunner()
    version = _ffmpeg_version(ffmpeg, runner)
    pad = min(_KEYFRAME_PAD_US, start_us)
    fast = start_us - pad
    duration_us = end_us - start_us
    recipe = {
        "start_us": start_us,
        "end_us": end_us,
        "pad_us": pad,
        "frame_count": frame_count,
        "ffmpeg_version": version,
        "video_codec": "h264",
        "audio_codec": "flac",
        "output_fps": "30/1",
    }
    runner.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            us_to_seconds_str(fast),
            "-i",
            str(video),
            "-ss",
            us_to_seconds_str(pad),
            "-map",
            "0:v:0",
            "-an",
            "-frames:v",
            str(frame_count),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-fps_mode",
            "cfr",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            str(destination_video),
        ],
        log_path=log_path,
        check=True,
    )
    runner.run(
        [
            ffmpeg,
            "-y",
            "-ss",
            us_to_seconds_str(fast),
            "-i",
            str(audio),
            "-ss",
            us_to_seconds_str(pad),
            "-t",
            us_to_seconds_str(duration_us),
            "-vn",
            "-c:a",
            "flac",
            str(destination_audio),
        ],
        log_path=log_path,
        check=True,
    )
    measured = _duration_us(destination_video, runner, log_path)
    error = measured - duration_us
    if abs(error) > DURATION_TOLERANCE_US:
        raise MediaError(
            f"staged clip duration {measured} us differs from the candidate span {duration_us} us by {error} us"
        )
    recipe_path = staging / f"{stem}.recipe.json"
    ensure_within(root, recipe_path)
    recipe_path.write_text(json.dumps(recipe, sort_keys=True) + "\n", encoding="utf-8")
    return StagedSpan(
        video_path=destination_video,
        audio_path=destination_audio,
        video_sha256=sha256_file(destination_video),
        audio_sha256=sha256_file(destination_audio),
        duration_us=measured,
        ffmpeg_version=version,
        source_start_us=start_us,
        source_end_us=end_us,
    )


def _require_local(path: Path, root: Path) -> None:
    text = str(path).lower()
    scheme = path.parts[0].lower() if path.parts else ""
    # Path collapses "https://" to "https:/", so the scheme part is checked too.
    if scheme in {"http:", "https:"} or text.startswith(("http://", "https://")) or ".." in path.parts:
        raise MediaError("refusing a remote or traversing media path")
    if path.is_symlink() or not path.is_file():
        raise MediaError(f"refusing to trim {path.name}")
    try:
        ensure_within(root, path)
    except MediaError:
        # The analysis proxy lives in the work root. A path outside it is rejected.
        raise


def _safe_name(name: str) -> bool:
    return "/" not in name and "\\" not in name and ".." not in name and len(name) <= 80


def _ffmpeg_version(ffmpeg: str, runner: ProcessRunner) -> str:
    completed = runner.run([ffmpeg, "-version"], log_path=None, check=True)
    line = completed.stdout.splitlines()[0].strip() if completed.stdout else "ffmpeg"
    return line[:120]


def _duration_us(path: Path, runner: ProcessRunner, log_path: Path | None) -> int:
    payload = read_ffprobe_json(path, runner, log_path)
    streams = payload.get("streams")
    if isinstance(streams, list):
        for stream in streams:
            if isinstance(stream, dict) and stream.get("codec_type") == "video":
                duration = seconds_text_to_us(stream.get("duration"))
                if duration is not None and duration > 0:
                    return duration
    container = payload.get("format")
    if isinstance(container, dict):
        duration = seconds_text_to_us(container.get("duration"))
        if duration is not None and duration > 0:
            return duration
    raise MediaError(f"{path.name} has no positive duration")


def ffprobe_available() -> str:
    return resolve_ffprobe()
