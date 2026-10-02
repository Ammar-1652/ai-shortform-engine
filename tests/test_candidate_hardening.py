"""Focused hardening regressions found during the independent Round 5 review."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from clipforge.candidates.constants import KIND_CANDIDATE
from clipforge.candidates.service import default_profile
from clipforge.candidates.show import load_candidate_document
from clipforge.candidates.verify import verify_candidate
from clipforge.errors import MediaError
from clipforge.media.workspace import SourceWorkspace
from clipforge.storage import find_artifact
from clipforge.transcription.io import publish_json as real_publish_json
from tests.candidate_support import PROJECT_ID, SOURCE_ID
from tests.test_candidate_service import _mine, _ready, _reserve

pytestmark = pytest.mark.candidate


def test_candidate_verify_does_not_create_missing_candidate_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    workspace = SourceWorkspace(work, PROJECT_ID, SOURCE_ID)
    runs = workspace.candidate_root() / "runs"
    runs.rmdir()
    workspace.candidate_root().rmdir()
    assert not workspace.candidate_root().exists()

    report = verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work)

    assert report.status == "FAIL"
    assert not workspace.candidate_root().exists()


def test_candidate_verify_uses_the_profile_stored_in_the_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    changed = default_profile().model_copy(update={"max_candidates": 10, "soft_target_min": 10})

    _mine(database, work, profile=changed)

    report = verify_candidate(database=database, source_asset_id=SOURCE_ID, work_root=work)
    assert report.status == "PASS"


def test_first_run_sidecar_failure_removes_uncommitted_current_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    calls = {"count": 0}

    def fail_sidecar(*args: object, **kwargs: object) -> tuple[str, int]:
        calls["count"] += 1
        if calls["count"] == 2:
            raise MediaError("sidecar failed")
        return real_publish_json(*args, **kwargs)  # type: ignore[no-any-return]

    monkeypatch.setattr("clipforge.candidates.service.publish_json", fail_sidecar)
    with pytest.raises(MediaError, match="sidecar"):
        _mine(database, work)

    with database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_CANDIDATE)
    assert row is None


def test_candidate_excerpt_audit_uses_real_sha256_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reserve(monkeypatch)
    database, work = _ready(tmp_path)
    _mine(database, work)
    document = load_candidate_document(database, SOURCE_ID, work)

    candidate = document.candidates[0]
    bundle = next(item for item in document.evidence_bundles if item.candidate_id == candidate.candidate_id)
    transcript_evidence = next(item for item in candidate.evidence if item.kind.value == "transcript")
    expected = hashlib.sha256(bundle.transcript_excerpt.encode("utf-8")).hexdigest()[:12]

    assert f"excerpt digest {expected}" in transcript_evidence.detail
