"""WAV checks. ffprobe is used when it is installed. It is not downloaded."""

from __future__ import annotations

import struct
import wave
from pathlib import Path

from clipforge.errors import ClipforgeError


class VoiceError(ClipforgeError):
    """Narration cannot be stored or does not verify."""


def wav_bytes(duration_us: int, sample_rate: int, channels: int) -> bytes:
    """Silence with an exact integer-microsecond duration."""
    frames = duration_us * sample_rate // 1_000_000
    if frames < 1:
        raise VoiceError("narration duration is too short to measure")
    payload = b"\x00\x00" * frames * channels
    header = _wav_header(len(payload), sample_rate, channels)
    return header + payload


def parse_wav(payload: bytes) -> tuple[int, int, int, str]:
    """Return sample rate, channels, duration microseconds, and codec."""
    if len(payload) < 44 or payload[:4] != b"RIFF" or payload[8:12] != b"WAVE":
        raise VoiceError("narration audio is not a WAV file")
    rate, channels, data_bytes = _fmt(payload)
    if data_bytes <= 0:
        raise VoiceError("narration audio is empty")
    frame_bytes = channels * 2
    if data_bytes % frame_bytes != 0:
        raise VoiceError("narration audio frame size is not aligned")
    frames = data_bytes // frame_bytes
    duration_us = frames * 1_000_000 // rate
    if duration_us <= 0:
        raise VoiceError("narration duration is too short to measure")
    return rate, channels, duration_us, "pcm_s16le"


def probe_file(path: Path) -> tuple[int, int, int, str]:
    """Prefer ffprobe. Fall back to the WAV header when ffprobe is absent."""
    import json
    import subprocess
    from shutil import which

    binary = which("ffprobe")
    if binary is None:
        return parse_wav(path.read_bytes())
    completed = subprocess.run(
        [
            binary,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            str(path),
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise VoiceError("ffprobe rejected the narration audio")
    try:
        document = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VoiceError("ffprobe returned an unreadable report") from exc
    streams = document.get("streams")
    if not isinstance(streams, list):
        raise VoiceError("ffprobe did not report an audio stream")
    audio = None
    for item in streams:
        if isinstance(item, dict) and item.get("codec_type") == "audio":
            audio = item
            break
    if not isinstance(audio, dict):
        raise VoiceError("ffprobe did not report an audio stream")
    codec = str(audio.get("codec_name") or "")
    if codec != "pcm_s16le":
        raise VoiceError("narration codec is not pcm_s16le")
    rate = int(audio.get("sample_rate") or 0)
    channels = int(audio.get("channels") or 0)
    duration_text = str(audio.get("duration") or "")
    if not duration_text:
        return parse_wav(path.read_bytes())
    # ffprobe duration is a decimal second string. Convert with integers only.
    if "." in duration_text:
        whole, fraction = duration_text.split(".", 1)
        fraction = (fraction + "000000")[:6]
    else:
        whole, fraction = duration_text, "000000"
    if not whole.isdigit() or not fraction.isdigit():
        raise VoiceError("ffprobe duration was not a decimal second value")
    duration_us = int(whole) * 1_000_000 + int(fraction)
    if rate < 8000 or channels < 1 or duration_us <= 0:
        raise VoiceError("ffprobe measurements are not usable")
    return rate, channels, duration_us, codec


def duration_is_acceptable(
    *,
    actual_us: int,
    target_us: int,
    tolerance_us: int,
    policy: str,
) -> None:
    delta = abs(actual_us - target_us)
    if policy == "preserve_duration" and delta > 1_000:
        raise VoiceError("narration duration does not preserve the target duration")
    if policy == "bounded_time_stretch":
        limit = min(tolerance_us, max(target_us // 20, 1))
        if delta > limit:
            raise VoiceError("narration duration is outside the bounded stretch limit")
        return
    if policy == "reject_if_out_of_range" and delta > tolerance_us:
        raise VoiceError("narration duration is outside the accepted range")
    if policy not in {"preserve_duration", "bounded_time_stretch", "reject_if_out_of_range"}:
        raise VoiceError("narration timing policy is unknown")


def _fmt(payload: bytes) -> tuple[int, int, int]:
    offset = 12
    rate = 0
    channels = 0
    data_bytes = 0
    while offset + 8 <= len(payload):
        chunk = payload[offset : offset + 4]
        size = struct.unpack_from("<I", payload, offset + 4)[0]
        start = offset + 8
        if chunk == b"fmt " and size >= 16:
            audio_format, channels, rate = struct.unpack_from("<HHI", payload, start)
            if audio_format != 1:
                raise VoiceError("narration codec is not pcm_s16le")
            bits = struct.unpack_from("<H", payload, start + 14)[0]
            if bits != 16:
                raise VoiceError("narration sample format is not 16-bit")
        elif chunk == b"data":
            data_bytes = size
        offset = start + size + (size % 2)
    if rate == 0 or channels == 0 or data_bytes == 0:
        raise VoiceError("narration WAV header is incomplete")
    return rate, channels, data_bytes


def _wav_header(data_bytes: int, sample_rate: int, channels: int) -> bytes:
    byte_rate = sample_rate * channels * 2
    block = channels * 2
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_bytes,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block,
        16,
        b"data",
        data_bytes,
    )


def _silence_check(path: Path) -> None:
    """Open through the wave module so a truncated file fails before a job commit."""
    try:
        with wave.open(str(path), "rb") as handle:
            if handle.getnframes() < 1:
                raise VoiceError("narration audio is empty")
    except wave.Error as exc:
        raise VoiceError("narration audio is not a WAV file") from exc
