"""ffprobe a Hero draft. This does not draw captions."""

from __future__ import annotations

from pathlib import Path

from clipforge.errors import MediaError
from clipforge.hero.constants import DURATION_TOLERANCE_US, OUTPUT_HEIGHT, OUTPUT_WIDTH
from clipforge.media.clock import seconds_text_to_us
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.preview.probe import PreviewProbe


def probe_hero(path: Path, *, expected_duration_us: int) -> PreviewProbe:
    payload = read_ffprobe_json(path, ProcessRunner(), None)
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise MediaError("ffprobe JSON has no streams list")
    videos = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "video"]
    audios = [item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"]
    if len(videos) != 1 or len(audios) != 1:
        raise MediaError(f"{path.name} must contain one video stream and one audio stream")
    video = videos[0]
    audio = audios[0]
    if video.get("codec_name") != "h264":
        raise MediaError(f"{path.name} video codec is {video.get('codec_name')!r}, expected h264")
    pixel_format = video.get("pix_fmt")
    if pixel_format not in {"yuv420p", "yuvj420p"}:
        raise MediaError(f"{path.name} pixel format is {pixel_format!r}, expected yuv420p")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    if width != OUTPUT_WIDTH or height != OUTPUT_HEIGHT:
        raise MediaError(f"{path.name} is {width}x{height}, expected {OUTPUT_WIDTH}x{OUTPUT_HEIGHT}")
    rate = str(video.get("r_frame_rate") or video.get("avg_frame_rate") or "")
    if rate != "30/1":
        raise MediaError(f"{path.name} frame rate is {rate}, expected 30/1")
    duration = seconds_text_to_us(video.get("duration"))
    if duration is None:
        container = payload.get("format")
        duration = seconds_text_to_us(container.get("duration") if isinstance(container, dict) else None)
    if duration is None or duration <= 0:
        raise MediaError(f"{path.name} has no positive duration")
    error = duration - expected_duration_us
    if abs(error) > DURATION_TOLERANCE_US:
        raise MediaError(
            f"{path.name} duration differs from the time map by {error} us, past {DURATION_TOLERANCE_US} us"
        )
    audio_duration = seconds_text_to_us(audio.get("duration"))
    if audio_duration is None or audio_duration <= 0:
        raise MediaError(f"{path.name} has no measurable audio duration")
    audio_error = audio_duration - expected_duration_us
    if abs(audio_error) > DURATION_TOLERANCE_US:
        raise MediaError(
            f"{path.name} audio duration differs from the time map by {audio_error} us, "
            f"past {DURATION_TOLERANCE_US} us; refusing an AV-unsynchronized output"
        )
    audio_start = seconds_text_to_us(audio.get("start_time"))
    if audio_start is not None and abs(audio_start) > DURATION_TOLERANCE_US:
        raise MediaError(f"{path.name} audio starts at {audio_start} us instead of zero")
    codec = audio.get("codec_name")
    if codec != "aac":
        raise MediaError(f"{path.name} audio codec is {codec!r}, expected aac")
    return PreviewProbe("h264", str(pixel_format), "aac", duration, error, 30, 1)
