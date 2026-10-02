"""CLI behavior that Round 1 actually implements."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from clipforge.cli.main import app

runner = CliRunner()


def test_help_lists_foundation_commands_and_not_pipelines() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("doctor", "project", "schema", "db"):
        assert name in result.stdout
    for absent in ("publish", "transcribe", "render", "ingest"):
        assert absent not in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_database_and_project_flow(tmp_path: Path) -> None:
    database = tmp_path / "clipforge.sqlite3"
    missing = runner.invoke(app, ["project", "list", "--db", str(database)])
    assert missing.exit_code != 0
    assert "db init" in missing.stderr

    created = runner.invoke(app, ["db", "init", "--db", str(database)])
    assert created.exit_code == 0
    again = runner.invoke(app, ["db", "init", "--db", str(database)])
    assert again.exit_code == 0

    status = runner.invoke(app, ["db", "status", "--db", str(database)])
    assert status.exit_code == 0
    assert "schema_version: 2" in status.stdout
    assert "projects: 0" in status.stdout

    empty = runner.invoke(app, ["project", "list", "--db", str(database)])
    assert empty.exit_code == 0
    assert "No projects." in empty.stdout

    made = runner.invoke(app, ["project", "create", "Launch", "--db", str(database)])
    assert made.exit_code == 0
    project_id = made.stdout.strip()
    listed = runner.invoke(app, ["project", "list", "--db", str(database)])
    assert project_id in listed.stdout
    assert "Launch" in listed.stdout

    blank = runner.invoke(app, ["project", "create", "   ", "--db", str(database)])
    assert blank.exit_code != 0


def test_schema_export_and_check(tmp_path: Path) -> None:
    out = tmp_path / "generated"
    exported = runner.invoke(app, ["schema", "export", "--out", str(out)])
    assert exported.exit_code == 0
    assert (out / "index.json").is_file()
    checked = runner.invoke(app, ["schema", "check", "--dir", str(out)])
    assert checked.exit_code == 0
    (out / "index.json").unlink()
    drifted = runner.invoke(app, ["schema", "check", "--dir", str(out)])
    assert drifted.exit_code != 0


def test_doctor_exits_zero_for_warnings(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--work-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "[PASS] python:" in result.stdout
    assert "[PASS] sqlite:" in result.stdout
    assert "summary:" in result.stdout
