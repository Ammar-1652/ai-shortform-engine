"""Fixtures for rough-preview tests. Upstream media bytes can be dummy files.

The fake renderer does not decode them. A real Remotion smoke test replaces
the proxy and the ASR audio with files ffmpeg can read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipforge.candidates.service import mine_source
from clipforge.media import recipes
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.media.workspace import SourceWorkspace
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.preview.service import render_previews
from clipforge.schemas.candidates import CandidateMiningProfile
from clipforge.schemas.ingest import DerivativeCacheRecord
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import TranscriptSegment
from clipforge.schemas.project import Project
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import (
    Database,
    insert_artifact,
    insert_asset_license_record,
    insert_job,
    insert_project,
    insert_source_asset,
    insert_source_manifest,
)
from clipforge.transcription.io import dump_json
from tests.candidate_support import (
    PROJECT_ID,
    SOURCE_ID,
    STAMP,
    manifest,
    owned_license,
    provenance,
    segment,
    source_asset,
    transcript_document,
    transcript_job,
    transcript_sidecar,
    visual_document,
    visual_job,
    visual_sidecar,
)


@dataclass(frozen=True, slots=True)
class PreviewFixture:
    database: Database
    work: Path
    source_path: Path
    workspace: SourceWorkspace


def short_profile(**overrides: object) -> CandidateMiningProfile:
    """One-second candidates so the fake encoder stays small. Still a real profile."""
    values: dict[str, object] = {
        "hard_min_duration_us": 1_000_000,
        "preferred_min_duration_us": 1_000_000,
        "preferred_max_duration_us": 1_500_000,
        "hard_max_duration_us": 2_000_000,
        "boundary_padding_us": 0,
        "soft_target_min": 0,
        "max_candidates": 25,
        "minimum_transcript_words": 5,
        "minimum_quality_coverage": 0.0,
        "pre_dedupe_pool_size": 200,
    }
    values.update(overrides)
    return CandidateMiningProfile(**values)  # type: ignore[arg-type]


def isolated_segments(count: int) -> tuple[list[TranscriptSegment], int]:
    """Non-overlapping spoken spans. Gaps are wider than the short hard maximum."""
    pieces: list[TranscriptSegment] = []
    for index in range(count):
        start = index * 4_000_000
        pieces.append(
            segment(
                index,
                start,
                start + 1_200_000,
                f"Point {index} explains one concrete method today.",
            )
        )
    if not pieces:
        return [], 30_000_000
    return pieces, pieces[-1].end_us + 1_000_000


def ready_stack(
    tmp_path: Path,
    *,
    segments: list[TranscriptSegment] | None = None,
    duration_us: int | None = None,
    proxy_bytes: bytes = b"proxy-bytes",
    asr_bytes: bytes = b"asr-bytes",
) -> PreviewFixture:
    spoken, implied = isolated_segments(1)
    pieces = spoken if segments is None else segments
    duration = implied if duration_us is None else duration_us
    if segments is not None and duration_us is None and pieces:
        duration = pieces[-1].end_us + 1_000_000
    tmp_path.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    source_path = tmp_path / "source.bin"
    source_path.write_bytes(b"source-bytes")
    source_sha = sha256_file(source_path)
    stat = source_path.stat()
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    workspace = SourceWorkspace(work, PROJECT_ID, SOURCE_ID)
    workspace.ensure()
    asr = workspace.audio_file("asr.flac")
    proxy = workspace.proxy_file("analysis.mp4")
    asr.write_bytes(asr_bytes)
    proxy.write_bytes(proxy_bytes)
    asr_sha = sha256_file(asr)
    proxy_sha = sha256_file(proxy)
    transcript = transcript_document(pieces, duration, asr_sha256=asr_sha)
    run = workspace.make_vision_run("analysis-1")
    visual = visual_document(
        duration,
        [(0, duration)],
        source_sha256=source_sha,
        proxy_sha256=proxy_sha,
        run_dir=run,
    )
    transcript_path = workspace.transcript_file()
    transcript_path.write_text(dump_json(transcript), encoding="utf-8")
    analysis_path = run / "analysis.json"
    analysis_path.write_text(dump_json(visual), encoding="utf-8")
    workspace.transcript_sidecar().write_text(
        dump_json(
            transcript_sidecar(
                transcript,
                source_sha256=source_sha,
                digest=sha256_file(transcript_path),
                size=transcript_path.stat().st_size,
            )
        ),
        encoding="utf-8",
    )
    workspace.vision_sidecar().write_text(
        dump_json(
            visual_sidecar(
                visual,
                digest=sha256_file(analysis_path),
                size=analysis_path.stat().st_size,
            )
        ),
        encoding="utf-8",
    )
    _write_derivative(
        workspace.metadata_file("analysis-proxy.recipe.json"),
        source_sha=source_sha,
        artifact=proxy,
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
    )
    _write_derivative(
        workspace.metadata_file("asr-audio.recipe.json"),
        source_sha=source_sha,
        artifact=asr,
        recipe_name=recipes.ASR_AUDIO_NAME,
        recipe_version=recipes.ASR_AUDIO_VERSION,
    )
    prepare = JobRecord(
        job_id="job-prepare",
        project_id=PROJECT_ID,
        kind=recipes.JOB_MEDIA_PREPARE,
        status=JobStatus.SUCCEEDED,
        created_at=STAMP,
        updated_at=STAMP,
        payload={"source_asset_id": SOURCE_ID, "source_sha256": source_sha},
    )
    project = Project(
        project_id=PROJECT_ID,
        name="Preview",
        created_at=STAMP,
        provenance=ArtifactProvenance(
            created_at=STAMP,
            created_by="tester",
            tool="pytest",
            tool_version="0.1.0",
        ),
    )
    with database.transaction() as connection:
        insert_project(connection, project)
        insert_asset_license_record(connection, owned_license())
        insert_source_asset(connection, source_asset(path_to_file_uri(source_path)))
        insert_source_manifest(connection, manifest(source_sha, stat.st_size, stat.st_mtime_ns, duration))
        insert_job(connection, prepare)
        insert_job(connection, transcript_job(transcript, source_sha))
        insert_job(connection, visual_job(visual))
        insert_artifact(
            connection,
            artifact_id="artifact-proxy",
            project_id=PROJECT_ID,
            job_id=prepare.job_id,
            source_asset_id=SOURCE_ID,
            kind=recipes.KIND_PROXY,
            uri=path_to_file_uri(proxy),
            provenance=provenance(SOURCE_ID, prepare.job_id, proxy_sha),
        )
        insert_artifact(
            connection,
            artifact_id="artifact-asr",
            project_id=PROJECT_ID,
            job_id=prepare.job_id,
            source_asset_id=SOURCE_ID,
            kind=recipes.KIND_ASR,
            uri=path_to_file_uri(asr),
            provenance=provenance(SOURCE_ID, prepare.job_id, asr_sha),
        )
        insert_artifact(
            connection,
            artifact_id="artifact-transcript",
            project_id=PROJECT_ID,
            job_id=transcript.provenance.job_id,
            source_asset_id=SOURCE_ID,
            kind="transcript_json",
            uri=path_to_file_uri(transcript_path),
            provenance=transcript.provenance,
        )
        insert_artifact(
            connection,
            artifact_id="artifact-visual",
            project_id=PROJECT_ID,
            job_id=visual.provenance.job_id,
            source_asset_id=SOURCE_ID,
            kind="visual_analysis_json",
            uri=path_to_file_uri(analysis_path),
            provenance=visual.provenance,
        )
    return PreviewFixture(database, work, source_path, workspace)


def mine(fixture: PreviewFixture, **kwargs: object):
    return mine_source(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        **kwargs,  # type: ignore[arg-type]
    )


def render(fixture: PreviewFixture, backend: FakeRoughRenderBackend | None = None, **kwargs: object):
    return render_previews(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        backend=backend,
        **kwargs,  # type: ignore[arg-type]
    )


def _write_derivative(
    path: Path,
    *,
    source_sha: str,
    artifact: Path,
    recipe_name: str,
    recipe_version: str,
) -> None:
    record = DerivativeCacheRecord(
        recipe_name=recipe_name,
        recipe_version=recipe_version,
        source_sha256=source_sha,
        project_id=PROJECT_ID,
        source_asset_id=SOURCE_ID,
        video_stream_index=0,
        audio_stream_index=1,
        artifact_sha256=sha256_file(artifact),
        size_bytes=artifact.stat().st_size,
        ffmpeg_version="test",
        arguments=["ffmpeg", "-i", "source.bin", artifact.name],
        validation_status="passed",
        created_at=STAMP,
    )
    path.write_text(dump_json(record), encoding="utf-8")
