"""Release snapshots measure the actual working tree, including uncommitted code."""

import subprocess
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.operator.release import save_release, snapshot_release, verify_release


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "src").mkdir()
    (repo / "src/tool.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(repo), "add", "src/tool.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "fixture",
        ],
        check=True,
    )
    return repo


def test_dirty_deleted_and_new_runtime_files_invalidate_release(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    work = tmp_path / "work"
    first = save_release(work, repo)
    snapshot = (work / "releases" / f"{first.release_id}.json").read_bytes()
    assert verify_release(work, first.release_id, repo) == first
    assert save_release(work, repo) == first
    assert snapshot == (work / "releases" / f"{first.release_id}.json").read_bytes()
    (repo / "src/tool.py").write_text("value = 2\n")
    with pytest.raises(MediaError, match="stale"):
        verify_release(work, first.release_id, repo)
    second = save_release(work, repo)
    assert first.release_id != second.release_id
    (repo / "src/new.py").write_text("enabled = True\n")
    assert snapshot_release(repo).fingerprint != second.fingerprint
    (repo / "src/tool.py").unlink()
    assert snapshot_release(repo).files != second.files


def test_release_refuses_symlink_and_excludes_private_work_files(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    first = snapshot_release(repo)
    (repo / ".env").write_text("PRIVATE=not-a-real-secret\n")
    (repo / "var").mkdir()
    (repo / "var/private.json").write_text('{"private": true}')
    assert snapshot_release(repo).fingerprint == first.fingerprint
    (repo / "src/alias.py").symlink_to(repo / "src/tool.py")
    with pytest.raises(MediaError, match="symlink"):
        snapshot_release(repo)
