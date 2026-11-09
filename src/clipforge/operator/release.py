"""Snapshot and verify local production dependencies, including dirty code.

No Git checkout, fetching, activation, environment capture, or credential
collection occurs. Release records stay under the ignored work root.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

from clipforge.editorial.knowledge import canonical_digest
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import mkdir_contained, reject_symlink_chain
from clipforge.paths import find_repo_root
from clipforge.schemas.release import ProductionRelease, ReleaseFile
from clipforge.transcription.io import publish_json

_ROOTS = ("src/", "configs/", "schemas/generated/", "apps/renderer/", ".codex/skills/", "scripts/")
_FILES = {"pyproject.toml", "uv.lock", "AGENTS.md", "SKILLS.md", "ARCHITECTURE.md"}
_EXTENSIONS = {
    ".py",
    ".ts",
    ".tsx",
    ".mjs",
    ".js",
    ".json",
    ".yml",
    ".yaml",
    ".md",
    ".toml",
    ".lock",
    ".sh",
    ".css",
}
_IGNORED = {"node_modules", "__pycache__", ".venv", "public", "dist", ".git"}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise MediaError("could not read release Git identity; inspect git status")
    return result.stdout.decode("utf-8")


def snapshot_release(repo: Path | None = None) -> ProductionRelease:
    """Compute identity from allowlisted tracked/untracked runtime files."""
    root = (repo or find_repo_root()).absolute()
    reject_symlink_chain(root)
    names = set(_git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0"))
    files: list[ReleaseFile] = []
    for name in sorted(names):
        parts = Path(name).parts
        if not name or not (name in _FILES or name.startswith(_ROOTS)):
            continue
        if set(parts) & _IGNORED or Path(name).suffix not in _EXTENSIONS:
            continue
        path = root / name
        reject_symlink_chain(path)
        if not path.exists():  # Deleted tracked files change the inventory fingerprint.
            continue
        if not path.is_file():
            raise MediaError(f"release dependency is not a regular file: {name}")
        files.append(ReleaseFile(relative_path=name, sha256=sha256_file(path), size_bytes=path.stat().st_size))
    code_sha = _git(root, "rev-parse", "HEAD").strip()
    fingerprint = canonical_digest(
        {"code_sha": code_sha, "files": [file.model_dump(mode="json") for file in files]}
    )
    return ProductionRelease(
        release_id=f"release-{fingerprint[:24]}",
        code_sha=code_sha,
        files=files,
        fingerprint=fingerprint,
        created_at=datetime.now(UTC),
    )


def save_release(work_root: Path, repo: Path | None = None) -> ProductionRelease:
    release = snapshot_release(repo)
    root = work_root.absolute()
    if not root.exists():
        root.mkdir(parents=True)
    reject_symlink_chain(root)
    path = confine_work_path(root, f"releases/{release.release_id}.json", label="release")
    mkdir_contained(root, path.parent)
    if path.exists():
        existing = load_release(root, release.release_id)
        if existing.fingerprint != release.fingerprint or existing.files != release.files:
            raise MediaError("release id conflicts with an existing snapshot")
        return existing
    publish_json(path, release, root, path.with_suffix(".partial"))
    stored = load_release(root, release.release_id)
    if stored != release:
        raise MediaError("release readback differs after promotion")
    return stored


def load_release(work_root: Path, release_id: str) -> ProductionRelease:
    path = confine_work_path(work_root, f"releases/{release_id}.json", label="release")
    try:
        stored = ProductionRelease.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise MediaError("release snapshot is missing or invalid; run operator release capture") from exc
    digest = canonical_digest(
        {"code_sha": stored.code_sha, "files": [file.model_dump(mode="json") for file in stored.files]}
    )
    if (
        digest != stored.fingerprint
        or stored.release_id != f"release-{digest[:24]}"
        or release_id != stored.release_id
    ):
        raise MediaError("release snapshot hash or identity changed")
    return stored


def verify_release(work_root: Path, release_id: str, repo: Path | None = None) -> ProductionRelease:
    stored = load_release(work_root, release_id)
    current = snapshot_release(repo)
    if current.fingerprint != stored.fingerprint:
        raise MediaError("production release is stale; capture a new release and revalidate dependent stages")
    return stored
