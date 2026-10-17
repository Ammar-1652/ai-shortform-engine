"""Shared checks for preview cache hits and ``preview verify``."""

from __future__ import annotations

from pathlib import Path

from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.preview.constants import JOB_PREVIEW
from clipforge.preview.inputs import PreviewInputs
from clipforge.preview.probe import probe_preview
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.preview import (
    CandidateRoughPreview,
    RoughPreviewCacheRecord,
    RoughPreviewRenderInput,
    RoughPreviewSetDocument,
)
from clipforge.schemas.time import digest_time_map

_ACCEPTED_PIXEL_FORMATS = frozenset({"yuv420p", "yuvj420p"})


def preview_problems(
    document: RoughPreviewSetDocument,
    record: RoughPreviewCacheRecord,
    *,
    manifest_path: Path,
    work_root: Path,
    workspace: SourceWorkspace,
    inputs: PreviewInputs,
    artifact_job_id: str | None,
    artifact_uri: str,
    artifact_provenance_job_id: str | None,
    artifact_inputs_sha256: str | None,
    artifact_source_ids: tuple[str, ...],
    job: JobRecord | None,
) -> list[str]:
    problems: list[str] = []
    problems.extend(_identity(document, record, inputs))
    problems.extend(
        _producer(
            document,
            record,
            artifact_job_id=artifact_job_id,
            artifact_provenance_job_id=artifact_provenance_job_id,
            artifact_inputs_sha256=artifact_inputs_sha256,
            artifact_source_ids=artifact_source_ids,
            job=job,
        )
    )
    problems.extend(_files(document, manifest_path, record, work_root, workspace, inputs))
    return problems


def _identity(
    document: RoughPreviewSetDocument,
    record: RoughPreviewCacheRecord,
    inputs: PreviewInputs,
) -> list[str]:
    problems: list[str] = []
    if document.preview_set_id != record.preview_set_id or document.provenance.job_id != record.job_id:
        problems.append("preview sidecar does not match the manifest identity")
    same_project = document.project_id == inputs.pair.source.project_id
    same_source = document.source_asset_id == inputs.pair.source.source_asset_id
    if not same_project or not same_source:
        problems.append("preview manifest names another project or source")
    checks = (
        (document.source_sha256, inputs.pair.manifest.content_sha256, "source"),
        (document.candidate_set_sha256, inputs.candidate_sha256, "candidate set"),
        (document.transcript_sha256, inputs.pair.transcript_sha256, "transcript"),
        (document.visual_analysis_sha256, inputs.pair.visual_sha256, "visual analysis"),
        (document.analysis_proxy_sha256, inputs.proxy_sha256, "analysis proxy"),
        (document.asr_audio_sha256, inputs.asr_sha256, "ASR audio"),
        (document.preview_input_sha256, inputs.preview_input_sha256, "preview input digest"),
        (document.mining_id, inputs.candidate_document.mining_id, "mining id"),
        (document.transcript_id, inputs.pair.transcript.transcript_id, "transcript id"),
        (document.visual_analysis_id, inputs.pair.visual.analysis_id, "visual analysis id"),
        (document.candidate_set_artifact_id, inputs.candidate_artifact_id, "candidate artifact id"),
    )
    for left, right, label in checks:
        if left != right:
            problems.append(f"preview manifest {label} does not match the current inputs")
    problems.extend(_sidecar(document, record, inputs))
    expected_ids = [item.candidate_id for item in inputs.candidate_document.candidates]
    got_ids = [item.candidate_id for item in document.previews]
    single = len(got_ids) == 1 and got_ids[0] in expected_ids
    if got_ids != expected_ids and not single:
        problems.append("preview order does not match the current candidate set")
    by_id = {item.candidate_id: item for item in inputs.candidate_document.candidates}
    for preview in document.previews:
        candidate = by_id.get(preview.candidate_id)
        if candidate is None:
            problems.append(f"preview names unknown candidate {preview.candidate_id}")
            continue
        if digest_time_map(candidate.time_map) != preview.time_map_sha256:
            problems.append(f"preview time map hash does not match candidate {preview.candidate_id}")
        segment = candidate.time_map.segments[0]
        if preview.source_start_us != segment.source_start_us or preview.source_end_us != segment.source_end_us:
            problems.append(f"preview source range does not match candidate {preview.candidate_id}")
    return problems


def _producer(
    document: RoughPreviewSetDocument,
    record: RoughPreviewCacheRecord,
    *,
    artifact_job_id: str | None,
    artifact_provenance_job_id: str | None,
    artifact_inputs_sha256: str | None,
    artifact_source_ids: tuple[str, ...],
    job: JobRecord | None,
) -> list[str]:
    problems: list[str] = []
    if artifact_job_id is None or document.provenance.job_id != artifact_job_id:
        problems.append("preview provenance job does not match the artifact row")
    if artifact_provenance_job_id != artifact_job_id:
        problems.append("artifact provenance job does not match the artifact row")
    if record.job_id != artifact_job_id:
        problems.append("preview sidecar job does not match the artifact row")
    if document.source_asset_id not in artifact_source_ids:
        problems.append("preview artifact provenance does not name this source")
    if artifact_inputs_sha256 != document.preview_input_sha256:
        problems.append("artifact input digest does not match the preview manifest")
    if job is None or job.job_id != artifact_job_id:
        problems.append("producing preview job is missing")
        return problems
    if job.kind != JOB_PREVIEW or job.status is not JobStatus.SUCCEEDED:
        problems.append(
            f"producing job {job.job_id} is {job.kind}/{job.status.value}, "
            "expected rough_preview_render/succeeded"
        )
    if job.project_id != document.project_id:
        problems.append("producing preview job is in another project")
    expected = {
        "source_asset_id": document.source_asset_id,
        "source_sha256": document.source_sha256,
        "mining_id": document.mining_id,
        "candidate_set_sha256": document.candidate_set_sha256,
        "transcript_id": document.transcript_id,
        "transcript_sha256": document.transcript_sha256,
        "visual_analysis_id": document.visual_analysis_id,
        "visual_analysis_sha256": document.visual_analysis_sha256,
        "analysis_proxy_sha256": document.analysis_proxy_sha256,
        "asr_audio_sha256": document.asr_audio_sha256,
        "preview_input_sha256": document.preview_input_sha256,
        "profile_fingerprint": document.profile_fingerprint,
        "renderer_recipe_version": document.renderer_recipe_version,
        "caption_algorithm_version": document.caption_algorithm_version,
        "preview_set_id": document.preview_set_id,
        "candidate_count": str(document.summary.rendered_count),
    }
    for key, wanted in expected.items():
        if job.payload.get(key) != wanted:
            problems.append(f"producing job {key} does not match the preview manifest")
    return problems


def _files(
    document: RoughPreviewSetDocument,
    manifest_path: Path,
    record: RoughPreviewCacheRecord,
    work_root: Path,
    workspace: SourceWorkspace,
    inputs: PreviewInputs,
) -> list[str]:
    del inputs
    problems: list[str] = []
    try:
        uri_path = manifest_path
        ensure_within(work_root, uri_path)
    except MediaError as exc:
        return [str(exc)]
    expected = workspace.preview_run_dir(document.preview_set_id) / "manifest.json"
    if manifest_path != expected or manifest_path.is_symlink() or not manifest_path.is_file():
        return ["preview manifest is not manifest.json inside this source's preview run"]
    try:
        digest = sha256_file(manifest_path)
        size = manifest_path.stat().st_size
    except OSError as exc:
        return [f"could not read preview manifest: {exc}"]
    if digest != record.manifest_sha256 or size != record.manifest_size_bytes:
        problems.append("preview manifest hash or size does not match the sidecar")
    run = manifest_path.parent
    for preview in document.previews:
        video = run / preview.preview_relative_path
        rendered = run / "candidates" / preview.candidate_id / "render-input.json"
        try:
            ensure_within(work_root, video)
            ensure_within(work_root, rendered)
        except MediaError as exc:
            problems.append(str(exc))
            continue
        if video.is_symlink() or not video.is_file():
            problems.append(f"preview file for {preview.candidate_id} is missing")
            continue
        if rendered.is_symlink() or not rendered.is_file():
            problems.append(f"render input for {preview.candidate_id} is missing")
            continue
        try:
            video_hash = sha256_file(video)
            video_size = video.stat().st_size
            input_hash = sha256_file(rendered)
        except OSError as exc:
            problems.append(f"could not hash preview files for {preview.candidate_id}: {exc}")
            continue
        if video_hash != preview.preview_sha256 or video_size != preview.preview_size_bytes:
            problems.append(f"preview MP4 for {preview.candidate_id} does not match its recorded hash")
        if input_hash != preview.render_input_sha256:
            problems.append(f"render input for {preview.candidate_id} does not match its recorded hash")
        if document.profile.campaign_id == "tarteel":
            try:
                render_input = RoughPreviewRenderInput.model_validate_json(rendered.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                problems.append(f"Tarteel render input for {preview.candidate_id} is invalid: {exc}")
            else:
                overlay = render_input.campaign_overlay
                if overlay is None:
                    problems.append(
                        f"Tarteel render input for {preview.candidate_id} has no CTA/watermark overlay"
                    )
                else:
                    staging = rendered.parent.parent.parent / "staging"
                    frame_prefix = overlay.cta_frame_prefix
                    frame_path = staging / f"{frame_prefix}-0001.png"
                    for name, label in ((overlay.watermark_asset_name, "watermark"),):
                        asset_path = staging / name
                        if (
                            asset_path.is_symlink()
                            or not asset_path.is_file()
                            or asset_path.stat().st_size == 0
                        ):
                            problems.append(f"Tarteel {label} alpha asset is missing from staging")
                    if frame_path.is_symlink() or not frame_path.is_file() or frame_path.stat().st_size == 0:
                        problems.append("Tarteel CTA alpha frame is missing from staging")
        problems.extend(_technical(video, preview))
    return problems


def _sidecar(
    document: RoughPreviewSetDocument,
    record: RoughPreviewCacheRecord,
    inputs: PreviewInputs,
) -> list[str]:
    """Field-by-field sidecar check against the manifest, the inputs, and the job binding."""
    problems: list[str] = []
    triples = (
        ("project id", record.project_id, document.project_id, inputs.pair.source.project_id),
        ("source id", record.source_asset_id, document.source_asset_id, inputs.pair.source.source_asset_id),
        ("preview set id", record.preview_set_id, document.preview_set_id, document.preview_set_id),
        ("job id", record.job_id, document.provenance.job_id, document.provenance.job_id),
        ("mining id", record.mining_id, document.mining_id, inputs.candidate_document.mining_id),
        ("source SHA", record.source_sha256, document.source_sha256, inputs.pair.manifest.content_sha256),
        (
            "candidate artifact id",
            record.candidate_set_artifact_id,
            document.candidate_set_artifact_id,
            inputs.candidate_artifact_id,
        ),
        (
            "candidate set SHA",
            record.candidate_set_sha256,
            document.candidate_set_sha256,
            inputs.candidate_sha256,
        ),
        ("transcript id", record.transcript_id, document.transcript_id, inputs.pair.transcript.transcript_id),
        (
            "transcript SHA",
            record.transcript_sha256,
            document.transcript_sha256,
            inputs.pair.transcript_sha256,
        ),
        (
            "visual analysis id",
            record.visual_analysis_id,
            document.visual_analysis_id,
            inputs.pair.visual.analysis_id,
        ),
        (
            "visual analysis SHA",
            record.visual_analysis_sha256,
            document.visual_analysis_sha256,
            inputs.pair.visual_sha256,
        ),
        ("proxy SHA", record.analysis_proxy_sha256, document.analysis_proxy_sha256, inputs.proxy_sha256),
        ("ASR SHA", record.asr_audio_sha256, document.asr_audio_sha256, inputs.asr_sha256),
        (
            "input digest",
            record.preview_input_sha256,
            document.preview_input_sha256,
            inputs.preview_input_sha256,
        ),
        (
            "profile fingerprint",
            record.profile_fingerprint,
            document.profile_fingerprint,
            document.profile_fingerprint,
        ),
        (
            "renderer recipe",
            record.renderer_recipe_version,
            document.renderer_recipe_version,
            document.profile.renderer_recipe_version,
        ),
        (
            "caption algorithm",
            record.caption_algorithm_version,
            document.caption_algorithm_version,
            document.profile.caption_algorithm_version,
        ),
    )
    for label, sidecar_value, manifest_value, current_value in triples:
        if sidecar_value != manifest_value or sidecar_value != current_value:
            problems.append(f"preview sidecar {label} does not match the manifest and current inputs")
    if record.rendered_count != document.summary.rendered_count:
        problems.append("preview sidecar rendered count does not match the manifest")
    return problems


def _technical(path: Path, preview: CandidateRoughPreview) -> list[str]:
    """ffprobe the MP4. A matching hash does not excuse an invalid picture."""
    try:
        probed = probe_preview(path, expected_duration_us=preview.output_duration_us, log_path=None)
    except MediaError as exc:
        return [str(exc)]
    problems: list[str] = []
    if probed.video_codec != "h264" or preview.detected_video_codec != "h264":
        problems.append(f"preview {preview.candidate_id} video codec is not h264")
    if probed.audio_codec != "aac" or preview.detected_audio_codec != "aac":
        problems.append(f"preview {preview.candidate_id} audio codec is not aac")
    if (
        probed.pixel_format not in _ACCEPTED_PIXEL_FORMATS
        or preview.detected_pixel_format not in _ACCEPTED_PIXEL_FORMATS
    ):
        problems.append(f"preview {preview.candidate_id} pixel format is not yuv420p")
    if probed.pixel_format != preview.detected_pixel_format:
        problems.append(f"preview {preview.candidate_id} pixel format does not match the manifest")
    if (probed.fps_numerator, probed.fps_denominator) != (30, 1):
        problems.append(f"preview {preview.candidate_id} frame rate is not 30/1")
    if probed.duration_error_us != preview.duration_error_us:
        problems.append(f"preview {preview.candidate_id} duration error does not match the manifest")
    return problems


def artifact_path(uri: str) -> Path:
    return path_from_file_uri(uri)
