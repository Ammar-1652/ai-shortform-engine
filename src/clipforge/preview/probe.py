"""ffprobe a published rough preview. This does not composite captions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.clock import seconds_text_to_us
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.preview.constants import DURATION_TOLERANCE_US, OUTPUT_HEIGHT, OUTPUT_WIDTH


@dataclass(frozen=True, slots=True)
class PreviewProbe:
    video_codec: str
    pixel_format: str
    audio_codec: str
    duration_us: int
    duration_error_us: int
    fps_numerator: int
    fps_denominator: int


def probe_preview(path: Path, *, expected_duration_us: int, log_path: Path | None) -> PreviewProbe:
    payload = read_ffprobe_json(path, ProcessRunner(), log_path)
    videos = [item for item in _streams(payload) if item.get("codec_type") == "video"]
    audios = [item for item in _streams(payload) if item.get("codec_type") == "audio"]
    if len(videos) != 1:
        raise MediaError(f"{path.name} must contain exactly one video stream")
    if len(audios) != 1:
        raise MediaError(f"{path.name} must contain exactly one audio stream. Silent speech was not invented.")
    video = videos[0]
    audio = audios[0]
    if video.get("codec_name") != "h264":
        raise MediaError(f"{path.name} video codec is {video.get('codec_name')!r}, expected h264")
    pixel_format = video.get("pix_fmt")
    # x264 full-range output is often tagged yuvj420p. It is the same 4:2:0 planar layout.
    if pixel_format not in {"yuv420p", "yuvj420p"}:
        raise MediaError(f"{path.name} pixel format is {pixel_format!r}, expected yuv420p")
    width = _int(video.get("width"))
    height = _int(video.get("height"))
    if width != OUTPUT_WIDTH or height != OUTPUT_HEIGHT:
        raise MediaError(f"{path.name} is {width}x{height}, expected {OUTPUT_WIDTH}x{OUTPUT_HEIGHT}")
    numerator, denominator = _rate(video.get("r_frame_rate") or video.get("avg_frame_rate"))
    if numerator != 30 or denominator != 1:
        raise MediaError(f"{path.name} frame rate is {numerator}/{denominator}, expected 30/1")
    duration = seconds_text_to_us(video.get("duration"))
    if duration is None:
        container = payload.get("format")
        container_duration = container.get("duration") if isinstance(container, dict) else None
        duration = seconds_text_to_us(container_duration)
    if duration is None or duration <= 0:
        raise MediaError(f"{path.name} has no positive duration")
    error = duration - expected_duration_us
    if abs(error) > DURATION_TOLERANCE_US:
        raise MediaError(
            f"{path.name} duration {duration} us differs from the time map {expected_duration_us} us "
            f"by {error} us, past the {DURATION_TOLERANCE_US} us preview tolerance."
        )
    codec = audio.get("codec_name")
    if not isinstance(codec, str) or not codec:
        raise MediaError(f"{path.name} audio codec is missing")
    return PreviewProbe(
        video_codec="h264",
        pixel_format=str(pixel_format),
        audio_codec=codec,
        duration_us=duration,
        duration_error_us=error,
        fps_numerator=numerator,
        fps_denominator=denominator,
    )


def _streams(payload: dict[str, object]) -> list[dict[str, object]]:
    raw = payload.get("streams")
    if not isinstance(raw, list):
        raise MediaError("ffprobe JSON has no streams list")
    return [item for item in raw if isinstance(item, dict)]


def _int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _rate(value: object) -> tuple[int, int]:
    if not isinstance(value, str) or "/" not in value:
        raise MediaError(f"ffprobe frame rate {value!r} is not a rational")
    numerator, denominator = value.split("/", 1)
    if not numerator.isdigit() or not denominator.isdigit() or int(denominator) == 0:
        raise MediaError(f"ffprobe frame rate {value!r} is not a positive rational")
    return int(numerator), int(denominator)
