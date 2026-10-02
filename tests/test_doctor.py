"""Doctor statuses stay PASS, WARN, or FAIL and do not hide a SQLite failure."""

from __future__ import annotations

from pathlib import Path

from clipforge.doctor import exit_code, run_checks


def test_foundation_checks_pass(tmp_path: Path) -> None:
    checks = run_checks(tmp_path)
    by_name = {check.name: check for check in checks}
    assert by_name["python"].status == "PASS"
    assert by_name["sqlite"].status == "PASS"
    assert by_name["work_directory"].status == "PASS"
    assert set(by_name) == {
        "python",
        "ffmpeg",
        "ffprobe",
        "node",
        "npm",
        "pnpm",
        "git",
        "work_directory",
        "sqlite",
        "gpu",
    }
    assert exit_code(checks) == 0
    assert all(check.status in {"PASS", "WARN", "FAIL"} for check in checks)
