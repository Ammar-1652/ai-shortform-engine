"""ffprobe adapter. The normalized model is what later code reads.

The raw JSON file is kept beside the source as a debugging artifact. Duration,
stream choice, and canonical time come from ``NormalizedMediaProbe``.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from clipforge.errors import MediaError
from clipforge.media.clock import (
    build_timeline,
    canonical_duration,
    classify_frame_timing,
    hdr_signal,
    parse_ratio,
    pts_to_us,
    seconds_text_to_us,
    select_streams,
)
from clipforge.media.clock import display_dimensions as compute_display_dimensions
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffprobe, tool_version
from clipforge.schemas.ingest import (
    AudioStreamInfo,
    ColorMetadata,
    MediaClassification,
    MediaFormatInfo,
    NormalizedMediaProbe,
    RationalNumber,
    RotationMetadata,
    StreamDisposition,
    VideoStreamInfo,
)


def read_ffprobe_json(path: Path, runner: ProcessRunner, log_path: Path | None) -> dict[str, Any]:
    """Return raw ffprobe JSON. This does not choose streams or invent a duration."""
    ffprobe = resolve_ffprobe()
    result = runner.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        log_path=log_path,
        check=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(f"ffprobe returned malformed JSON for {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MediaError(f"ffprobe JSON for {path.name} was not an object")
    return payload


def probe_file(
    path: Path,
    runner: ProcessRunner,
    *,
    video_override: int | None,
    audio_override: int | None,
    log_path: Path | None,
) -> tuple[dict[str, Any], NormalizedMediaProbe]:
    ffprobe = resolve_ffprobe()
    version = tool_version(runner, ffprobe)
    result = runner.run(
        [
            ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ],
        log_path=log_path,
        check=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaError(
            f"ffprobe returned malformed JSON for {path.name}: {exc}. The file was not ingested."
        ) from exc
    if not isinstance(payload, dict):
        raise MediaError(f"ffprobe JSON for {path.name} was not an object. The file was not ingested.")
    normalized = normalize_probe(
        payload,
        ffprobe_version=version,
        video_override=video_override,
        audio_override=audio_override,
    )
    return payload, normalized


def normalize_probe(
    payload: dict[str, Any],
    *,
    ffprobe_version: str,
    video_override: int | None,
    audio_override: int | None,
) -> NormalizedMediaProbe:
    if not ffprobe_version.strip():
        raise MediaError("ffprobe version is empty. Refusing to store a probe without tool provenance.")
    streams = payload.get("streams")
    if streams is None:
        streams = []
    if not isinstance(streams, list):
        raise MediaError("ffprobe JSON streams field was not a list")
    videos: list[VideoStreamInfo] = []
    audios: list[AudioStreamInfo] = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        codec_type = stream.get("codec_type")
        if codec_type == "video":
            videos.append(_video_stream(stream))
        elif codec_type == "audio":
            audios.append(_audio_stream(stream))
    video, audio, selection = select_streams(
        videos,
        audios,
        video_override=video_override,
        audio_override=audio_override,
    )
    fmt = _format_info(payload.get("format"))
    # Duration is checked here so a stream with no timing fails before a manifest is stored.
    canonical_duration(video, fmt)
    timeline = build_timeline(video, audio, fmt)
    chapters = payload.get("chapters")
    chapter_count = len(chapters) if isinstance(chapters, list) else 0
    return NormalizedMediaProbe(
        format=fmt,
        video_streams=videos,
        audio_streams=audios,
        chapter_count=chapter_count,
        ffprobe_version=ffprobe_version[:200],
        selection=selection,
        timeline=timeline,
        classification=MediaClassification(
            frame_timing=classify_frame_timing(video),
            hdr=hdr_signal(video.color),
            transcription_eligible=audio is not None,
        ),
    )


def _format_info(value: object) -> MediaFormatInfo:
    if not isinstance(value, dict):
        return MediaFormatInfo()
    return MediaFormatInfo(
        format_name=_optional_text(value.get("format_name")),
        format_long_name=_optional_text(value.get("format_long_name")),
        duration_us=seconds_text_to_us(value.get("duration")),
        start_time_us=seconds_text_to_us(value.get("start_time")),
        size_bytes=_non_negative_int(value.get("size")),
        bit_rate=_non_negative_int(value.get("bit_rate")),
        tags=_tags(value.get("tags")),
    )


def _video_stream(stream: dict[str, Any]) -> VideoStreamInfo:
    time_base = parse_ratio(stream.get("time_base"))
    start_pts = _optional_int(stream.get("start_pts"))
    start_us = _start_us(start_pts, time_base, stream.get("start_time"))
    duration_ts = _optional_int(stream.get("duration_ts"))
    duration_us = _duration_us(duration_ts, time_base, stream.get("duration"))
    width = _positive_int(stream.get("width"))
    height = _positive_int(stream.get("height"))
    rotation = _rotation(stream)
    sar = parse_ratio(stream.get("sample_aspect_ratio"))
    display_width = None
    display_height = None
    if width is not None and height is not None:
        display_width, display_height = compute_display_dimensions(width, height, sar, rotation)
    return VideoStreamInfo(
        index=_index(stream),
        codec_name=_optional_text(stream.get("codec_name")),
        codec_long_name=_optional_text(stream.get("codec_long_name")),
        profile=_optional_text(stream.get("profile")),
        width=width,
        height=height,
        display_width=display_width,
        display_height=display_height,
        pix_fmt=_optional_text(stream.get("pix_fmt")),
        sample_aspect_ratio=sar,
        display_aspect_ratio=parse_ratio(stream.get("display_aspect_ratio")),
        avg_frame_rate=parse_ratio(stream.get("avg_frame_rate")),
        r_frame_rate=parse_ratio(stream.get("r_frame_rate")),
        time_base=time_base,
        start_pts=start_pts,
        start_time_us=start_us,
        duration_ts=duration_ts,
        duration_us=duration_us,
        bit_rate=_non_negative_int(stream.get("bit_rate")),
        disposition=_disposition(stream.get("disposition")),
        language=_language(stream),
        color=ColorMetadata(
            color_range=_optional_text(stream.get("color_range")),
            color_space=_optional_text(stream.get("color_space")),
            color_transfer=_optional_text(stream.get("color_transfer")),
            color_primaries=_optional_text(stream.get("color_primaries")),
        ),
        rotation=RotationMetadata(degrees=rotation),
        field_order=_optional_text(stream.get("field_order")),
    )


def _audio_stream(stream: dict[str, Any]) -> AudioStreamInfo:
    time_base = parse_ratio(stream.get("time_base"))
    start_pts = _optional_int(stream.get("start_pts"))
    duration_ts = _optional_int(stream.get("duration_ts"))
    return AudioStreamInfo(
        index=_index(stream),
        codec_name=_optional_text(stream.get("codec_name")),
        sample_rate=_positive_int(stream.get("sample_rate")),
        channels=_positive_int(stream.get("channels")),
        channel_layout=_optional_text(stream.get("channel_layout")),
        sample_fmt=_optional_text(stream.get("sample_fmt")),
        time_base=time_base,
        start_pts=start_pts,
        start_time_us=_start_us(start_pts, time_base, stream.get("start_time")),
        duration_ts=duration_ts,
        duration_us=_duration_us(duration_ts, time_base, stream.get("duration")),
        bit_rate=_non_negative_int(stream.get("bit_rate")),
        disposition=_disposition(stream.get("disposition")),
        language=_language(stream),
    )


def _start_us(start_pts: int | None, time_base: RationalNumber | None, start_time: object) -> int | None:
    if start_pts is not None and time_base is not None:
        return pts_to_us(start_pts, time_base.numerator, time_base.denominator)
    return seconds_text_to_us(start_time)


def _duration_us(duration_ts: int | None, time_base: RationalNumber | None, duration: object) -> int | None:
    if duration_ts is not None and duration_ts > 0 and time_base is not None:
        microseconds = pts_to_us(duration_ts, time_base.numerator, time_base.denominator)
        if microseconds > 0:
            return microseconds
    return seconds_text_to_us(duration)


def _index(stream: dict[str, Any]) -> int:
    value = _optional_int(stream.get("index"))
    if value is None or value < 0:
        raise MediaError("ffprobe stream is missing a usable index")
    return value


def _disposition(value: object) -> StreamDisposition:
    if not isinstance(value, dict):
        return StreamDisposition()
    return StreamDisposition(
        default=_flag(value.get("default")),
        attached_pic=_flag(value.get("attached_pic")),
    )


def _rotation(stream: dict[str, Any]) -> int | None:
    side = stream.get("side_data_list")
    if isinstance(side, list):
        for item in side:
            if isinstance(item, dict) and "rotation" in item:
                parsed = _rotation_int(item.get("rotation"))
                if parsed is not None:
                    return parsed
    tags = stream.get("tags")
    if isinstance(tags, dict):
        parsed = _rotation_int(tags.get("rotate"))
        if parsed is not None:
            return parsed
    return None


def _rotation_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal = Decimal(str(value))
    except InvalidOperation:
        return None
    return int(decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _language(stream: dict[str, Any]) -> str | None:
    tags = stream.get("tags")
    if not isinstance(tags, dict):
        return None
    value = tags.get("language")
    if isinstance(value, str) and value.strip():
        return value.strip()[:40]
    return None


def _tags(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            continue
        result[key[:80]] = item[:300]
        if len(result) >= 40:
            break
    return result


def _flag(value: object) -> bool:
    if value is True or value == 1:
        return True
    return isinstance(value, str) and value.strip() in {"1", "true", "True"}


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.upper() == "N/A":
        return None
    return text[:300]


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text or text.upper() == "N/A":
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _positive_int(value: object) -> int | None:
    parsed = _optional_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _non_negative_int(value: object) -> int | None:
    parsed = _optional_int(value)
    if parsed is None or parsed < 0:
        return None
    return parsed
