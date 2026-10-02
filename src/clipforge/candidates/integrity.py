"""One integrity check for a published candidate set.

Cache turns any problem into a miss. Verify prints the same problem. The
transcript and visual checks stay in their own modules.
"""

from __future__ import annotations

from pathlib import Path

from clipforge.candidates.cache import cache_identity_matches
from clipforge.candidates.constants import JOB_CANDIDATE
from clipforge.candidates.inputs import EvidencePair
from clipforge.candidates.overlap import intersection_us
from clipforge.errors import MediaError
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.schemas.candidates import (
    CandidateMiningCacheRecord,
    CandidateMiningDocument,
    CandidateMiningProfile,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import Transcript
from clipforge.schemas.vision import VisualAnalysisDocument

_BANNED = (
    "host speaking",
    "guest speaking",
    "main speaker",
    "speaker face",
    "active_speaker",
    "speaker_score",
    "speaker_probability",
    "likely_speaker",
)


def candidate_problems(
    document: CandidateMiningDocument,
    record: CandidateMiningCacheRecord,
    *,
    candidate_path: Path,
    work_root: Path,
    workspace: SourceWorkspace,
    pair: EvidencePair,
    profile: CandidateMiningProfile,
    artifact_job_id: str | None,
    artifact_uri: str,
    artifact_provenance_job_id: str | None,
    artifact_inputs_sha256: str | None,
    artifact_source_ids: tuple[str, ...],
    job: JobRecord | None,
) -> list[str]:
    """Return why this candidate set is not the current output of this evidence pair."""
    problems: list[str] = []
    problems.extend(_binding_problems(document, record, pair, profile))
    problems.extend(
        _producer_problems(
            document,
            record,
            artifact_job_id=artifact_job_id,
            artifact_provenance_job_id=artifact_provenance_job_id,
            artifact_inputs_sha256=artifact_inputs_sha256,
            artifact_source_ids=artifact_source_ids,
            job=job,
        )
    )
    problems.extend(_path_problems(document, candidate_path, artifact_uri, work_root, workspace))
    problems.extend(_reference_problems(document, pair.transcript, pair.visual))
    if not cache_identity_matches(
        record,
        project_id=pair.source.project_id,
        source_asset_id=pair.source.source_asset_id,
        source_sha256=pair.manifest.content_sha256,
        transcript_id=pair.transcript.transcript_id,
        transcript_sha256=pair.transcript_sha256,
        visual_analysis_id=pair.visual.analysis_id,
        visual_analysis_sha256=pair.visual_sha256,
        candidate_input_sha256=pair.candidate_input_sha256,
        profile=profile,
        candidate_path=candidate_path,
    ):
        problems.append("candidate cache identity does not match the current evidence and profile")
    return problems


def _binding_problems(
    document: CandidateMiningDocument,
    record: CandidateMiningCacheRecord,
    pair: EvidencePair,
    profile: CandidateMiningProfile,
) -> list[str]:
    problems: list[str] = []
    if document.mining_id != record.mining_id:
        problems.append("sidecar mining_id does not match the candidate document")
    if document.provenance.job_id != record.job_id:
        problems.append("sidecar job_id does not match the candidate document")
    if document.project_id != pair.source.project_id or document.source_asset_id != pair.source.source_asset_id:
        problems.append("candidate document names another project or source")
    if document.source_sha256 != pair.manifest.content_sha256:
        problems.append("candidate document source hash does not match the manifest")
    if (
        document.transcript_sha256 != pair.transcript_sha256
        or document.transcript_id != pair.transcript.transcript_id
    ):
        problems.append("candidate document is not bound to the current transcript bytes")
    if (
        document.visual_analysis_sha256 != pair.visual_sha256
        or document.visual_analysis_id != pair.visual.analysis_id
    ):
        problems.append("candidate document is not bound to the current visual analysis bytes")
    if document.candidate_input_sha256 != pair.candidate_input_sha256:
        problems.append("candidate input digest does not match the current transcript and visual hashes")
    if (
        document.transcript_job_id != pair.transcript_job.job_id
        or document.visual_job_id != pair.visual_job.job_id
    ):
        problems.append("candidate document names a different upstream producer")
    if document.profile_fingerprint != profile.fingerprint():
        problems.append("candidate profile fingerprint does not match the requested profile")
    return problems


def _producer_problems(
    document: CandidateMiningDocument,
    record: CandidateMiningCacheRecord,
    *,
    artifact_job_id: str | None,
    artifact_provenance_job_id: str | None,
    artifact_inputs_sha256: str | None,
    artifact_source_ids: tuple[str, ...],
    job: JobRecord | None,
) -> list[str]:
    problems: list[str] = []
    if artifact_job_id is None or document.provenance.job_id != artifact_job_id:
        problems.append("candidate provenance job does not match the artifact row")
    if artifact_provenance_job_id != artifact_job_id:
        problems.append("artifact provenance job does not match the artifact row")
    if record.job_id != artifact_job_id:
        problems.append("sidecar job_id does not match the artifact row")
    if document.source_asset_id not in artifact_source_ids:
        problems.append("candidate artifact provenance does not name this source")
    if artifact_inputs_sha256 != document.candidate_input_sha256:
        problems.append("artifact input digest does not match the candidate document")
    if job is None or job.job_id != artifact_job_id:
        problems.append("producing candidate job is missing")
        return problems
    if job.kind != JOB_CANDIDATE or job.status is not JobStatus.SUCCEEDED:
        problems.append(
            f"producing job {job.job_id} is {job.kind}/{job.status.value}, expected candidate_mine/succeeded"
        )
    if job.project_id != document.project_id:
        problems.append("producing candidate job is in another project")
    if job.payload.get("mining_id") != document.mining_id:
        problems.append("producing job mining_id does not match the candidate document")
    if job.payload.get("selected_count") != str(document.summary.selected_count):
        problems.append("producing job selected_count does not match the candidate document")
    expected = {
        "source_asset_id": document.source_asset_id,
        "source_sha256": document.source_sha256,
        "transcript_id": document.transcript_id,
        "transcript_sha256": document.transcript_sha256,
        "transcript_job_id": document.transcript_job_id,
        "visual_analysis_id": document.visual_analysis_id,
        "visual_analysis_sha256": document.visual_analysis_sha256,
        "visual_job_id": document.visual_job_id,
        "candidate_input_sha256": document.candidate_input_sha256,
        "recipe_version": document.recipe_version,
        "profile_fingerprint": document.profile_fingerprint,
    }
    for key, wanted in expected.items():
        if job.payload.get(key) != wanted:
            problems.append(f"producing job {key} does not match the candidate document")
    return problems


def _path_problems(
    document: CandidateMiningDocument,
    candidate_path: Path,
    artifact_uri: str,
    work_root: Path,
    workspace: SourceWorkspace,
) -> list[str]:
    try:
        uri_path = path_from_file_uri(artifact_uri)
        ensure_within(work_root, uri_path)
        ensure_within(work_root, candidate_path)
    except MediaError as exc:
        return [str(exc)]
    expected = workspace.candidate_run_dir(document.mining_id) / "candidates.json"
    if candidate_path != expected or uri_path != expected:
        return ["candidate artifact is not the candidates.json file inside this source's mining run"]
    if candidate_path.is_symlink() or not candidate_path.is_file():
        return ["candidate artifact path is missing or is a symlink"]
    return []


def _reference_problems(
    document: CandidateMiningDocument,
    transcript: Transcript,
    visual: VisualAnalysisDocument,
) -> list[str]:
    problems: list[str] = []
    segments = {segment.segment_id: segment for segment in transcript.segments}
    words = {word.word_id: word for segment in transcript.segments for word in segment.words}
    scenes = {scene.scene_id: scene for scene in visual.scenes}
    frames = {frame.frame_id: frame for frame in visual.frame_evidence}
    faces = {face.observation_id: face for face in visual.face_observations}
    for bundle in document.evidence_bundles:
        for segment_id in bundle.transcript_segment_ids:
            segment = segments.get(segment_id)
            if segment is None:
                problems.append(f"candidate references unknown transcript segment {segment_id}")
                continue
            if (
                intersection_us(
                    bundle.source_start_us,
                    bundle.source_end_us,
                    segment.start_us,
                    segment.end_us,
                )
                <= 0
            ):
                problems.append(f"transcript segment {segment_id} does not overlap the candidate")
        for word_id in bundle.transcript_word_ids:
            word = words.get(word_id)
            if word is None:
                problems.append(f"candidate references unknown transcript word {word_id}")
                continue
            owner = next(
                (
                    segment.segment_id
                    for segment in transcript.segments
                    if any(item.word_id == word_id for item in segment.words)
                ),
                None,
            )
            if owner not in bundle.transcript_segment_ids:
                problems.append(f"transcript word {word_id} is not in an included segment")
            if word.start_us >= bundle.source_end_us or word.end_us <= bundle.source_start_us:
                problems.append(f"transcript word {word_id} does not overlap the candidate")
        for scene_id in bundle.visual_scene_ids:
            scene = scenes.get(scene_id)
            if scene is None:
                problems.append(f"candidate references unknown visual scene {scene_id}")
                continue
            if (
                intersection_us(
                    bundle.source_start_us,
                    bundle.source_end_us,
                    scene.time_range.start_us,
                    scene.time_range.end_us,
                )
                <= 0
            ):
                problems.append(f"visual scene {scene_id} does not overlap the candidate")
        for frame_id in bundle.representative_frame_ids:
            frame = frames.get(frame_id)
            if frame is None:
                problems.append(f"candidate references unknown representative frame {frame_id}")
                continue
            if frame.scene_id not in bundle.visual_scene_ids:
                problems.append(f"representative frame {frame_id} is not in an overlapping scene")
            if not bundle.source_start_us <= frame.actual_timestamp_us < bundle.source_end_us:
                problems.append(f"representative frame {frame_id} is outside the candidate interval")
        for face_id in bundle.face_observation_ids:
            if face_id not in faces:
                problems.append(f"candidate references unknown face observation {face_id}")
        for detail in (bundle.transcript_excerpt,):
            problems.extend(_banned(detail))
    for candidate in document.candidates:
        for evidence in candidate.evidence:
            problems.extend(_banned(evidence.detail))
    return problems


def _banned(text: str) -> list[str]:
    lowered = text.casefold()
    return [f"candidate text claims speaker identity ({phrase})" for phrase in _BANNED if phrase in lowered]
