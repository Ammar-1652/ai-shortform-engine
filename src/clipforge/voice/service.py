"""Store narration as a normal artifact. Generation does not approve a Hero."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from clipforge.jobs.promote import PromotionError, promote
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_to_file_uri
from clipforge.media.workspace import ensure_within
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.voice import NarrationAudioArtifact, NarrationRequest
from clipforge.storage import Database, get_artifact, get_job, insert_artifact, insert_job
from clipforge.voice.audio import VoiceError, duration_is_acceptable, probe_file
from clipforge.voice.provider import FakeVoiceProvider, VoiceProvider

KIND = "narration_audio"


def doctor_text(provider: VoiceProvider) -> str:
    return provider.doctor()


def capability_text(provider: VoiceProvider) -> str:
    payload = provider.capabilities()
    return json.dumps(payload, sort_keys=True)


def generate_narration(
    database: Database,
    work_root: Path,
    request: NarrationRequest,
    provider: VoiceProvider,
    *,
    sidecar_hook: object | None = None,
) -> NarrationAudioArtifact:
    """Create one narration asset, or return the cached asset when identity matches."""
    root = work_root.resolve()
    cached = _cache_hit(database, root, request)
    if cached is not None:
        return cached
    payload = provider.generate(request)
    provider.verify_audio(payload)
    now = datetime.now(UTC)
    artifact_id = str(uuid4())
    job_id = str(uuid4())
    destination = _audio_path(root, artifact_id)
    partial = destination.with_suffix(".wav.partial")
    _reject_links(root, destination)
    ensure_within(root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(payload)
    measured = probe_file(partial)
    rate, channels, duration_us, codec = measured
    if rate != request.sample_rate or channels != request.channels:
        partial.unlink(missing_ok=True)
        raise VoiceError("narration sample rate or channel count does not match the request")
    if codec != "pcm_s16le":
        partial.unlink(missing_ok=True)
        raise VoiceError("narration codec is not pcm_s16le")
    duration_is_acceptable(
        actual_us=duration_us,
        target_us=request.target_duration_us,
        tolerance_us=request.duration_tolerance_us,
        policy=request.timing_policy,
    )
    digest = sha256_file(partial)
    cache_id = _cache_id(request)
    document = NarrationAudioArtifact(
        artifact_id=artifact_id,
        project_id=request.project_id,
        source_asset_id=request.source_asset_id,
        hero_id=request.hero_id,
        provider_id=request.provider_id,
        voice_profile_id=request.voice_profile_id,
        engine_id=request.profile.engine_id,
        model_id=request.profile.model_id,
        model_revision=request.profile.model_revision,
        script_sha256=request.script_sha256,
        script_label=request.script_text if len(request.script_text) <= 80 else request.script_text[:80],
        audio_sha256=digest,
        size_bytes=partial.stat().st_size,
        duration_us=duration_us,
        sample_rate=rate,
        channels=channels,
        codec=codec,
        language=request.language,
        provider_version=request.profile.provider_version,
        consent_record_id=request.profile.consent_record_id,
        license_evidence_id=request.profile.license_evidence_id,
        model_license=request.profile.model_license,
        commercial_use=request.profile.commercial_use,
        cache_id=cache_id,
        job_id=job_id,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=request.created_by,
            tool="clipforge-voice",
            tool_version="0",
            source_asset_ids=[request.source_asset_id],
            job_id=job_id,
            inputs_sha256=digest,
        ),
    )
    _public_document(document)
    sidecar = _sidecar_path(root, artifact_id)
    previous = sidecar.read_bytes() if sidecar.is_file() and not sidecar.is_symlink() else None
    replaced = False

    def write_output() -> None:
        return None

    def write_manifest() -> None:
        NarrationAudioArtifact.model_validate_json(document.model_dump_json())

    def commit_database() -> None:
        with database.transaction() as connection:
            insert_job(
                connection,
                JobRecord(
                    job_id=job_id,
                    project_id=request.project_id,
                    kind="narration_generate",
                    status=JobStatus.SUCCEEDED,
                    created_at=now,
                    updated_at=now,
                    payload={
                        "source_asset_id": request.source_asset_id,
                        "artifact_id": artifact_id,
                        "cache_id": cache_id,
                    },
                ),
            )
            insert_artifact(
                connection,
                artifact_id=artifact_id,
                project_id=request.project_id,
                job_id=job_id,
                source_asset_id=request.source_asset_id,
                kind=KIND,
                uri=path_to_file_uri(destination),
                provenance=document.provenance,
            )
            if sidecar_hook is not None:
                if not callable(sidecar_hook):
                    raise VoiceError("sidecar hook is not callable")
                sidecar_hook()
            partial.replace(destination)
            nonlocal replaced
            replaced = True
            text = document.model_dump_json() + "\n"
            sidecar.write_text(text, encoding="utf-8")
            cache = _cache_file(root, cache_id)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")

    def rollback() -> None:
        if partial.is_file() and not partial.is_symlink():
            partial.unlink()
        if replaced and destination.is_file() and not destination.is_symlink() and previous is None:
            destination.unlink()
        if previous is None:
            if sidecar.is_file() and not sidecar.is_symlink():
                sidecar.unlink()
        elif replaced:
            sidecar.write_bytes(previous)

    def write_sidecar() -> None:
        return None

    try:
        promote(
            write_output=write_output,
            write_manifest=write_manifest,
            commit_database=commit_database,
            write_sidecar=write_sidecar,
            rollback_database=rollback,
        )
    except PromotionError as exc:
        raise VoiceError("narration sidecar was not saved") from exc
    return document


def verify_narration(database: Database, work_root: Path, artifact_id: str) -> str:
    """Re-read one narration asset. This does not generate audio."""
    root = work_root.resolve()
    document = _load(root, artifact_id)
    path = _audio_path(root, artifact_id)
    if path.is_symlink() or not path.is_file():
        raise VoiceError("narration audio is missing")
    digest = sha256_file(path)
    if digest != document.audio_sha256 or path.stat().st_size != document.size_bytes:
        raise VoiceError("narration audio hash does not match")
    rate, channels, duration_us, codec = probe_file(path)
    if (rate, channels, codec) != (document.sample_rate, document.channels, document.codec):
        raise VoiceError("narration measurements do not match")
    if abs(duration_us - document.duration_us) > 1_000:
        raise VoiceError("narration duration does not match")
    with database.connect() as connection:
        artifact = get_artifact(connection, artifact_id)
        job = get_job(connection, document.job_id)
    if artifact.project_id != document.project_id or artifact.source_asset_id != document.source_asset_id:
        raise VoiceError("narration artifact lineage does not match")
    if artifact.kind != KIND or job.status is not JobStatus.SUCCEEDED:
        raise VoiceError("narration producer is not a succeeded job")
    if job.project_id != document.project_id:
        raise VoiceError("narration job belongs to a different project")
    _public_document(document)
    return "PASS narration"


def list_narration(database: Database, project_id: str) -> list[str]:
    with database.connect() as connection:
        rows = connection.execute(
            """
            SELECT artifact_id FROM artifacts
            WHERE project_id = ? AND kind = ?
            ORDER BY created_at, artifact_id
            """,
            (project_id, KIND),
        ).fetchall()
    return [str(row["artifact_id"]) for row in rows]


def require_bound_narration(
    database: Database,
    work_root: Path,
    artifact_id: str,
    *,
    project_id: str,
    source_asset_id: str,
    target_duration_us: int,
) -> tuple[str, Path]:
    """Check a narration asset before an advanced job is inserted."""
    text = verify_narration(database, work_root, artifact_id)
    if not text.startswith("PASS"):
        raise VoiceError("narration asset did not verify")
    document = _load(work_root.resolve(), artifact_id)
    if document.project_id != project_id or document.source_asset_id != source_asset_id:
        raise VoiceError("narration asset belongs to a different project or source")
    # The advanced render currently declares the whole edit as the narration window.
    # Refuse implicit padding, truncation, stretching, or looping in either direction.
    if abs(document.duration_us - target_duration_us) > 100_000:
        raise VoiceError("narration duration does not match the advanced plan")
    path = _audio_path(work_root.resolve(), artifact_id)
    return document.audio_sha256, path


def _cache_hit(database: Database, root: Path, request: NarrationRequest) -> NarrationAudioArtifact | None:
    cache_id = _cache_id(request)
    sidecar = _cache_file(root, cache_id)
    if sidecar.is_symlink() or not sidecar.is_file():
        return None
    try:
        document = NarrationAudioArtifact.model_validate_json(sidecar.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if document.cache_id != cache_id or document.script_sha256 != request.script_sha256:
        return None
    try:
        verify_narration(database, root, document.artifact_id)
    except VoiceError:
        return None
    return document


def _cache_id(request: NarrationRequest) -> str:
    body = {
        "project_id": request.project_id,
        "source_asset_id": request.source_asset_id,
        "candidate_id": request.candidate_id,
        "hero_id": request.hero_id,
        "provider_id": request.provider_id,
        "provider_version": request.profile.provider_version,
        "engine_id": request.profile.engine_id,
        "model_id": request.profile.model_id,
        "model_revision": request.profile.model_revision,
        "voice_profile_id": request.voice_profile_id,
        "script_sha256": request.script_sha256,
        "language": request.language,
        "sample_rate": request.sample_rate,
        "channels": request.channels,
        "timing_policy": request.timing_policy,
        "target_duration_us": request.target_duration_us,
        "output_format": request.output_format,
        "conversion_recipe": request.conversion_recipe,
        "model_license": request.profile.model_license,
        "commercial_use": request.profile.commercial_use,
        "consent_record_id": request.profile.consent_record_id,
        "license_evidence_id": request.profile.license_evidence_id,
        "output_use": request.output_use,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(root: Path, artifact_id: str) -> NarrationAudioArtifact:
    path = _sidecar_path(root, artifact_id)
    if path.is_symlink() or not path.is_file():
        raise VoiceError("narration record is missing")
    try:
        return NarrationAudioArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VoiceError("narration record could not be read") from exc


def _public_document(document: NarrationAudioArtifact) -> None:
    text = document.model_dump_json()
    if any(token in text.lower() for token in ("/tmp/", "/home/", "/users/", "://", "viewer_id")):
        raise VoiceError("narration record contains a forbidden token")


def _cache_file(root: Path, cache_id: str) -> Path:
    _safe(cache_id)
    return root / "voice" / "cache" / f"{cache_id}.json"


def _audio_path(root: Path, artifact_id: str) -> Path:
    _safe(artifact_id)
    return root / "voice" / "audio" / f"{artifact_id}.wav"


def _sidecar_path(root: Path, artifact_id: str) -> Path:
    _safe(artifact_id)
    return root / "voice" / "audio" / f"{artifact_id}.json"


def _safe(artifact_id: str) -> None:
    if "/" in artifact_id or "\\" in artifact_id or ".." in artifact_id:
        raise VoiceError("narration id is not a safe identifier")


def _reject_links(root: Path, destination: Path) -> None:
    current = root
    for part in ("voice", "audio"):
        current = current / part
        if current.is_symlink():
            raise VoiceError("voice directory is a symlink")
    if destination.is_symlink():
        raise VoiceError("narration audio is a symlink")


def fake_provider() -> FakeVoiceProvider:
    return FakeVoiceProvider()
