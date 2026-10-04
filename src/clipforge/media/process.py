"""Run ffprobe and ffmpeg from argument lists. Never through a shell."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, TextIO

from clipforge.errors import MediaError

_STDOUT_LIMIT = 8 * 1024 * 1024
_STDERR_TAIL = 8 * 1024
_LOG_LIMIT = 2 * 1024 * 1024


class MediaCancelled(MediaError):
    """The operator interrupted a media command. Partial outputs must not be kept."""


@dataclass(frozen=True, slots=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr_tail: str
    elapsed_s: float
    log_path: Path | None


class ProcessRunner:
    """One child at a time. Stdout is capped. Stderr is tailed and written to a log file."""

    def __init__(self) -> None:
        self.transcode_count = 0
        self._active: subprocess.Popen[bytes] | None = None

    def run(
        self,
        argv: list[str],
        *,
        log_path: Path | None = None,
        cancel_event: threading.Event | None = None,
        check: bool = True,
        env: dict[str, str] | None = None,
        reap_group: bool = False,
    ) -> ProcessResult:
        if not argv or any(not isinstance(part, str) or part == "" for part in argv):
            raise MediaError("refusing to run a command with an empty argument. The shell was not used.")
        if is_transcode(argv):
            self.transcode_count += 1
        started = time.monotonic()
        log_handle = _open_log(log_path)
        process: subprocess.Popen[bytes] | None = None
        try:
            if log_handle is not None:
                log_handle.write(f"argv: {json.dumps(argv)}\n")
                log_handle.flush()
            process = subprocess.Popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
            self._active = process
            capture = _Capture()
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_thread = threading.Thread(
                target=_read_stdout,
                args=(process.stdout, capture),
                name="clipforge-stdout",
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_read_stderr,
                args=(process.stderr, capture, log_handle),
                name="clipforge-stderr",
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            cancelled = False
            try:
                while process.poll() is None:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        terminate_process(process)
                        break
                    if capture.stdout_overflow:
                        terminate_process(process)
                        break
                    time.sleep(0.05)
            except KeyboardInterrupt:
                terminate_process(process)
                raise
            if reap_group and process.poll() is not None:
                # The leader is still a zombie, so its pid cannot have been reused.
                # Signal the group before wait() so a leftover browser cannot stay up.
                _signal_group(process.pid)
            stdout_thread.join(timeout=2)
            stderr_thread.join(timeout=2)
            returncode = process.wait(timeout=5)
            elapsed = time.monotonic() - started
            stdout = capture.stdout.decode("utf-8", errors="replace")
            stderr_tail = capture.stderr_tail.decode("utf-8", errors="replace")
            if log_handle is not None:
                log_handle.write(f"returncode: {returncode}\n")
                log_handle.write(f"elapsed_s: {elapsed:.3f}\n")
                log_handle.flush()
            if cancelled or (cancel_event is not None and cancel_event.is_set()):
                raise MediaCancelled(
                    f"cancelled {Path(argv[0]).name}. The child process was terminated. "
                    f"Log: {log_path if log_path is not None else 'not requested'}."
                )
            if capture.stdout_overflow:
                raise MediaError(
                    f"{Path(argv[0]).name} stdout exceeded {_STDOUT_LIMIT} bytes. "
                    "The process was terminated instead of loading the rest into memory."
                )
            result = ProcessResult(
                argv=tuple(argv),
                returncode=returncode,
                stdout=stdout,
                stderr_tail=stderr_tail,
                elapsed_s=elapsed,
                log_path=log_path,
            )
            if check and returncode != 0:
                raise MediaError(_failure_message(result))
            return result
        finally:
            if process is not None and process.poll() is None:
                terminate_process(process)
            self._active = None
            if log_handle is not None:
                log_handle.close()


def is_transcode(argv: list[str]) -> bool:
    """True for an ffmpeg encode. ffprobe and ``ffmpeg -version`` are not encodes."""
    if not argv or Path(argv[0]).name != "ffmpeg":
        return False
    return "libx264" in argv or "flac" in argv


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    """SIGTERM the child's process group, then SIGKILL. Wait so it cannot stay a zombie."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return


class _Capture:
    def __init__(self) -> None:
        self.stdout = bytearray()
        self.stderr_tail = bytearray()
        self.stdout_overflow = False
        self.lock = threading.Lock()


def _read_stdout(stream: BinaryIO, capture: _Capture) -> None:
    while True:
        chunk = stream.read(65536)
        if not chunk:
            return
        with capture.lock:
            if len(capture.stdout) + len(chunk) > _STDOUT_LIMIT:
                capture.stdout_overflow = True
                return
            capture.stdout.extend(chunk)


def _read_stderr(stream: BinaryIO, capture: _Capture, log_handle: TextIO | None) -> None:
    written = 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            return
        with capture.lock:
            capture.stderr_tail.extend(chunk)
            if len(capture.stderr_tail) > _STDERR_TAIL:
                del capture.stderr_tail[:-_STDERR_TAIL]
        if log_handle is not None and written < _LOG_LIMIT:
            take = chunk[: _LOG_LIMIT - written]
            log_handle.write(take.decode("utf-8", errors="replace"))
            written += len(take)


def _open_log(log_path: Path | None) -> TextIO | None:
    if log_path is None:
        return None
    if log_path.is_symlink() or log_path.parent.is_symlink():
        raise MediaError(f"renderer log path is a symlink: {log_path.name}")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path.open("a", encoding="utf-8")


def _signal_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _failure_message(result: ProcessResult) -> str:
    detail = " ".join(result.stderr_tail.strip().split())
    limit = 1500 if result.argv and Path(result.argv[0]).name == "node" else 300
    if len(detail) > limit:
        detail = detail[:limit] + "..."
    if not detail:
        detail = "no stderr was captured"
    location = str(result.log_path) if result.log_path is not None else "not requested"
    name = Path(result.argv[0]).name if result.argv else "process"
    label = "renderer log" if name == "node" else "stderr"
    return f"{name} exited {result.returncode}. {label}: {detail} The log is {location}."
