"""Shared checks for a Hero cache hit and ``hero verify``. Neither path rewrites."""

from __future__ import annotations

from pathlib import Path

from clipforge.errors import MediaError
from clipforge.hero.identity import digest_candidate, hero_input_digest
from clipforge.hero.plan import digest_alignment
from clipforge.hero.probe import probe_hero
from clipforge.hero.selection import review_digest
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.preview.inputs import PreviewInputs
from clipforge.schemas.governance import ReviewDecision
from clipforge.schemas.hero import (
    ForcedAlignmentDocument,
    HeroCacheRecord,
    HeroDraftSetDocument,
    HeroPlanDocument,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.time import digest_time_map


def _alignment_identity_complete(alignment: ForcedAlignmentDocument) -> bool:
    """Return whether an alignment has the Round 30 provider identity.

    Older sidecars still validate because the identity fields have defaults for
    read compatibility. They must not fall through to a misleading plan hash
    mismatch: without the identity, the only safe recovery is to run ``hero
    align`` again under the current provider.
    """

    if alignment.model_name == "fake-forced-align-v1":
        return bool(alignment.binding_sha256)
    return all(
        (
            alignment.binding_sha256,
            alignment.model_revision,
            alignment.checkpoint_sha256,
            alignment.manifest_sha256,
            alignment.alignment_status,
        )
    )


def hero_problems(
    document: HeroDraftSetDocument,
    record: HeroCacheRecord,
    *,
    manifest_path: Path,
    work_root: Path,
    workspace: SourceWorkspace,
    inputs: PreviewInputs,
    rough_artifact_id: str,
    rough_preview_set_id: str,
    rough_manifest_sha256: str,
    reviews: list[ReviewDecision],
    artifact_job_id: str | None,
    artifact_uri: str,
    artifact_provenance_job_id: str | None,
    artifact_inputs_sha256: str | None,
    artifact_source_ids: tuple[str, ...],
    job: JobRecord | None,
    alignment_model: str | None,
    whisperx_version: str | None,
    alignment_config_sha256: str | None,
) -> list[str]:
    """Return human-readable problems. An empty list means the current Hero set is intact."""
    problems: list[str] = []
    if document.hero_set_id != record.hero_set_id or document.provenance.job_id != record.job_id:
        problems.append("Hero sidecar does not match the manifest identity")
    if document.project_id != inputs.pair.source.project_id:
        problems.append("Hero manifest names another project")
    if document.source_asset_id != inputs.pair.source.source_asset_id:
        problems.append("Hero manifest names another source")
    checks = (
        (document.source_sha256, inputs.pair.manifest.content_sha256, "source"),
        (document.candidate_set_sha256, inputs.candidate_sha256, "candidate set"),
        (document.candidate_set_artifact_id, inputs.candidate_artifact_id, "candidate artifact"),
        (document.transcript_id, inputs.pair.transcript.transcript_id, "transcript id"),
        (document.transcript_sha256, inputs.pair.transcript_sha256, "transcript"),
        (document.visual_analysis_id, inputs.pair.visual.analysis_id, "visual analysis id"),
        (document.visual_analysis_sha256, inputs.pair.visual_sha256, "visual analysis"),
        (document.analysis_proxy_sha256, inputs.proxy_sha256, "analysis proxy"),
        (document.asr_audio_sha256, inputs.asr_sha256, "ASR audio"),
        (document.rough_preview_artifact_id, rough_artifact_id, "rough preview artifact"),
        (document.rough_preview_set_id, rough_preview_set_id, "rough preview set"),
        (document.rough_manifest_sha256, rough_manifest_sha256, "rough preview manifest"),
    )
    for found, expected, label in checks:
        if found != expected:
            problems.append(f"Hero {label} does not match the current evidence")
    if alignment_model is not None and document.alignment_model != alignment_model:
        problems.append("Hero alignment model does not match the current adapter")
    if whisperx_version is not None and document.whisperx_version != whisperx_version:
        problems.append("Hero alignment version does not match the current adapter")
    if alignment_config_sha256 is not None and document.alignment_config_sha256 != alignment_config_sha256:
        problems.append("Hero alignment configuration does not match the current adapter")
    if job is None or job.status is not JobStatus.SUCCEEDED or job.job_id != document.provenance.job_id:
        problems.append("Hero job is not the succeeded producer of this manifest")
    same_job = artifact_job_id == document.provenance.job_id
    same_provenance_job = artifact_provenance_job_id == document.provenance.job_id
    if not same_job or not same_provenance_job:
        problems.append("Hero artifact is not bound to this job")
    if artifact_inputs_sha256 != document.hero_input_sha256:
        problems.append("Hero artifact input digest does not match the manifest")
    if inputs.pair.source.source_asset_id not in artifact_source_ids:
        problems.append("Hero artifact provenance does not name this source")
    expected_manifest = workspace.hero_run_dir(document.hero_set_id) / "manifest.json"
    try:
        ensure_within(work_root, manifest_path)
    except MediaError:
        problems.append("Hero manifest is outside the work root")
        return problems
    if manifest_path != expected_manifest or manifest_path.is_symlink() or not manifest_path.is_file():
        problems.append("Hero artifact is not manifest.json inside this Hero run")
        return problems
    if artifact_uri and sha256_file(manifest_path) != record.manifest_sha256:
        problems.append("Hero manifest bytes do not match the sidecar")
    if manifest_path.stat().st_size != record.manifest_size_bytes:
        problems.append("Hero manifest size does not match the sidecar")
    problems.extend(
        _drafts(
            document,
            workspace,
            inputs,
            reviews,
            rough_artifact_id,
            alignment_model=document.alignment_model,
            whisperx_version=document.whisperx_version,
            alignment_config_sha256=document.alignment_config_sha256,
        )
    )
    return problems


def _drafts(
    document: HeroDraftSetDocument,
    workspace: SourceWorkspace,
    inputs: PreviewInputs,
    reviews: list[ReviewDecision],
    rough_artifact_id: str,
    *,
    alignment_model: str,
    whisperx_version: str,
    alignment_config_sha256: str,
) -> list[str]:
    from clipforge.review.service import effective_review

    problems: list[str] = []
    by_id = {item.candidate_id: item for item in inputs.candidate_document.candidates}
    approvals: list[dict[str, str]] = []
    run = workspace.hero_run_dir(document.hero_set_id)
    for draft in document.drafts:
        candidate = by_id.get(draft.candidate_id)
        decision = effective_review(reviews, rough_artifact_id, draft.candidate_id)
        if candidate is None or decision is None or decision.decision != "approved":
            problems.append(f"{draft.candidate_id} is no longer approved for the current rough preview")
            continue
        if decision.review_id != draft.review_id or review_digest(decision) != draft.review_digest:
            problems.append(f"{draft.candidate_id} approval decision does not match the Hero draft")
        if digest_time_map(candidate.time_map) != draft.time_map_sha256:
            problems.append(f"{draft.candidate_id} TimeMap changed after the Hero draft")
        directory = run / "candidates" / draft.candidate_id
        video = directory / "hero.mp4"
        rendered = directory / "render-input.json"
        alignment_path = directory / "alignment.json"
        plan_path = directory / "plan.json"
        for path, label in (
            (video, "MP4"),
            (rendered, "render input"),
            (alignment_path, "alignment"),
            (plan_path, "plan"),
        ):
            if path.is_symlink() or not path.is_file():
                problems.append(f"{draft.candidate_id} {label} is missing")
        if not video.is_file() or video.is_symlink():
            continue
        if sha256_file(video) != draft.preview_sha256 or video.stat().st_size != draft.preview_size_bytes:
            problems.append(f"{draft.candidate_id} MP4 hash or size does not match the manifest")
        render_ready = rendered.is_file() and not rendered.is_symlink()
        if render_ready and sha256_file(rendered) != draft.render_input_sha256:
            problems.append(f"{draft.candidate_id} render input hash does not match the manifest")
        if alignment_path.is_file() and not alignment_path.is_symlink():
            if sha256_file(alignment_path) != draft.alignment_sha256:
                problems.append(f"{draft.candidate_id} alignment hash does not match the manifest")
            else:
                problems.extend(
                    _alignment_file(alignment_path, draft.candidate_id, document, decision, candidate)
                )
        plan_ready = plan_path.is_file() and not plan_path.is_symlink()
        if plan_ready and sha256_file(plan_path) != draft.edit_plan_sha256:
            problems.append(f"{draft.candidate_id} plan hash does not match the manifest")
        try:
            probe_hero(video, expected_duration_us=draft.output_duration_us)
        except MediaError as exc:
            problems.append(f"{draft.candidate_id} MP4 failed inspection: {exc}")
        approvals.append(
            {
                "alignment_id": _alignment_id(alignment_path),
                "alignment_sha256": draft.alignment_sha256,
                "candidate_id": draft.candidate_id,
                "candidate_sha256": digest_candidate(candidate),
                "review_digest": draft.review_digest,
                "review_id": draft.review_id,
                "time_map_sha256": draft.time_map_sha256,
            }
        )
    if len(approvals) == len(document.drafts):
        digest = hero_input_digest(
            source_sha256=document.source_sha256,
            candidate_set_artifact_id=document.candidate_set_artifact_id,
            candidate_set_sha256=document.candidate_set_sha256,
            transcript_id=document.transcript_id,
            transcript_sha256=document.transcript_sha256,
            visual_analysis_id=document.visual_analysis_id,
            visual_analysis_sha256=document.visual_analysis_sha256,
            analysis_proxy_sha256=document.analysis_proxy_sha256,
            asr_audio_sha256=document.asr_audio_sha256,
            rough_preview_artifact_id=document.rough_preview_artifact_id,
            rough_preview_set_id=document.rough_preview_set_id,
            rough_manifest_sha256=document.rough_manifest_sha256,
            profile_fingerprint=document.profile_fingerprint,
            motion_library_version=document.motion_library_version,
            renderer_recipe_version=document.renderer_recipe_version,
            caption_algorithm_version=document.caption_algorithm_version,
            alignment_model=alignment_model,
            whisperx_version=whisperx_version,
            alignment_config_sha256=alignment_config_sha256,
            approvals=approvals,
        )
        if digest != document.hero_input_sha256:
            problems.append("Hero input digest does not match the approved set")
    return problems


def _alignment_file(
    path: Path,
    candidate_id: str,
    document: HeroDraftSetDocument,
    decision: ReviewDecision,
    candidate: object,
) -> list[str]:
    from clipforge.schemas.editorial import CandidateClip

    if not isinstance(candidate, CandidateClip):
        return [f"{candidate_id} is not a candidate clip"]
    try:
        alignment = ForcedAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"{candidate_id} alignment could not be read: {exc}"]
    problems: list[str] = []
    if alignment.candidate_id != candidate_id:
        problems.append(f"{candidate_id} alignment names another candidate")
    if alignment.review_id != decision.review_id or alignment.review_digest != review_digest(decision):
        problems.append(f"{candidate_id} alignment is not bound to the current approval")
    if alignment.rough_preview_artifact_id != document.rough_preview_artifact_id:
        problems.append(f"{candidate_id} alignment is bound to another rough preview")
    same_transcript = alignment.transcript_sha256 == document.transcript_sha256
    same_audio = alignment.asr_audio_sha256 == document.asr_audio_sha256
    if not same_transcript or not same_audio:
        problems.append(f"{candidate_id} alignment does not match the current transcript or ASR audio")
    if alignment.time_map_sha256 != digest_time_map(candidate.time_map):
        problems.append(f"{candidate_id} alignment TimeMap does not match the candidate")
    if any(word.alignment_quality != "forced" for word in alignment.words):
        problems.append(f"{candidate_id} alignment is not forced")
    identity_complete = _alignment_identity_complete(alignment)
    if not identity_complete:
        problems.append(
            f"{candidate_id} alignment uses a legacy provider identity; rerun hero align before planning"
        )
    plan_path = path.parent / "plan.json"
    if plan_path.is_file() and not plan_path.is_symlink():
        try:
            plan = HeroPlanDocument.model_validate_json(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            problems.append(f"{candidate_id} plan could not be read: {exc}")
        else:
            if plan.edit_plan.stage != "hero":
                problems.append(f"{candidate_id} plan is not a Hero plan")
            if identity_complete and plan.alignment_sha256 != digest_alignment(alignment):
                problems.append(f"{candidate_id} plan is not bound to this alignment")
    return problems


def _alignment_id(path: Path) -> str:
    try:
        alignment = ForcedAlignmentDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return alignment.alignment_id
