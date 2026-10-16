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
from clipforge.preview.timing import frame_at_or_after
from clipforge.schemas.time import TimeMapDocument, digest_time_map
from clipforge.timeline import FrameRate

# Enough to land on a prior keyframe for a typical long-GOP H.264 proxy.
_KEYFRAME_PAD_US = 10_000_000
_CUT_FADE_US = 8_000
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


@dataclass(frozen=True, slots=True)
class StagedTimeMap:
    """A frame-accurate local clip made from an ordered jump-cut TimeMap."""

    video_path: Path
    audio_path: Path
    video_sha256: str
    audio_sha256: str
    duration_us: int
    ffmpeg_version: str
    source_ranges: tuple[tuple[int, int], ...]


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
    audio_duration = _audio_duration_us(destination_audio, runner, log_path)
    audio_error = audio_duration - duration_us
    if abs(audio_error) > DURATION_TOLERANCE_US:
        raise MediaError(
            f"staged speech duration {audio_duration} us differs from the candidate span {duration_us} us "
            f"by {audio_error} us; refusing an AV-unsynchronized render"
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


def stage_time_map(
    video: Path,
    audio: Path,
    staging: Path,
    *,
    stem: str,
    time_map: TimeMapDocument,
    frame_count: int,
    root: Path,
    log_path: Path | None,
) -> StagedTimeMap:
    """Stage ordered source ranges without silently repeating the first span.

    Candidate mining remains single-span, but Hero editorial plans may use an
    explicit ordered TimeMap.  Each range is trimmed on the source clock and
    concatenated in list order.  No floating seconds are persisted: the
    integer microseconds are converted only at the ffmpeg argv boundary.
    """
    mapped = time_map.to_time_map()
    source_ranges = tuple((item.source_start_us, item.source_end_us) for item in time_map.segments)
    if not source_ranges or frame_count < 1:
        raise MediaError("a TimeMap stage needs at least one range and one frame")
    if frame_count != mapped.output_frame_count(FrameRate(30, 1)):
        raise MediaError("TimeMap stage frame count does not match its canonical duration at 30/1")
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
    recipe_path = staging / f"{stem}.recipe.json"
    for path in (destination_video, destination_audio, recipe_path):
        ensure_within(root, path)
        if path.exists() or path.is_symlink():
            raise MediaError(f"refusing to replace staged media {path.name}")
    ffmpeg = resolve_ffmpeg()
    runner = ProcessRunner()
    version = _ffmpeg_version(ffmpeg, runner)

    video_parts = []
    segment_frame_counts: list[int] = []
    for index, segment in enumerate(mapped.segments):
        start_us, end_us = segment.source_start_us, segment.source_end_us
        start_frame = frame_at_or_after(segment.output_start_us, frame_count)
        end_frame = frame_at_or_after(segment.output_end_us, frame_count)
        segment_frames = end_frame - start_frame
        if segment_frames < 1:
            raise MediaError("TimeMap segment does not own an output frame")
        segment_frame_counts.append(segment_frames)
        video_parts.append(
            f"[0:v]trim=start={us_to_seconds_str(start_us)}:end={us_to_seconds_str(end_us)},"
            "setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=0.034,"
            f"trim=end_frame={segment_frames},setpts=PTS-STARTPTS[v{index}]"
        )
    video_labels = "".join(f"[v{index}]" for index in range(len(source_ranges)))
    # The ordered TimeMap remains the only program clock. Each picture range
    # is reset to its local zero and concatenated in the declared output order;
    # the paired audio path below uses those identical ranges.
    video_filter = ";".join(video_parts) + ";" + video_labels + f"concat=n={len(source_ranges)}:v=1:a=0[v]"
    runner.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video),
            "-filter_complex",
            video_filter,
            "-map",
            "[v]",
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
    audio_parts = []
    for index, (start_us, end_us) in enumerate(source_ranges):
        segment_duration_us = end_us - start_us
        fade_us = min(_CUT_FADE_US, max(1, segment_duration_us // 3))
        filters = [
            f"atrim=start={us_to_seconds_str(start_us)}:end={us_to_seconds_str(end_us)}",
            "asetpts=PTS-STARTPTS",
        ]
        # A short deterministic envelope removes clicks at editorial cuts
        # without overlapping, duplicating, or retiming speech. The TimeMap
        # remains the sole program clock.
        if index > 0 and source_ranges[index - 1][1] != start_us:
            filters.append(f"afade=t=in:st=0:d={us_to_seconds_str(fade_us)}")
        if index < len(source_ranges) - 1 and end_us != source_ranges[index + 1][0]:
            fade_start = max(0, segment_duration_us - fade_us)
            filters.append(f"afade=t=out:st={us_to_seconds_str(fade_start)}:d={us_to_seconds_str(fade_us)}")
        audio_parts.append(f"[0:a]{','.join(filters)}[a{index}]")
    audio_labels = "".join(f"[a{index}]" for index in range(len(source_ranges)))
    audio_filter = ";".join(audio_parts) + ";" + audio_labels + f"concat=n={len(source_ranges)}:v=0:a=1[a]"
    runner.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(audio),
            "-filter_complex",
            audio_filter,
            "-map",
            "[a]",
            "-c:a",
            "flac",
            str(destination_audio),
        ],
        log_path=log_path,
        check=True,
    )
    duration_us = _duration_us(destination_video, runner, log_path)
    expected_us = mapped.total_output_duration()
    error = duration_us - expected_us
    if abs(error) > DURATION_TOLERANCE_US:
        raise MediaError(
            f"staged TimeMap duration {duration_us} us differs from its ranges {expected_us} us by {error} us"
        )
    audio_probe = read_ffprobe_json(destination_audio, runner, log_path)
    audio_streams = audio_probe.get("streams")
    if not isinstance(audio_streams, list) or len(audio_streams) != 1:
        raise MediaError("staged TimeMap speech must contain exactly one audio stream")
    audio_stream = audio_streams[0]
    audio_us = seconds_text_to_us(audio_stream.get("duration")) if isinstance(audio_stream, dict) else None
    if audio_us is None or abs(audio_us - expected_us) > DURATION_TOLERANCE_US:
        raise MediaError("staged TimeMap speech duration does not match its source ranges")
    audio_start = seconds_text_to_us(audio_stream.get("start_time")) if isinstance(audio_stream, dict) else None
    if audio_start is not None and abs(audio_start) > DURATION_TOLERANCE_US:
        raise MediaError("staged TimeMap speech starts away from output zero")
    recipe_path.write_text(
        json.dumps(
            {
                "source_ranges": source_ranges,
                # Keep the speech edit auditable: the audio and picture are
                # intentionally cut from the identical ordered ranges.  A
                # future adapter must not infer a second ordering here.
                "audio_source_ranges": source_ranges,
                "time_map_sha256": digest_time_map(time_map),
                "expected_duration_us": expected_us,
                "frame_count": frame_count,
                "ffmpeg_version": version,
                "video_codec": "h264",
                "audio_codec": "flac",
                "output_fps": "30/1",
                "audio_boundary_policy": "micro_fade_v1",
                "audio_boundary_fade_us": _CUT_FADE_US,
                "video_frame_policy": "canonical_output_grid_v1",
                "video_segment_frame_counts": segment_frame_counts,
                "staging_recipe": "time-map-v2-frame-quantized",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return StagedTimeMap(
        video_path=destination_video,
        audio_path=destination_audio,
        video_sha256=sha256_file(destination_video),
        audio_sha256=sha256_file(destination_audio),
        duration_us=duration_us,
        ffmpeg_version=version,
        source_ranges=source_ranges,
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


def _audio_duration_us(path: Path, runner: ProcessRunner, log_path: Path | None) -> int:
    payload = read_ffprobe_json(path, runner, log_path)
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise MediaError(f"{path.name} has no stream list")
    audio_streams = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    if len(audio_streams) != 1:
        raise MediaError(f"{path.name} must contain exactly one speech stream")
    duration = seconds_text_to_us(audio_streams[0].get("duration"))
    if duration is None or duration <= 0:
        raise MediaError(f"{path.name} has no measurable speech duration")
    start = seconds_text_to_us(audio_streams[0].get("start_time"))
    if start is not None and abs(start) > DURATION_TOLERANCE_US:
        raise MediaError(f"{path.name} speech starts at {start} us instead of zero")
    return duration


def ffprobe_available() -> str:
    return resolve_ffprobe()
