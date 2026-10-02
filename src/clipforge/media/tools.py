"""Locate ffmpeg and ffprobe. An override must be an executable file."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.process import ProcessRunner


def resolve_executable(env_name: str, program: str) -> str:
    override = os.environ.get(env_name, "").strip()
    if override:
        path = Path(override)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise MediaError(
                f"{env_name} is not an executable file: {override}. "
                f"Point it at the {program} binary, or unset it to use PATH."
            )
        return str(path)
    found = shutil.which(program)
    if found is None:
        raise MediaError(
            f"{program} was not found on PATH. Install it from the OS packages, "
            f"or set {env_name} to the executable. A static build URL is not downloaded."
        )
    return found


def resolve_ffmpeg() -> str:
    return resolve_executable("CLIPFORGE_FFMPEG", "ffmpeg")


def resolve_ffprobe() -> str:
    return resolve_executable("CLIPFORGE_FFPROBE", "ffprobe")


def tool_version(runner: ProcessRunner, executable: str) -> str:
    result = runner.run([executable, "-version"], log_path=None, check=True)
    line = result.stdout.strip().splitlines()
    if not line or not line[0].strip():
        raise MediaError(f"{Path(executable).name} did not report a version on stdout")
    return line[0].strip()[:200]
