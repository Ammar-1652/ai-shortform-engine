"""Canonical source clock and the filter graphs that follow it.

Canonical ``t=0`` is the first presentation timestamp of the selected primary
video stream. ``video_origin_us`` is that timestamp on the container clock.
Audio offset is ``audio_start_us - video_origin_us``. A positive offset means
the audio starts later, so ASR audio gets that much leading silence. A
negative offset means the audio starts earlier, so the lead-in is trimmed.
Speech samples are not stretched, pitched, or loudness-normalized.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from clipforge.errors import MediaError
from clipforge.schemas.common import MAX_TIMELINE_US
from clipforge.schemas.ingest import (
    AudioStreamInfo,
    ColorMetadata,
    FrameTimingClass,
    HdrSignal,
    MediaFormatInfo,
    MediaTimelineInfo,
    RationalNumber,
    StreamSelection,
    VideoStreamInfo,
)

MAX_PROXY_LONG_EDGE = 1280
_PQ = frozenset({"smpte2084", "pq"})
_HLG = frozenset({"arib-std-b67", "hlg"})


def seconds_text_to_us(value: object) -> int | None:
    """Convert an ffprobe seconds string to integer microseconds, half-up."""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return None
    quantized = (decimal * Decimal(1_000_000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def pts_to_us(pts: int, numerator: int, denominator: int) -> int:
    """Convert ``pts * numerator / denominator`` seconds into microseconds, half-up."""
    if denominator <= 0:
        raise MediaError("stream time_base denominator must be positive")
    return _div_half_up(pts * numerator * 1_000_000, denominator)


def parse_ratio(value: object) -> RationalNumber | None:
    """Parse ``30000/1001``. ``0/0`` and missing values stay unknown."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if "/" not in text:
        return None
    left, right = text.split("/", 1)
    try:
        numerator = int(left)
        denominator = int(right)
    except ValueError:
        return None
    if numerator <= 0 or denominator <= 0:
        return None
    return RationalNumber(numerator=numerator, denominator=denominator)


def canonical_duration(video: VideoStreamInfo, fmt: MediaFormatInfo) -> tuple[int, str]:
    """Selected-video timing wins. Format duration is used only when video start is 0 or absent."""
    if video.duration_ts is not None and video.duration_ts > 0 and video.time_base is not None:
        microseconds = pts_to_us(video.duration_ts, video.time_base.numerator, video.time_base.denominator)
        if microseconds > 0:
            _reject_huge(microseconds)
            return microseconds, "selected_video_duration_ts"
    if video.duration_us is not None and video.duration_us > 0:
        _reject_huge(video.duration_us)
        return video.duration_us, "selected_video_duration"
    if video.start_time_us in {None, 0} and fmt.duration_us is not None and fmt.duration_us > 0:
        _reject_huge(fmt.duration_us)
        if video.start_time_us is None:
            return fmt.duration_us, "format_duration_video_start_absent"
        return fmt.duration_us, "format_duration_video_start_zero"
    raise MediaError(
        "could not establish a canonical duration from the selected video stream. "
        "ffprobe did not report a positive video duration_ts, video duration, or a usable "
        "format duration with video start at zero. Refusing to invent a duration."
    )


def build_timeline(
    video: VideoStreamInfo,
    audio: AudioStreamInfo | None,
    fmt: MediaFormatInfo,
) -> MediaTimelineInfo:
    video_start = video.start_time_us
    assumed_video = video_start is None
    origin = 0 if video_start is None else video_start
    duration, evidence = canonical_duration(video, fmt)
    if audio is None:
        return MediaTimelineInfo(
            video_origin_us=origin,
            video_start_assumed_zero=assumed_video,
            audio_start_us=None,
            audio_start_assumed_zero=False,
            audio_offset_us=None,
            canonical_duration_us=duration,
            duration_evidence=evidence,
        )
    audio_start_value = audio.start_time_us
    assumed_audio = audio_start_value is None
    audio_start = 0 if audio_start_value is None else audio_start_value
    if assumed_audio:
        evidence = f"{evidence}+audio_start_assumed_zero"
    return MediaTimelineInfo(
        video_origin_us=origin,
        video_start_assumed_zero=assumed_video,
        audio_start_us=audio_start,
        audio_start_assumed_zero=assumed_audio,
        audio_offset_us=audio_start - origin,
        canonical_duration_us=duration,
        duration_evidence=evidence,
    )


def classify_frame_timing(video: VideoStreamInfo) -> FrameTimingClass:
    """Compare avg_frame_rate and r_frame_rate. Do not scan packets."""
    average = video.avg_frame_rate
    reported = video.r_frame_rate
    if average is None or reported is None:
        return FrameTimingClass.UNKNOWN
    if average.numerator <= 0 or reported.numerator <= 0:
        return FrameTimingClass.UNKNOWN
    if (average.numerator, average.denominator) != (reported.numerator, reported.denominator):
        return FrameTimingClass.VFR_POSSIBLE
    return FrameTimingClass.CFR_LIKELY


def hdr_signal(color: ColorMetadata) -> HdrSignal:
    transfer = (color.color_transfer or "").strip().lower()
    if transfer in _PQ:
        return HdrSignal.PQ
    if transfer in _HLG:
        return HdrSignal.HLG
    return HdrSignal.NONE


def select_streams(
    videos: list[VideoStreamInfo],
    audios: list[AudioStreamInfo],
    *,
    video_override: int | None,
    audio_override: int | None,
) -> tuple[VideoStreamInfo, AudioStreamInfo | None, StreamSelection]:
    usable_video = sorted(
        (stream for stream in videos if _usable_video(stream)),
        key=lambda stream: stream.index,
    )
    if video_override is not None:
        chosen = [stream for stream in usable_video if stream.index == video_override]
        if not chosen:
            attached = [
                stream
                for stream in videos
                if stream.index == video_override and stream.disposition.attached_pic
            ]
            if attached:
                raise MediaError(
                    f"video stream {video_override} is an attached picture, not a usable video stream. "
                    "Pick another --video-stream index. Clipforge did not fall back."
                )
            raise MediaError(
                f"video stream {video_override} is not a usable video stream. "
                "Clipforge did not fall back to a different stream."
            )
        video = chosen[0]
        video_how: Literal["automatic", "explicit"] = "explicit"
    else:
        if not usable_video:
            raise MediaError(
                "no usable video stream. Attached pictures were ignored. "
                "This file cannot be ingested as a video source."
            )
        defaults = [stream for stream in usable_video if stream.disposition.default]
        video = defaults[0] if defaults else usable_video[0]
        video_how = "automatic"

    usable_audio = sorted(
        (stream for stream in audios if _usable_audio(stream)),
        key=lambda stream: stream.index,
    )
    if audio_override is not None:
        chosen_audio = [stream for stream in usable_audio if stream.index == audio_override]
        if not chosen_audio:
            raise MediaError(
                f"audio stream {audio_override} is not a usable audio stream. "
                "Clipforge did not fall back to a different stream."
            )
        audio: AudioStreamInfo | None = chosen_audio[0]
        audio_how: Literal["automatic", "explicit", "none"] = "explicit"
    elif not usable_audio:
        audio = None
        audio_how = "none"
    else:
        defaults_audio = [stream for stream in usable_audio if stream.disposition.default]
        audio = defaults_audio[0] if defaults_audio else usable_audio[0]
        audio_how = "automatic"
    selection = StreamSelection(
        video_stream_index=video.index,
        audio_stream_index=None if audio is None else audio.index,
        video_selection=video_how,
        audio_selection=audio_how,
    )
    return video, audio, selection


def display_dimensions(
    width: int,
    height: int,
    sample_aspect: RationalNumber | None,
    rotation: int | None,
) -> tuple[int, int]:
    display_width = width
    if sample_aspect is not None and sample_aspect.numerator > 0:
        display_width = round(width * sample_aspect.numerator / sample_aspect.denominator)
    display_width = max(display_width, 1)
    if _swaps_axes(rotation):
        return height, display_width
    return display_width, height


def proxy_pixel_size(display_width: int, display_height: int) -> tuple[int, int]:
    """Fit inside a 1280 long edge. Never upscale. Even sizes drop at most one pixel."""
    if display_width <= 0 or display_height <= 0:
        raise MediaError("display dimensions must be positive before a proxy can be scaled")
    long_edge = max(display_width, display_height)
    if long_edge <= MAX_PROXY_LONG_EDGE:
        return _even(display_width), _even(display_height)
    if display_width >= display_height:
        width = MAX_PROXY_LONG_EDGE
        height = round(display_height * MAX_PROXY_LONG_EDGE / display_width)
    else:
        height = MAX_PROXY_LONG_EDGE
        width = round(display_width * MAX_PROXY_LONG_EDGE / display_height)
    return _even(max(width, 1)), _even(max(height, 1))


def rotation_filters(degrees: int | None) -> list[str]:
    """Bake a right-angle display rotation into pixels. Other angles fail closed."""
    if degrees is None:
        return []
    quadrant = degrees % 360
    if quadrant == 0:
        return []
    if quadrant == 90:
        return ["transpose=1"]
    if quadrant == 180:
        return ["hflip", "vflip"]
    if quadrant == 270:
        return ["transpose=2"]
    raise MediaError(
        f"rotation of {degrees} degrees is not a right angle. "
        "Round 2 bakes 0, 90, 180, and 270 degree display metadata only."
    )


def duration_tolerance_us(rate: RationalNumber | None) -> int:
    """max(100 ms, three frame periods). Not bit-exact duration equality."""
    frame_us = 0
    if rate is not None and rate.numerator > 0:
        frame_us = (rate.denominator * 1_000_000) // rate.numerator
    return max(100_000, frame_us * 3)


def us_to_seconds_str(microseconds: int) -> str:
    if microseconds < 0:
        raise MediaError("a filter duration was negative")
    return f"{microseconds // 1_000_000}.{microseconds % 1_000_000:06d}"


def audio_filter_chain(
    stream_index: int,
    offset_us: int,
    duration_us: int,
    *,
    output_rate: int,
    label: str,
    pcm_s16: bool,
) -> str:
    """Build the audio filter_complex fragment for one selected stream.

    The chain's ``t=0`` is canonical video time. Delayed audio is prefixed
    with generated silence. Early audio is trimmed. The result is padded or
    cut to ``duration_us``.
    """
    duration = us_to_seconds_str(duration_us)
    source = f"[0:{stream_index}]aformat=channel_layouts=mono,aresample=48000"
    if offset_us < 0:
        lead = us_to_seconds_str(-offset_us)
        chain = f"{source},atrim=start={lead},asetpts=PTS-STARTPTS"
        chain += f",apad=whole_dur={duration},atrim=end={duration},asetpts=PTS-STARTPTS"
    elif offset_us > 0:
        delay = us_to_seconds_str(offset_us)
        chain = (
            f"aevalsrc=0:d={delay}:s=48000,aformat=channel_layouts=mono,asetpts=PTS-STARTPTS[sil{stream_index}];"
            f"{source},asetpts=PTS-STARTPTS[aud{stream_index}];"
            f"[sil{stream_index}][aud{stream_index}]concat=n=2:v=0:a=1,"
            f"apad=whole_dur={duration},atrim=end={duration}"
        )
    else:
        chain = f"{source},asetpts=PTS-STARTPTS,apad=whole_dur={duration},atrim=end={duration}"
    if output_rate != 48000:
        chain += f",aresample={output_rate}"
    if pcm_s16:
        chain += ",aformat=sample_fmts=s16:channel_layouts=mono"
    return f"{chain}[{label}]"


def proxy_filter_complex(
    *,
    video_index: int,
    audio_index: int | None,
    output_width: int,
    output_height: int,
    sample_aspect: RationalNumber | None,
    rotation: int | None,
    offset_us: int,
    duration_us: int,
) -> str:
    filters = ["setpts=PTS-STARTPTS"]
    if sample_aspect is not None and sample_aspect.numerator != sample_aspect.denominator:
        filters.extend(["scale=iw*sar:ih", "setsar=1"])
    filters.extend(rotation_filters(rotation))
    filters.append(f"scale={output_width}:{output_height}:flags=lanczos")
    filters.extend(["setsar=1", "format=yuv420p", "sidedata=mode=delete:type=DISPLAYMATRIX"])
    parts = [f"[0:{video_index}]{','.join(filters)}[v]"]
    if audio_index is not None:
        parts.append(
            audio_filter_chain(
                audio_index,
                offset_us,
                duration_us,
                output_rate=48000,
                label="a",
                pcm_s16=False,
            )
        )
    return ";".join(parts)


def _usable_video(stream: VideoStreamInfo) -> bool:
    return (
        not stream.disposition.attached_pic
        and stream.width is not None
        and stream.height is not None
        and stream.width > 0
        and stream.height > 0
    )


def _usable_audio(stream: AudioStreamInfo) -> bool:
    return stream.sample_rate is not None or stream.channels is not None


def _swaps_axes(rotation: int | None) -> bool:
    if rotation is None:
        return False
    return rotation % 180 == 90


def _even(value: int) -> int:
    floored = value - (value % 2)
    return max(floored, 2)


def _div_half_up(numerator: int, denominator: int) -> int:
    sign = 1 if numerator >= 0 else -1
    quotient, remainder = divmod(abs(numerator), denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return sign * quotient


def _reject_huge(microseconds: int) -> None:
    if microseconds > MAX_TIMELINE_US:
        raise MediaError(
            "canonical duration is longer than 7 days. "
            "Clipforge refused to store a timestamp past the contract limit."
        )
