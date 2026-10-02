"""One integrity check for visual cache readiness and ``vision verify``.

A failure is a list of reasons. Cache turns that into a miss. Verify prints it
as a failure. The rules are not copied into a second hand-written checker.
"""

from __future__ import annotations

from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import ensure_within
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.vision import VisualAnalysisCacheRecord, VisualAnalysisDocument
from clipforge.vision.constants import JOB_VISUAL, RECIPE_NAME, RECIPE_VERSION
from clipforge.vision.profile import (
    face_fingerprint,
    sampling_fingerprint,
    scene_fingerprint,
    tracking_fingerprint,
)

_PAYLOAD_KEYS = (
    "source_asset_id",
    "source_sha256",
    "proxy_sha256",
    "recipe_version",
    "analysis_id",
)


def visual_problems(
    document: VisualAnalysisDocument,
    record: VisualAnalysisCacheRecord,
    *,
    analysis_path: Path,
    work_root: Path,
    current_proxy_sha256: str | None,
    artifact_job_id: str | None,
    artifact_provenance_job_id: str | None,
    artifact_inputs_sha256: str | None,
    artifact_source_ids: tuple[str, ...],
    job: JobRecord | None,
) -> list[str]:
    problems = document_sidecar_problems(document, record)
    problems.extend(
        producer_problems(
            document=document,
            record=record,
            current_proxy_sha256=current_proxy_sha256,
            artifact_job_id=artifact_job_id,
            artifact_provenance_job_id=artifact_provenance_job_id,
            artifact_inputs_sha256=artifact_inputs_sha256,
            artifact_source_ids=artifact_source_ids,
            job=job,
        )
    )
    problems.extend(evidence_problems(document, analysis_path, work_root))
    return problems


def document_sidecar_problems(document: VisualAnalysisDocument, record: VisualAnalysisCacheRecord) -> list[str]:
    problems: list[str] = []
    if document.analysis_id != record.analysis_id:
        problems.append("sidecar analysis_id does not match the document")
    if document.provenance.job_id != record.job_id:
        problems.append("sidecar job_id does not match document provenance")
    if document.project_id != record.project_id or document.source_asset_id != record.source_asset_id:
        problems.append("document project or source does not match the sidecar")
    _compare(problems, "source sha256", document.source_sha256, record.source_sha256)
    _compare(problems, "proxy sha256", document.proxy_sha256, record.proxy_sha256)
    _compare(problems, "proxy recipe", document.proxy_recipe_name, record.proxy_recipe_name)
    _compare(problems, "proxy recipe version", document.proxy_recipe_version, record.proxy_recipe_version)
    _compare(problems, "recipe", document.recipe_name, record.recipe_name)
    _compare(problems, "recipe version", document.recipe_version, record.recipe_version)
    _compare(problems, "pyscenedetect version", document.pyscenedetect_version, record.pyscenedetect_version)
    _compare(problems, "scene backend", document.scene_backend, record.scene_backend)
    _compare(problems, "pyav version", document.pyav_version, record.pyav_version)
    _compare(problems, "opencv version", document.opencv_version, record.opencv_version)
    _compare(problems, "mediapipe version", document.mediapipe_version, record.mediapipe_version)
    _compare(problems, "face model sha256", document.face_model_sha256, record.face_model_sha256)
    _compare(problems, "evidence digest", document.evidence_manifest_digest, record.evidence_manifest_digest)
    if document.recipe_name != RECIPE_NAME or document.recipe_version != RECIPE_VERSION:
        problems.append("document recipe is not visual-analysis v1")
    expected_scene = scene_fingerprint(
        detector=document.scene_detector,
        backend=document.scene_backend,
        adaptive_threshold=document.adaptive_threshold,
        min_content_val=document.min_content_val,
        window_width=document.window_width,
        min_scene_len_frames=document.min_scene_len_frames,
    )
    if expected_scene != document.scene_profile_fingerprint:
        problems.append("document scene settings do not match its scene fingerprint")
    if document.scene_profile_fingerprint != record.scene_profile_fingerprint:
        problems.append("document scene fingerprint does not match the sidecar")
    expected_sampling = sampling_fingerprint(
        fractions=tuple(document.representative_fractions),
        short_scene_us=document.short_scene_us,
        face_sample_interval_us=document.face_sample_interval_us,
        jpeg_quality=document.jpeg_quality,
        jpeg_long_edge=document.jpeg_long_edge,
    )
    if expected_sampling != document.sampling_profile_fingerprint:
        problems.append("document sampling settings do not match its sampling fingerprint")
    if document.sampling_profile_fingerprint != record.sampling_profile_fingerprint:
        problems.append("document sampling fingerprint does not match the sidecar")
    expected_face = face_fingerprint(
        min_detection_confidence=document.min_detection_confidence,
        min_suppression_threshold=document.min_suppression_threshold,
    )
    if expected_face != document.face_profile_fingerprint:
        problems.append("document face settings do not match its face fingerprint")
    if document.face_profile_fingerprint != record.face_profile_fingerprint:
        problems.append("document face fingerprint does not match the sidecar")
    expected_tracking = tracking_fingerprint(
        iou_threshold=document.tracking_iou_threshold,
        center_distance_threshold=document.tracking_center_distance_threshold,
        max_gap_us=document.tracking_max_gap_us,
    )
    if expected_tracking != document.tracking_profile_fingerprint:
        problems.append("document tracking settings do not match its tracking fingerprint")
    if document.tracking_profile_fingerprint != record.tracking_profile_fingerprint:
        problems.append("document tracking fingerprint does not match the sidecar")
    return problems


def producer_problems(
    *,
    document: VisualAnalysisDocument,
    record: VisualAnalysisCacheRecord,
    current_proxy_sha256: str | None,
    artifact_job_id: str | None,
    artifact_provenance_job_id: str | None,
    artifact_inputs_sha256: str | None,
    artifact_source_ids: tuple[str, ...],
    job: JobRecord | None,
) -> list[str]:
    problems: list[str] = []
    if current_proxy_sha256 is None:
        problems.append("current analysis proxy identity is not available")
    elif document.proxy_sha256 != current_proxy_sha256 or record.proxy_sha256 != current_proxy_sha256:
        problems.append("visual analysis proxy sha256 does not match the current analysis proxy")
    if document.provenance.inputs_sha256 != current_proxy_sha256:
        problems.append("document provenance input digest does not match the current analysis proxy")
    if artifact_inputs_sha256 != current_proxy_sha256:
        problems.append("artifact provenance input digest does not match the current analysis proxy")
    if artifact_job_id is None or document.provenance.job_id != artifact_job_id:
        problems.append("document provenance job_id does not match the artifact row")
    if artifact_provenance_job_id != artifact_job_id:
        problems.append("artifact provenance job_id does not match the artifact row")
    if record.job_id != artifact_job_id:
        problems.append("sidecar job_id does not match the artifact row")
    if document.source_asset_id not in artifact_source_ids:
        problems.append("artifact provenance does not name this source")
    if job is None:
        problems.append("producing visual analysis job is missing")
        return problems
    if job.job_id != artifact_job_id or job.job_id != document.provenance.job_id:
        problems.append("producing job id does not match the artifact row")
    if job.kind != JOB_VISUAL or job.status is not JobStatus.SUCCEEDED:
        problems.append(
            f"producing job {job.job_id} is {job.kind}/{job.status.value}, expected visual_analyze/succeeded"
        )
    if job.project_id != document.project_id:
        problems.append("producing job is in a different project")
    payload_id = job.payload.get("analysis_id")
    if payload_id != document.analysis_id:
        problems.append("producing job analysis_id does not match the document")
    for key in _PAYLOAD_KEYS:
        if key == "analysis_id":
            continue
        if key not in job.payload:
            continue
        expected = _payload_value(document, key)
        if job.payload[key] != expected:
            problems.append(f"producing job {key} does not match the document")
    return problems


def evidence_problems(document: VisualAnalysisDocument, analysis_path: Path, work_root: Path) -> list[str]:
    problems: list[str] = []
    run_dir = analysis_path.parent
    try:
        ensure_within(work_root, run_dir)
    except MediaError as exc:
        return [str(exc)]
    for item in document.evidence_files:
        path = run_dir / item.relative_path
        try:
            ensure_within(work_root, path)
        except MediaError as exc:
            problems.append(str(exc))
            continue
        if not path.is_file() or path.is_symlink():
            problems.append(f"evidence file {item.relative_path} is missing")
            continue
        try:
            digest = sha256_file(path)
            size = path.stat().st_size
        except OSError as exc:
            problems.append(f"could not read evidence file {item.relative_path}: {exc}")
            continue
        if digest != item.sha256 or size != item.size_bytes:
            problems.append(f"evidence file {item.relative_path} does not match its recorded hash")
    return problems


def _compare(problems: list[str], label: str, left: str, right: str) -> None:
    if left != right:
        problems.append(f"document {label} does not match the sidecar")


def _payload_value(document: VisualAnalysisDocument, key: str) -> str:
    if key == "source_asset_id":
        return document.source_asset_id
    if key == "source_sha256":
        return document.source_sha256
    if key == "proxy_sha256":
        return document.proxy_sha256
    if key == "recipe_version":
        return document.recipe_version
    return document.analysis_id
