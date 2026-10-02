"""Read-only candidate verification. This does not repair, score, or load a model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from clipforge.candidates.cache import read_candidate_cache
from clipforge.candidates.constants import KIND_CANDIDATE
from clipforge.candidates.inputs import load_evidence_pair
from clipforge.candidates.integrity import candidate_problems
from clipforge.candidates.service import default_profile
from clipforge.errors import ClipforgeError, MediaError, StorageError
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.schemas.candidates import CandidateMiningDocument
from clipforge.schemas.governance import require_rights_cleared
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
)
from clipforge.transcription.io import read_text

Status = Literal["PASS", "FAIL"]


@dataclass(frozen=True, slots=True)
class VerifyLine:
    status: Status
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class CandidateVerifyReport:
    source_asset_id: str
    lines: tuple[VerifyLine, ...]

    @property
    def status(self) -> Status:
        if any(line.status == "FAIL" for line in self.lines):
            return "FAIL"
        return "PASS"


def verify_candidate(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
) -> CandidateVerifyReport:
    """Check the current candidate set. A missing model cache is not a warning or a failure."""
    lines: list[VerifyLine] = []
    root = work_root.resolve()
    try:
        with database.connect() as connection:
            source = get_source_asset(connection, source_asset_id)
            manifest = get_source_manifest(connection, source_asset_id)
            license_record = get_asset_license_record(connection, source.license_record_id)
    except StorageError as exc:
        return CandidateVerifyReport(source_asset_id, (VerifyLine("FAIL", "source", str(exc)),))
    try:
        require_rights_cleared(license_record)
    except ClipforgeError as exc:
        lines.append(VerifyLine("FAIL", "rights", str(exc)))
    else:
        lines.append(VerifyLine("PASS", "rights", license_record.status.value))
    try:
        inspect_mutation(path_from_file_uri(source.uri), manifest)
    except MediaError as exc:
        lines.append(VerifyLine("FAIL", "source_mutation", str(exc)))
    else:
        lines.append(VerifyLine("PASS", "source_mutation", "referenced source still matches the stored hash"))
    try:
        pair = load_evidence_pair(database, source_asset_id, root)
    except MediaError as exc:
        lines.append(VerifyLine("FAIL", "upstream", str(exc)))
        return CandidateVerifyReport(source_asset_id, tuple(lines))
    lines.append(
        VerifyLine(
            "PASS",
            "upstream",
            f"transcript {pair.transcript.transcript_id} visual {pair.visual.analysis_id}",
        )
    )
    lines.append(VerifyLine("PASS", "candidate_input", pair.candidate_input_sha256))
    record = read_candidate_cache(pair.workspace.candidate_sidecar())
    with database.connect() as connection:
        row = find_artifact(connection, pair.source.project_id, source_asset_id, KIND_CANDIDATE)
        job = None
        if row is not None and row.job_id is not None:
            try:
                job = get_job(connection, row.job_id)
            except StorageError as exc:
                lines.append(VerifyLine("FAIL", "producer", str(exc)))
    if record is None or row is None or row.job_id is None:
        lines.append(VerifyLine("FAIL", "candidate", "candidate set or sidecar is missing"))
        return CandidateVerifyReport(source_asset_id, tuple(lines))
    try:
        path = path_from_file_uri(row.uri)
        document = CandidateMiningDocument.model_validate_json(read_text(path))
    except (OSError, ValidationError, ValueError, MediaError) as exc:
        lines.append(VerifyLine("FAIL", "candidate_document", str(exc)))
        return CandidateVerifyReport(source_asset_id, tuple(lines))
    problems = candidate_problems(
        document,
        record,
        candidate_path=path,
        work_root=root,
        workspace=pair.workspace,
        pair=pair,
        profile=default_profile(),
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
    )
    if problems:
        for problem in problems:
            lines.append(VerifyLine("FAIL", "candidate", problem))
    else:
        lines.append(
            VerifyLine(
                "PASS",
                "candidate",
                f"mining {document.mining_id} selected {document.summary.selected_count}",
            )
        )
    return CandidateVerifyReport(source_asset_id, tuple(lines))
