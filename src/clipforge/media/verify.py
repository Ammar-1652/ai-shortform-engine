"""Inspect a prepared source. This command reports. It does not repair or transcode."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from clipforge.errors import ComplianceGateError, MediaError, StorageError
from clipforge.media import recipes
from clipforge.media.cache import cache_identity_matches, read_cache_record
from clipforge.media.clock import proxy_pixel_size
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.mutation import inspect_mutation
from clipforge.media.process import ProcessRunner
from clipforge.media.validate import validate_asr_audio, validate_proxy
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.governance import require_rights_cleared
from clipforge.schemas.ingest import SourceIngestManifest, VideoStreamInfo
from clipforge.storage import (
    Database,
    find_artifact,
    get_asset_license_record,
    get_job,
    get_source_asset,
    get_source_manifest,
)

Status = Literal["PASS", "WARN", "FAIL"]


@dataclass(frozen=True, slots=True)
class VerifyLine:
    status: Status
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class VerifyReport:
    source_asset_id: str
    lines: tuple[VerifyLine, ...]

    @property
    def status(self) -> Status:
        if any(line.status == "FAIL" for line in self.lines):
            return "FAIL"
        if any(line.status == "WARN" for line in self.lines):
            return "WARN"
        return "PASS"


def verify_source(
    *,
    database: Database,
    source_asset_id: str,
    work_root: Path,
    runner: ProcessRunner | None = None,
) -> VerifyReport:
    active = runner or ProcessRunner()
    lines: list[VerifyLine] = []
    with database.connect() as connection:
        source = get_source_asset(connection, source_asset_id)
        manifest = get_source_manifest(connection, source_asset_id)
        license_record = get_asset_license_record(connection, source.license_record_id)
        proxy_row = find_artifact(connection, source.project_id, source_asset_id, recipes.KIND_PROXY)
        audio_row = find_artifact(connection, source.project_id, source_asset_id, recipes.KIND_ASR)
        probe_row = find_artifact(connection, source.project_id, source_asset_id, recipes.KIND_PROBE)
    if source.project_id != manifest.project_id:
        lines.append(VerifyLine("FAIL", "project", "source and manifest name different projects"))
        return VerifyReport(source_asset_id, tuple(lines))
    lines.append(VerifyLine("PASS", "project", source.project_id))
    path = path_from_file_uri(source.uri)
    try:
        drift = inspect_mutation(path, manifest)
    except MediaError as exc:
        lines.append(VerifyLine("FAIL", "source", str(exc)))
        return VerifyReport(source_asset_id, tuple(lines))
    if drift is None:
        lines.append(VerifyLine("PASS", "mutation", "size and mtime match the ingest record"))
    else:
        lines.append(
            VerifyLine(
                "WARN",
                "mutation",
                "size or mtime changed but the SHA-256 still matches. Verify did not update the record.",
            )
        )
    try:
        require_rights_cleared(license_record)
    except ComplianceGateError as exc:
        lines.append(VerifyLine("FAIL", "rights", str(exc)))
    else:
        lines.append(
            VerifyLine(
                "PASS",
                "rights",
                f"{license_record.status.value}; evidence is recorded. This is not a new legal review.",
            )
        )
    lines.append(
        VerifyLine(
            "PASS",
            "probe",
            f"duration {manifest.canonical_duration_us} us, video {manifest.video_stream_index}, "
            f"audio {manifest.audio_stream_index}, {manifest.probe.classification.frame_timing.value}, "
            f"hdr {manifest.probe.classification.hdr.value}, "
            f"evidence {manifest.probe.timeline.duration_evidence}",
        )
    )
    if manifest.probe.classification.frame_timing.value == "vfr_possible":
        lines.append(
            VerifyLine(
                "WARN",
                "frame_timing",
                "avg_frame_rate and r_frame_rate differ. Treat this as VFR-possible and use timestamps.",
            )
        )
    if manifest.probe.classification.hdr.value != "none":
        lines.append(
            VerifyLine(
                "WARN",
                "hdr",
                "HDR metadata is present. Round 2 does not build an SDR proxy for it.",
            )
        )
    if probe_row is None:
        lines.append(VerifyLine("WARN", "ffprobe_artifact", "no ffprobe JSON artifact row"))
    elif (
        probe_row.project_id != source.project_id
        or source_asset_id not in probe_row.provenance.source_asset_ids
    ):
        lines.append(VerifyLine("FAIL", "ffprobe_artifact", "ffprobe artifact lineage does not match"))
    else:
        lines.append(VerifyLine("PASS", "ffprobe_artifact", probe_row.artifact_id))

    workspace = SourceWorkspace(work_root.resolve(), source.project_id, source_asset_id)
    video = _video(manifest)
    _check_derivative(
        lines,
        name="proxy",
        manifest=manifest,
        path=workspace.proxy_file("analysis.mp4"),
        sidecar=workspace.metadata_file("analysis-proxy.recipe.json"),
        recipe_name=recipes.ANALYSIS_PROXY_NAME,
        recipe_version=recipes.ANALYSIS_PROXY_VERSION,
        row_project=None if proxy_row is None else proxy_row.project_id,
        row_job=None if proxy_row is None else proxy_row.job_id,
        row_sources=() if proxy_row is None else tuple(proxy_row.provenance.source_asset_ids),
        row_provenance_job=None if proxy_row is None else proxy_row.provenance.job_id,
        source_project=source.project_id,
        database=database,
        validate=lambda: _validate_proxy(active, workspace, manifest, video),
        required=True,
    )
    if manifest.transcription_eligible:
        _check_derivative(
            lines,
            name="asr_audio",
            manifest=manifest,
            path=workspace.audio_file("asr.flac"),
            sidecar=workspace.metadata_file("asr-audio.recipe.json"),
            recipe_name=recipes.ASR_AUDIO_NAME,
            recipe_version=recipes.ASR_AUDIO_VERSION,
            row_project=None if audio_row is None else audio_row.project_id,
            row_job=None if audio_row is None else audio_row.job_id,
            row_sources=() if audio_row is None else tuple(audio_row.provenance.source_asset_ids),
            row_provenance_job=None if audio_row is None else audio_row.provenance.job_id,
            source_project=source.project_id,
            database=database,
            validate=lambda: validate_asr_audio(
                workspace.audio_file("asr.flac"),
                active,
                canonical_duration_us=manifest.canonical_duration_us,
                rate=None if video is None else (video.avg_frame_rate or video.r_frame_rate),
                log_path=None,
            ),
            required=True,
        )
    else:
        audio_path = workspace.audio_file("asr.flac")
        if audio_path.is_file() or audio_row is not None:
            lines.append(
                VerifyLine(
                    "FAIL",
                    "asr_audio",
                    "ASR audio exists for a source that is not transcription-eligible",
                )
            )
        else:
            lines.append(
                VerifyLine(
                    "PASS",
                    "asr_audio",
                    "no audio stream; ASR audio is not expected and was not fabricated",
                )
            )
    return VerifyReport(source_asset_id, tuple(lines))


def format_report(report: VerifyReport) -> str:
    lines = [f"status: {report.status}", f"source_asset_id: {report.source_asset_id}"]
    for line in report.lines:
        lines.append(f"[{line.status}] {line.name}: {line.detail}")
    return "\n".join(lines)


def _check_derivative(
    lines: list[VerifyLine],
    *,
    name: str,
    manifest: SourceIngestManifest,
    path: Path,
    sidecar: Path,
    recipe_name: str,
    recipe_version: str,
    row_project: str | None,
    row_job: str | None,
    row_sources: tuple[str, ...],
    row_provenance_job: str | None,
    source_project: str,
    database: Database,
    validate: Callable[[], object],
    required: bool,
) -> None:
    record = read_cache_record(sidecar)
    if record is None or not path.is_file():
        if required:
            lines.append(VerifyLine("FAIL", name, f"missing {path.name} or its recipe sidecar"))
        return
    if not cache_identity_matches(
        record,
        recipe_name=recipe_name,
        recipe_version=recipe_version,
        source_sha256=manifest.content_sha256,
        video_stream_index=manifest.video_stream_index,
        audio_stream_index=manifest.audio_stream_index,
        artifact_path=path,
    ):
        lines.append(VerifyLine("FAIL", name, "recipe, hash, size, or selected streams do not match the file"))
        return
    try:
        validate()
    except (MediaError, OSError) as exc:
        lines.append(VerifyLine("FAIL", name, str(exc)))
        return
    if row_project != source_project or manifest.source_asset_id not in row_sources:
        lines.append(VerifyLine("FAIL", name, "artifact row is missing or belongs to another project"))
        return
    if row_job is None or row_provenance_job != row_job:
        lines.append(VerifyLine("FAIL", name, "artifact job id does not match provenance.job_id"))
        return
    with database.connect() as connection:
        try:
            job = get_job(connection, row_job)
        except StorageError as exc:
            lines.append(VerifyLine("FAIL", name, str(exc)))
            return
    if job.project_id != source_project:
        lines.append(VerifyLine("FAIL", name, f"job {row_job} is in project {job.project_id}"))
        return
    expected_tool = recipes.recipe_id(recipe_name, recipe_version)
    if job.kind != recipes.JOB_MEDIA_PREPARE:
        lines.append(VerifyLine("FAIL", name, f"job kind is {job.kind}"))
        return
    lines.append(
        VerifyLine(
            "PASS",
            name,
            f"{path.name} sha256 {record.artifact_sha256[:12]} "
            f"recipe {expected_tool} bytes {record.size_bytes}",
        )
    )


def _validate_proxy(
    runner: ProcessRunner,
    workspace: SourceWorkspace,
    manifest: SourceIngestManifest,
    video: VideoStreamInfo | None,
) -> None:
    if video is None or video.display_width is None or video.display_height is None:
        raise MediaError("selected video has no display dimensions")
    output_width, output_height = proxy_pixel_size(video.display_width, video.display_height)
    validate_proxy(
        workspace.proxy_file("analysis.mp4"),
        runner,
        canonical_duration_us=manifest.canonical_duration_us,
        rate=video.avg_frame_rate or video.r_frame_rate,
        output_width=output_width,
        output_height=output_height,
        display_width=video.display_width,
        display_height=video.display_height,
        expect_audio=manifest.audio_stream_index is not None,
        log_path=None,
    )


def _video(manifest: SourceIngestManifest) -> VideoStreamInfo | None:
    for stream in manifest.probe.video_streams:
        if stream.index == manifest.video_stream_index:
            return stream
    return None
