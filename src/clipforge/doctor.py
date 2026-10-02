"""Environment checks. WARN means usable with a gap. FAIL means this process cannot trust the tool."""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.errors import StorageError
from clipforge.paths import resolve_work_dir
from clipforge.storage import Database

Status = Literal["PASS", "WARN", "FAIL"]
_MIN_PYTHON = (3, 11)


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: Status
    detail: str


def run_checks(work_dir: Path | None = None) -> list[Check]:
    """Inspect the tools Round 1 and the next rounds depend on."""
    return [
        _check_python(),
        _check_command("ffmpeg", ("ffmpeg", "-version"), missing="warn"),
        _check_command("ffprobe", ("ffprobe", "-version"), missing="warn"),
        _check_command("node", ("node", "--version"), missing="warn"),
        _check_command("npm", ("npm", "--version"), missing="warn"),
        _check_command("pnpm", ("pnpm", "--version"), missing="warn"),
        _check_command("git", ("git", "--version"), missing="warn"),
        _check_work_dir(resolve_work_dir(work_dir)),
        _check_sqlite(),
        _check_gpu(),
    ]


def exit_code(checks: list[Check]) -> int:
    """Return 1 when any check failed. Warnings stay on stdout and exit 0."""
    return 1 if any(check.status == "FAIL" for check in checks) else 0


def format_report(checks: list[Check]) -> str:
    lines = [f"[{check.status}] {check.name}: {check.detail}" for check in checks]
    passed = sum(check.status == "PASS" for check in checks)
    warned = sum(check.status == "WARN" for check in checks)
    failed = sum(check.status == "FAIL" for check in checks)
    lines.append(f"summary: {passed} pass, {warned} warn, {failed} fail")
    lines.append(f"acceleration: {_acceleration_line(checks)}")
    return "\n".join(lines)


def _check_python() -> Check:
    version = sys.version_info
    detail = sys.version.split()[0]
    if version < _MIN_PYTHON:
        return Check(
            "python",
            "FAIL",
            f"{detail} is older than {_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}. "
            "Create the project environment with `uv sync` (Python 3.11).",
        )
    return Check("python", "PASS", f"{detail} at {sys.executable}")


def _check_command(name: str, argv: tuple[str, ...], *, missing: Literal["warn", "fail"]) -> Check:
    executable = shutil.which(argv[0])
    if executable is None:
        status: Status = "FAIL" if missing == "fail" else "WARN"
        hint = _missing_hint(name)
        return Check(name, status, f"not found on PATH. {hint}")
    try:
        completed = subprocess.run(
            [executable, *argv[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return Check(name, "FAIL", f"{executable} timed out after 10s")
    except OSError as exc:
        return Check(name, "FAIL", f"could not run {executable}: {exc}")
    text = (completed.stdout or completed.stderr).strip().splitlines()
    first = text[0] if text else "(no output)"
    if completed.returncode != 0:
        return Check(name, "FAIL", f"{executable} exited {completed.returncode}: {first}")
    return Check(name, "PASS", first)


def _missing_hint(name: str) -> str:
    hints = {
        "ffmpeg": "Round 2 ingest needs ffmpeg from your OS packages. Do not download a random binary.",
        "ffprobe": "ffprobe ships with ffmpeg. Install the OS ffmpeg package.",
        "node": "The Remotion scaffold needs Node.js 22 LTS or newer.",
        "npm": "npm ships with Node.js. It is used to install pnpm if corepack is absent.",
        "pnpm": "Install pnpm (Node 22+ corepack, or `npm install -g pnpm`) before renderer checks.",
        "git": "Git is required to version this repository.",
    }
    return hints.get(name, "Install the missing tool and re-run `clipforge doctor`.")


def _check_work_dir(path: Path) -> Check:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".clipforge-write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("work_directory", "FAIL", f"cannot write to {path}: {exc}")
    return Check("work_directory", "PASS", f"writable {path}")


def _check_sqlite() -> Check:
    try:
        with tempfile.TemporaryDirectory() as tmp:
            database = Database(Path(tmp) / "doctor.sqlite3")
            version = database.initialize()
            database.health_check()
    except (StorageError, sqlite3.Error, OSError) as exc:
        return Check("sqlite", "FAIL", f"temporary database check failed: {exc}")
    linked = sqlite3.sqlite_version
    return Check("sqlite", "PASS", f"library {linked}; clipforge schema version {version}")


def _check_gpu() -> Check:
    nvidia = shutil.which("nvidia-smi")
    if nvidia is None:
        return Check(
            "gpu",
            "WARN",
            "nvidia-smi is not on PATH. No NVIDIA GPU was confirmed. CPU is the only verified path.",
        )
    try:
        completed = subprocess.run(
            [
                nvidia,
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return Check("gpu", "WARN", f"nvidia-smi could not be queried: {exc}")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip() or "no output"
        return Check("gpu", "WARN", f"nvidia-smi exited {completed.returncode}: {detail}")
    row = (completed.stdout or "").strip().splitlines()
    if not row:
        return Check("gpu", "WARN", "nvidia-smi returned no GPU rows")
    nvcc = shutil.which("nvcc")
    toolkit = f" nvcc={nvcc}" if nvcc else " nvcc=not-on-PATH"
    return Check(
        "gpu",
        "PASS",
        row[0] + toolkit + ". CUDA inference libraries were not executed.",
    )


def _acceleration_line(checks: list[Check]) -> str:
    gpu = next((check for check in checks if check.name == "gpu"), None)
    if gpu is not None and gpu.status == "PASS":
        return "NVIDIA GPU visible to nvidia-smi. CUDA transcription is not verified in Round 1."
    if sys.platform == "darwin" and "arm" in sys.machine.lower():
        return "Apple Silicon host. GPU inference was not executed."
    return "CPU path only from the tools checked here. No CUDA device was confirmed."
