"""Read the current Hero draft set. These functions do not align or render."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError, StorageError
from clipforge.hero.constants import KIND_HERO
from clipforge.hero.integrity import hero_problems
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.preview.inputs import PreviewInputs, load_preview_inputs
from clipforge.preview.service import default_profile
from clipforge.review.service import require_current_preview
from clipforge.schemas.hero import HeroCacheRecord, HeroDraftOutput, HeroDraftSetDocument
from clipforge.storage import Database, find_artifact, get_job, list_reviews


@dataclass(frozen=True, slots=True)
class CurrentHero:
    project_id: str
    source_asset_id: str
    artifact_id: str
    document: HeroDraftSetDocument
    manifest_path: Path
    manifest_sha256: str
    inputs: PreviewInputs


def load_current_hero(database: Database, source_asset_id: str, work_root: Path) -> CurrentHero:
    """Load one verified Hero draft set. A missing set is an error, not an empty success."""
    root = work_root.resolve()
    current = require_current_preview(database, source_asset_id, root)
    inputs = load_preview_inputs(
        database,
        source_asset_id,
        root,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=False,
    )
    sidecar = inputs.pair.workspace.hero_sidecar()
    if not sidecar.is_file() or sidecar.is_symlink():
        raise MediaError(f"no current hero draft for source {source_asset_id}")
    try:
        record = HeroCacheRecord.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise MediaError(f"current hero draft could not be read: {exc}") from exc
    with database.connect() as connection:
        row = find_artifact(connection, inputs.pair.source.project_id, source_asset_id, KIND_HERO)
        if row is None or row.job_id is None:
            raise MediaError(f"no current hero draft for source {source_asset_id}")
        try:
            job = get_job(connection, row.job_id)
        except StorageError as exc:
            raise MediaError(str(exc)) from exc
        reviews = list_reviews(connection, inputs.pair.source.project_id)
    path = path_from_file_uri(row.uri)
    expected = inputs.pair.workspace.hero_run_dir(record.hero_set_id) / "manifest.json"
    ensure_within(root, path)
    if path != expected or path.is_symlink() or not path.is_file():
        raise MediaError("hero artifact is not manifest.json inside this source's hero run")
    try:
        document = HeroDraftSetDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise MediaError(f"current hero draft could not be read: {exc}") from exc
    problems = hero_problems(
        document,
        record,
        manifest_path=path,
        work_root=root,
        workspace=inputs.pair.workspace,
        inputs=inputs,
        rough_artifact_id=current.artifact_id,
        rough_preview_set_id=current.document.preview_set_id,
        rough_manifest_sha256=current.manifest_sha256,
        reviews=reviews,
        artifact_job_id=row.job_id,
        artifact_uri=row.uri,
        artifact_provenance_job_id=row.provenance.job_id,
        artifact_inputs_sha256=row.provenance.inputs_sha256,
        artifact_source_ids=tuple(row.provenance.source_asset_ids),
        job=job,
        alignment_model=None,
        whisperx_version=None,
        alignment_config_sha256=None,
    )
    if problems:
        raise MediaError("hero draft is not readable: " + "; ".join(problems))
    return CurrentHero(
        project_id=inputs.pair.source.project_id,
        source_asset_id=source_asset_id,
        artifact_id=row.artifact_id,
        document=document,
        manifest_path=path,
        manifest_sha256=sha256_file(path),
        inputs=inputs,
    )


def hero_media_path(database: Database, source_asset_id: str, candidate_id: str, work_root: Path) -> Path:
    current = load_current_hero(database, source_asset_id, work_root)
    draft = next((item for item in current.document.drafts if item.candidate_id == candidate_id), None)
    if draft is None:
        raise MediaError(f"unknown candidate {candidate_id}")
    relative = f"candidates/{candidate_id}/hero.mp4"
    if draft.preview_relative_path != relative:
        raise MediaError("refusing to serve a hero path that is not hero.mp4")
    path = current.manifest_path.parent / relative
    if path.is_symlink():
        raise MediaError("refusing to serve a symlinked hero draft")
    ensure_within(work_root.resolve(), path)
    if not path.is_file():
        raise MediaError(f"hero file for {candidate_id} is missing")
    return path


def format_hero_list(current: CurrentHero) -> str:
    lines = [
        f"hero_set_id: {current.document.hero_set_id}",
        f"artifact_id: {current.artifact_id}",
        f"manifest_sha256: {current.manifest_sha256}",
        f"rough_preview_artifact_id: {current.document.rough_preview_artifact_id}",
        f"profile_fingerprint: {current.document.profile_fingerprint}",
        "rank\tcandidate_id\treview_id\tduration_us\tcaptions",
    ]
    for draft in current.document.drafts:
        lines.append(
            f"{draft.rank}\t{draft.candidate_id}\t{draft.review_id}\t"
            f"{draft.output_duration_us}\t{draft.caption_count}"
        )
    return "\n".join(lines)


def format_hero_show(current: CurrentHero, candidate_id: str) -> str:
    draft = next((item for item in current.document.drafts if item.candidate_id == candidate_id), None)
    if draft is None:
        raise MediaError(f"unknown candidate {candidate_id}")
    return "\n".join(_show_lines(current, draft))


def _show_lines(current: CurrentHero, draft: HeroDraftOutput) -> list[str]:
    return [
        "stage: hero",
        f"source_asset_id: {current.source_asset_id}",
        f"candidate_id: {draft.candidate_id}",
        f"hero_set_id: {current.document.hero_set_id}",
        f"artifact_id: {current.artifact_id}",
        f"rough_preview_artifact_id: {current.document.rough_preview_artifact_id}",
        f"review_id: {draft.review_id}",
        f"review_digest: {draft.review_digest}",
        f"alignment_sha256: {draft.alignment_sha256}",
        f"alignment_model: {current.document.alignment_model}",
        f"whisperx_version: {current.document.whisperx_version}",
        *_alignment_lines(current.document.alignment_model),
        "alignment_quality: forced",
        f"edit_plan_sha256: {draft.edit_plan_sha256}",
        f"time_map_sha256: {draft.time_map_sha256}",
        f"render_input_sha256: {draft.render_input_sha256}",
        f"profile_fingerprint: {current.document.profile_fingerprint}",
        f"motion_library_version: {current.document.motion_library_version}",
        f"renderer_recipe_version: {current.document.renderer_recipe_version}",
        f"caption_algorithm_version: {current.document.caption_algorithm_version}",
        f"duration_us: {draft.output_duration_us}",
        f"duration_error_us: {draft.duration_error_us}",
        f"dimensions: {draft.width}x{draft.height}",
        f"fps: {draft.output_fps_numerator}/{draft.output_fps_denominator}",
        f"video_codec: {draft.detected_video_codec}",
        f"audio_codec: {draft.detected_audio_codec}",
        f"pixel_format: {draft.detected_pixel_format}",
        f"caption_count: {draft.caption_count}",
    ]


def _alignment_lines(model_name: str) -> list[str]:
    from clipforge.language.providers import provider_for_model

    record = provider_for_model(model_name)
    if record is None:
        return [
            "locale: unknown",
            "normalized_language: unknown",
            "alignment_status: alignment_not_claimed",
            "alignment_provider: none",
            "alignment_revision: none",
            "alignment_checkpoint: none",
            "alignment_blocker: alignment_not_claimed",
        ]
    checkpoint = record.checkpoint_sha256 or "none"
    return [
        f"locale: {record.locale}",
        f"normalized_language: {record.normalized_language}",
        f"alignment_status: {record.live_status}",
        f"alignment_provider: {record.provider_name}",
        f"alignment_revision: {record.model_revision}",
        f"alignment_checkpoint: {checkpoint}",
        f"alignment_blocker: {record.unavailable_reason}",
    ]


def workspace_for(current: CurrentHero) -> SourceWorkspace:
    return current.inputs.pair.workspace
