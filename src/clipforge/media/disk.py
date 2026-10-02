"""Storage preflight. Preparation stops before ffmpeg when the reserve would be crossed.

Estimate, in bytes, for a source of ``duration_us`` with optional audio::

    seconds = duration_us / 1_000_000
    proxy = seconds * 1_500_000 + 1_000_000
    partial_proxy = proxy
    flac = seconds * 32_000 + 100_000 if audio else 0
    partial_flac = flac
    overhead = 8 MiB
    estimate = (proxy + partial_proxy + flac + partial_flac + overhead) * 3 / 2

``1_500_000`` bytes per second is a high proxy rate for a 1280-long-edge H.264
file, used so the guess stays above the file we will write. FLAC is bounded by
the uncompressed 16 kHz 16-bit mono rate. The 3/2 factor covers filter
scratch and a short moov rewrite. The check fails when
``free - estimate <= reserve``, so projected free space after the write stays
strictly above the reserve.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.paths import resolve_disk_reserve_bytes

_GIBIBYTE = 1024**3


@dataclass(frozen=True, slots=True)
class DiskStatus:
    work_root: Path
    filesystem: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    reserve_bytes: int

    @property
    def usable_bytes(self) -> int:
        return max(0, self.free_bytes - self.reserve_bytes)


def read_disk(work_root: Path, reserve_bytes: int | None = None) -> DiskStatus:
    reserve = resolve_disk_reserve_bytes(reserve_bytes)
    probe_path = _existing_ancestor(work_root)
    usage = shutil.disk_usage(probe_path)
    try:
        device = f"device:{probe_path.stat().st_dev}"
    except OSError:
        device = "unknown"
    return DiskStatus(
        work_root=work_root,
        filesystem=device,
        total_bytes=usage.total,
        used_bytes=usage.used,
        free_bytes=usage.free,
        reserve_bytes=reserve,
    )


def estimate_prepare_bytes(duration_us: int, *, has_audio: bool) -> int:
    if duration_us <= 0:
        raise MediaError("cannot estimate storage for a non-positive duration")
    seconds = duration_us / 1_000_000
    proxy = int(seconds * 1_500_000) + 1_000_000
    flac = int(seconds * 32_000) + 100_000 if has_audio else 0
    overhead = 8 * 1024 * 1024
    return int((proxy + proxy + flac + flac + overhead) * 3 / 2)


def require_disk_budget(free_bytes: int, reserve_bytes: int, estimate_bytes: int) -> None:
    """Fail when projected free space would not stay strictly above the reserve."""
    if estimate_bytes < 0 or free_bytes < 0 or reserve_bytes < 0:
        raise MediaError("disk figures must be zero or positive")
    projected = free_bytes - estimate_bytes
    if projected <= reserve_bytes:
        raise MediaError(
            "not enough free disk for derived media. "
            f"Free space is {free_bytes} bytes, the reserve is {reserve_bytes} bytes, "
            f"and this prepare is estimated at {estimate_bytes} bytes. "
            f"Projected free space would be {projected} bytes, which does not stay above the reserve. "
            "ffmpeg was not started. Free space or lower the job's output, then retry. "
            "There is no ignore-disk-safety override."
        )


def format_bytes(value: int) -> str:
    if value >= _GIBIBYTE:
        return f"{value} bytes ({value / _GIBIBYTE:.2f} GiB)"
    return f"{value} bytes"


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists():
        if current.parent == current:
            break
        current = current.parent
    if not current.exists():
        raise MediaError(f"cannot measure disk space for {path}: no parent directory exists")
    return current


def device_label(path: Path) -> str:
    try:
        return f"device:{os.stat(path).st_dev}"
    except OSError:
        return "unknown"
