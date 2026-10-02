"""One check for a stored first-pass transcript.

Cache turns any problem into a miss. Verify prints the same problem as FAIL.
The generic Transcript schema still allows older documents to omit Round 3
fields. A reusable faster-whisper artifact may not.
"""

from __future__ import annotations

from clipforge.schemas.ingest import SourceIngestManifest
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import Transcript
from clipforge.schemas.transcription import TranscriptionCacheRecord
from clipforge.transcription.constants import JOB_TRANSCRIBE, RECIPE_VERSION
from clipforge.transcription.profile import DecodingProfile

_PAYLOAD_KEYS = (
    "source_asset_id",
    "source_sha256",
    "asr_audio_sha256",
    "model_revision",
    "device",
    "compute_type",
    "language",
    "recipe_version",
)


def document_sidecar_problems(
    document: Transcript,
    record: TranscriptionCacheRecord,
    manifest: SourceIngestManifest | None = None,
) -> list[str]:
    """Return why this document and sidecar are not one inference."""
    problems: list[str] = []
    problems.extend(_missing_round3_fields(document))
    if document.transcript_id != record.transcript_id:
        problems.append("sidecar transcript_id does not match the transcript document")
    if document.provenance.job_id != record.job_id:
        problems.append("sidecar job_id does not match the transcript provenance job")
    if document.asr_model != record.model_requested:
        problems.append("document model does not match the sidecar model")
    if document.model_revision != record.model_revision:
        problems.append("document model revision does not match the sidecar")
    if document.model_source != record.model_source:
        problems.append("document model source does not match the sidecar")
    if document.faster_whisper_version != record.faster_whisper_version:
        problems.append("document faster-whisper version does not match the sidecar")
    if document.ctranslate2_version != record.ctranslate2_version:
        problems.append("document CTranslate2 version does not match the sidecar")
    if document.device != record.device:
        problems.append("document device does not match the sidecar")
    if document.compute_type != record.compute_type:
        problems.append("document compute type does not match the sidecar")
    if document.language_requested != record.language:
        problems.append("document language does not match the sidecar")
    if document.word_timestamps is not True:
        problems.append("document word timestamps are not enabled")
    if document.asr_audio_sha256 != record.input_audio_sha256:
        problems.append("document ASR hash does not match the sidecar")
    if document.alignment != "approximate" or document.timing_quality != "provisional":
        problems.append("first-pass transcript must stay provisional")
    if manifest is not None and document.canonical_duration_us != manifest.canonical_duration_us:
        problems.append("transcript duration does not match the source manifest")
    fingerprint = _document_fingerprint(document)
    if fingerprint is None:
        problems.append("document decoding settings cannot be fingerprinted")
    elif fingerprint != record.decoding_fingerprint:
        problems.append("document decoding settings do not match the sidecar fingerprint")
    return problems


def producer_binding_problems(
    *,
    document: Transcript,
    record: TranscriptionCacheRecord,
    manifest: SourceIngestManifest,
    current_asr_sha256: str,
    artifact_job_id: str | None,
    artifact_provenance_job_id: str | None,
    artifact_inputs_sha256: str | None,
    artifact_source_ids: tuple[str, ...],
    job: JobRecord | None,
) -> list[str]:
    """Return why the files are not the exact output of the recorded job and ASR audio."""
    problems: list[str] = []
    if artifact_job_id is None:
        problems.append("transcript artifact row is missing")
        return problems
    if document.provenance.job_id != artifact_job_id:
        problems.append("document provenance job does not match the artifact row")
    if artifact_provenance_job_id != artifact_job_id:
        problems.append("artifact provenance job does not match the artifact row")
    if record.job_id != artifact_job_id:
        problems.append("sidecar job_id does not match the artifact row")
    if record.job_id != document.provenance.job_id:
        problems.append("sidecar job_id does not match the transcript provenance job")
    if manifest.source_asset_id not in artifact_source_ids:
        problems.append("artifact provenance does not name this source")
    if document.asr_audio_sha256 != current_asr_sha256:
        problems.append("transcript ASR hash does not match the current ASR audio")
    if record.input_audio_sha256 != current_asr_sha256:
        problems.append("sidecar ASR hash does not match the current ASR audio")
    if document.provenance.inputs_sha256 != current_asr_sha256:
        problems.append("transcript provenance input digest does not match the current ASR audio")
    if artifact_inputs_sha256 != current_asr_sha256:
        problems.append("artifact provenance input digest does not match the current ASR audio")
    if job is None or job.job_id != artifact_job_id:
        problems.append("producing transcription job does not match the artifact row")
        return problems
    if job.kind != JOB_TRANSCRIBE or job.status is not JobStatus.SUCCEEDED:
        problems.append(
            f"producing job {job.job_id} is {job.kind}/{job.status.value}, expected transcribe/succeeded"
        )
    if job.project_id != manifest.project_id:
        problems.append("producing job is in another project")
    if job.payload.get("transcript_id") != document.transcript_id:
        problems.append("producing job transcript_id does not match the transcript document")
    problems.extend(_payload_problems(job, document, record, manifest, current_asr_sha256))
    return problems


def _missing_round3_fields(document: Transcript) -> list[str]:
    required = {
        "canonical_duration_us": document.canonical_duration_us,
        "asr_audio_sha256": document.asr_audio_sha256,
        "asr_recipe_name": document.asr_recipe_name,
        "asr_recipe_version": document.asr_recipe_version,
        "engine": document.engine,
        "faster_whisper_version": document.faster_whisper_version,
        "ctranslate2_version": document.ctranslate2_version,
        "model_revision": document.model_revision,
        "model_source": document.model_source,
        "device_requested": document.device_requested,
        "device": document.device,
        "compute_type": document.compute_type,
        "language_requested": document.language_requested,
        "beam_size": document.beam_size,
        "temperature": document.temperature,
        "detected_language": document.detected_language,
        "language_probability": document.language_probability,
        "speech_detected": document.speech_detected,
        "segment_count": document.segment_count,
        "word_count": document.word_count,
    }
    missing = [name for name, value in required.items() if value is None or value == ""]
    if document.engine not in {None, "faster-whisper"}:
        return [f"engine is {document.engine}, expected faster-whisper"]
    if not missing:
        return []
    return ["transcript is missing Round 3 fields: " + ", ".join(dict.fromkeys(missing))]


def _document_fingerprint(document: Transcript) -> str | None:
    if (
        document.beam_size is None
        or document.temperature is None
        or document.language_requested is None
        or document.word_timestamps is not True
    ):
        return None
    profile = DecodingProfile(
        task="transcribe",
        beam_size=document.beam_size,
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=document.condition_on_previous_text,
        temperature=document.temperature,
        language=document.language_requested,
    )
    return profile.fingerprint()


def _payload_problems(
    job: JobRecord,
    document: Transcript,
    record: TranscriptionCacheRecord,
    manifest: SourceIngestManifest,
    current_asr_sha256: str,
) -> list[str]:
    expected = {
        "source_asset_id": manifest.source_asset_id,
        "source_sha256": manifest.content_sha256,
        "asr_audio_sha256": current_asr_sha256,
        "model_revision": document.model_revision,
        "device": document.device,
        "compute_type": document.compute_type,
        "language": document.language_requested,
        "recipe_version": RECIPE_VERSION,
    }
    problems: list[str] = []
    for key in _PAYLOAD_KEYS:
        if key not in job.payload:
            continue
        if key == "recipe_version" and job.payload[key] != record.recipe_version:
            problems.append("producing job recipe_version does not match the sidecar")
            continue
        if key == "source_sha256" and job.payload[key] != record.source_sha256:
            problems.append("producing job source_sha256 does not match the sidecar")
            continue
        wanted = expected[key]
        if wanted is not None and job.payload[key] != wanted:
            problems.append(f"producing job {key} does not match the stored transcript")
    return problems
