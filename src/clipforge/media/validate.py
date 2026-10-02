"""Check a derived file with ffprobe before it is allowed to take its final name."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clipforge.errors import MediaError
from clipforge.media.clock import duration_tolerance_us, seconds_text_to_us
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.schemas.ingest import RationalNumber

_SAMPLE_RATE_TOLERANCE = 1


def validate_asr_audio(
    path: Path,
    runner: ProcessRunner,
    *,
    canonical_duration_us: int,
    rate: RationalNumber | None,
    log_path: Path | None,
) -> dict[str, Any]:
    payload = read_ffprobe_json(path, runner, log_path)
    audio = _streams(payload, "audio")
    video = _streams(payload, "video")
    if video:
        raise MediaError(f"{path.name} contains a video stream. ASR audio must be audio only.")
    if len(audio) != 1:
        raise MediaError(f"{path.name} must contain exactly one audio stream")
    stream = audio[0]
    if stream.get("codec_name") != "flac":
        raise MediaError(f"{path.name} codec is {stream.get('codec_name')!r}, expected flac")
    channels = _int_field(stream.get("channels"))
    if channels != 1:
        raise MediaError(f"{path.name} has {channels} channels, expected mono")
    sample_rate = _int_field(stream.get("sample_rate"))
    if sample_rate is None or abs(sample_rate - 16000) > _SAMPLE_RATE_TOLERANCE:
        raise MediaError(f"{path.name} sample rate is {sample_rate!r}, expected 16000 Hz")
    _require_duration(stream, payload, canonical_duration_us, rate, path.name)
    return payload


def validate_proxy(
    path: Path,
    runner: ProcessRunner,
    *,
    canonical_duration_us: int,
    rate: RationalNumber | None,
    output_width: int,
    output_height: int,
    display_width: int,
    display_height: int,
    expect_audio: bool,
    log_path: Path | None,
) -> dict[str, Any]:
    payload = read_ffprobe_json(path, runner, log_path)
    video_streams = _streams(payload, "video")
    audio_streams = _streams(payload, "audio")
    if len(video_streams) != 1:
        raise MediaError(f"{path.name} must contain exactly one video stream")
    video = video_streams[0]
    if video.get("codec_name") != "h264":
        raise MediaError(f"{path.name} video codec is {video.get('codec_name')!r}, expected h264")
    if video.get("pix_fmt") != "yuv420p":
        raise MediaError(f"{path.name} pix_fmt is {video.get('pix_fmt')!r}, expected yuv420p")
    width = _int_field(video.get("width"))
    height = _int_field(video.get("height"))
    if width != output_width or height != output_height:
        raise MediaError(
            f"{path.name} is {width}x{height}, expected {output_width}x{output_height} "
            "after aspect-preserving scale and display rotation."
        )
    if width > display_width or height > display_height:
        raise MediaError(
            f"{path.name} is {width}x{height}, larger than display {display_width}x{display_height}. "
            "The proxy must not upscale."
        )
    if expect_audio and not audio_streams:
        raise MediaError(f"{path.name} is missing audio that the source has")
    if not expect_audio and audio_streams:
        raise MediaError(f"{path.name} has audio, but the source has no selected audio stream")
    rotation = _output_rotation(video)
    if rotation not in {None, 0}:
        raise MediaError(
            f"{path.name} still carries rotation {rotation}. "
            "The proxy should have baked display orientation into the pixels."
        )
    _require_duration(video, payload, canonical_duration_us, rate, path.name)
    return payload


def _require_duration(
    stream: dict[str, Any],
    payload: dict[str, Any],
    expected_us: int,
    rate: RationalNumber | None,
    label: str,
) -> None:
    actual = seconds_text_to_us(stream.get("duration"))
    if actual is None:
        fmt = payload.get("format")
        if isinstance(fmt, dict):
            actual = seconds_text_to_us(fmt.get("duration"))
    tolerance = duration_tolerance_us(rate)
    if actual is None or abs(actual - expected_us) > tolerance:
        raise MediaError(
            f"{label} duration is {actual} microseconds, canonical duration is {expected_us}, "
            f"tolerance is {tolerance}. Refusing to publish a timeline that does not match the source."
        )


def _streams(payload: dict[str, Any], codec_type: str) -> list[dict[str, Any]]:
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return []
    return [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == codec_type]


def _int_field(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _output_rotation(stream: dict[str, Any]) -> int | None:
    side = stream.get("side_data_list")
    if isinstance(side, list):
        for item in side:
            if isinstance(item, dict) and "rotation" in item:
                value = item.get("rotation")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return round(value)
                if isinstance(value, str):
                    try:
                        return round(float(value))
                    except ValueError:
                        return None
    tags = stream.get("tags")
    if isinstance(tags, dict) and "rotate" in tags:
        try:
            return round(float(str(tags["rotate"])))
        except ValueError:
            return None
    return None
