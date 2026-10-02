"""Tiny synthetic media for tests. Nothing here is committed."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def require_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        raise RuntimeError("ffmpeg and ffprobe must be installed. CI installs them with apt.")
    return ffmpeg


def run_ffmpeg(argv: list[str]) -> None:
    completed = subprocess.run(argv, check=False, capture_output=True)
    if completed.returncode != 0:
        tail = completed.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"ffmpeg fixture failed: {tail}")


def synth_video(
    directory: Path,
    name: str,
    *,
    size: str = "160x90",
    rate: str = "30",
    duration: str = "2",
    audio: bool = True,
    audio_offset: str | None = None,
    video_offset: str | None = None,
    extra_audio: bool = False,
    rotate: str | None = None,
    color_trc: str | None = None,
    vfr: bool = False,
    early_tone: bool = False,
) -> Path:
    """Build a short H.264 file. ``audio_offset`` delays the audio input with ``-itsoffset``."""
    ffmpeg = require_ffmpeg()
    target = directory / name
    video = f"testsrc=size={size}:rate={rate}:duration={duration}"
    argv: list[str] = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error"]
    if video_offset is not None:
        argv.extend(["-itsoffset", video_offset])
    argv.extend(["-f", "lavfi", "-i", video])
    if early_tone:
        tone = directory / f"{target.stem}-tone.wav"
        run_ffmpeg(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=200:sample_rate=48000:duration=0.5",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=2000:sample_rate=48000:duration=2.5",
                "-filter_complex",
                "[0:a][1:a]concat=n=2:v=0:a=1[a]",
                "-map",
                "[a]",
                str(tone),
            ]
        )
        argv.extend(["-i", str(tone)])
    elif audio or extra_audio or audio_offset is not None:
        if audio_offset is not None:
            argv.extend(["-itsoffset", audio_offset])
        argv.extend(["-f", "lavfi", "-i", f"sine=frequency=1000:sample_rate=48000:duration={duration}"])
        if extra_audio:
            argv.extend(["-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}"])
    if vfr:
        argv.extend(["-vf", "setpts='PTS+if(eq(mod(N,2),0),0,0.015/TB)'", "-fps_mode", "vfr"])
    argv.extend(["-map", "0:v:0"])
    if early_tone or audio or extra_audio or audio_offset is not None:
        argv.extend(["-map", "1:a:0"])
        if extra_audio:
            argv.extend(["-map", "2:a:0", "-disposition:a:0", "0", "-disposition:a:1", "default"])
    argv.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"])
    if audio or extra_audio or audio_offset is not None or early_tone:
        argv.extend(["-c:a", "aac", "-ac", "1"])
    else:
        argv.append("-an")
    if color_trc is not None:
        argv.extend(
            [
                "-x264-params",
                f"colorprim=bt2020:transfer={color_trc}:colormatrix=bt2020nc",
            ]
        )
    encoded = target if rotate is None else target.with_name(f"{target.stem}-norot{target.suffix}")
    argv.append(str(encoded))
    run_ffmpeg(argv)
    if rotate is None:
        return target
    run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-display_rotation",
            rotate,
            "-i",
            str(encoded),
            "-c",
            "copy",
            str(target),
        ]
    )
    encoded.unlink()
    return target
