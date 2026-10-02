"""Synthetic transcript and visual documents for candidate tests. No copied source text."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from clipforge.media.hashing import sha256_file
from clipforge.schemas.common import SCHEMA_VERSION
from clipforge.schemas.governance import AssetLicenseRecord, RightsStatus
from clipforge.schemas.ingest import (
    AudioStreamInfo,
    FrameTimingClass,
    HdrSignal,
    MediaClassification,
    MediaFormatInfo,
    MediaTimelineInfo,
    NormalizedMediaProbe,
    RationalNumber,
    SourceIngestManifest,
    StreamSelection,
    VideoStreamInfo,
)
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.schemas.media import (
    FaceObservation,
    Scene,
    SegmentDiagnostics,
    SourceAsset,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.time import SourceTimeRange
from clipforge.schemas.transcription import TranscriptionCacheRecord
from clipforge.schemas.vision import (
    ContactSheet,
    EvidenceFile,
    FaceDetectionSample,
    FrameEvidence,
    FrameVisualMetrics,
    NormalizedBoundingBox,
    SceneVisualEvidence,
    VisualAnalysisCacheRecord,
    VisualAnalysisDocument,
    VisualAnalysisSummary,
    digest_evidence,
)
from clipforge.transcription.constants import RECIPE_NAME as TRANSCRIPT_RECIPE
from clipforge.transcription.constants import RECIPE_VERSION as TRANSCRIPT_RECIPE_VERSION
from clipforge.transcription.profile import DecodingProfile
from clipforge.vision.constants import (
    ADAPTIVE_THRESHOLD,
    FACE_SAMPLE_INTERVAL_US,
    JPEG_LONG_EDGE,
    JPEG_QUALITY,
    MIN_CONTENT_VAL,
    MIN_DETECTION_CONFIDENCE,
    MIN_SCENE_LEN_FRAMES,
    MIN_SUPPRESSION_THRESHOLD,
    REPRESENTATIVE_FRACTIONS,
    SCENE_BACKEND,
    SCENE_DETECTOR,
    SHORT_SCENE_US,
    TRACKING_CENTER_DISTANCE,
    TRACKING_IOU_THRESHOLD,
    TRACKING_MAX_GAP_US,
    WINDOW_WIDTH,
)
from clipforge.vision.constants import (
    RECIPE_NAME as VISUAL_RECIPE,
)
from clipforge.vision.constants import (
    RECIPE_VERSION as VISUAL_RECIPE_VERSION,
)
from clipforge.vision.profile import (
    face_fingerprint,
    sampling_fingerprint,
    scene_fingerprint,
    tracking_fingerprint,
)

STAMP = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
PROJECT_ID = "project-1"
SOURCE_ID = "source-1"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def provenance(source_id: str, job_id: str, inputs: str | None = None) -> ArtifactProvenance:
    return ArtifactProvenance(
        created_at=STAMP,
        created_by="tester",
        tool="pytest",
        tool_version="0.1.0",
        source_asset_ids=[source_id],
        job_id=job_id,
        inputs_sha256=inputs,
    )


def segment(
    ordinal: int,
    start_us: int,
    end_us: int,
    text: str,
    *,
    confidence: float | None = 0.9,
    diagnostics: bool = True,
    words: bool = True,
) -> TranscriptSegment:
    built: list[TranscriptWord] = []
    if words:
        tokens = text.split()
        span = end_us - start_us
        step = max(1, span // len(tokens))
        cursor = start_us
        for index, token in enumerate(tokens):
            word_end = end_us if index == len(tokens) - 1 else min(end_us, cursor + step)
            if word_end <= cursor:
                word_end = min(end_us, cursor + 1)
            built.append(
                TranscriptWord(
                    word_id=f"w-{ordinal}-{index}",
                    text=token if index == 0 else f" {token}",
                    start_us=cursor,
                    end_us=word_end,
                    confidence=confidence,
                )
            )
            cursor = word_end
    return TranscriptSegment(
        segment_id=f"seg-{ordinal}",
        ordinal=ordinal,
        start_us=start_us,
        end_us=end_us,
        text=text,
        words=built,
        diagnostics=(
            SegmentDiagnostics(avg_logprob=-0.2, no_speech_prob=0.01, compression_ratio=1.4, temperature=0.0)
            if diagnostics
            else None
        ),
    )


def transcript_document(
    segments: list[TranscriptSegment],
    duration_us: int,
    *,
    source_id: str = SOURCE_ID,
    project_id: str = PROJECT_ID,
    asr_sha256: str,
    job_id: str = "job-transcript",
    transcript_id: str = "transcript-1",
) -> Transcript:
    words = sum(len(item.words) for item in segments)
    profile = DecodingProfile(
        task="transcribe",
        beam_size=5,
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=True,
        temperature=0.0,
        language="en",
    )
    return Transcript(
        transcript_id=transcript_id,
        project_id=project_id,
        source_asset_id=source_id,
        asr_model="small.en",
        alignment="approximate",
        segments=segments,
        provenance=provenance(source_id, job_id, asr_sha256),
        canonical_duration_us=duration_us,
        asr_audio_sha256=asr_sha256,
        asr_recipe_name="asr-audio",
        asr_recipe_version="1",
        engine="faster-whisper",
        faster_whisper_version="1.2.1",
        ctranslate2_version="4.6.0",
        model_revision="rev-test",
        model_source="local_directory",
        device_requested="cpu",
        device="cpu",
        compute_type="int8",
        language_requested="en",
        beam_size=5,
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=True,
        temperature=0.0,
        detected_language="en",
        language_probability=0.99 if segments else 0.0,
        speech_detected=bool(segments),
        segment_count=len(segments),
        word_count=words,
        first_speech_us=segments[0].start_us if segments else None,
        last_speech_us=segments[-1].end_us if segments else None,
        speech_span_us=(segments[-1].end_us - segments[0].start_us) if segments else None,
        timing_adjustments=[profile.fingerprint()],
    )


def transcript_sidecar(
    document: Transcript,
    *,
    source_sha256: str,
    digest: str,
    size: int,
) -> TranscriptionCacheRecord:
    assert document.beam_size is not None
    assert document.temperature is not None
    assert document.language_requested is not None
    fingerprint = DecodingProfile(
        task="transcribe",
        beam_size=document.beam_size,
        word_timestamps=True,
        vad_filter=False,
        condition_on_previous_text=document.condition_on_previous_text,
        temperature=document.temperature,
        language=document.language_requested,
    ).fingerprint()
    assert document.asr_audio_sha256 is not None
    assert document.provenance.job_id is not None
    return TranscriptionCacheRecord(
        project_id=document.project_id,
        source_asset_id=document.source_asset_id,
        transcript_id=document.transcript_id,
        job_id=document.provenance.job_id,
        source_sha256=source_sha256,
        input_audio_sha256=document.asr_audio_sha256,
        asr_recipe_name="asr-audio",
        asr_recipe_version="1",
        recipe_name=TRANSCRIPT_RECIPE,
        recipe_version=TRANSCRIPT_RECIPE_VERSION,
        faster_whisper_version=document.faster_whisper_version or "1.2.1",
        ctranslate2_version=document.ctranslate2_version or "4.6.0",
        model_requested=document.asr_model,
        model_revision=document.model_revision or "rev-test",
        model_source="local_directory",
        device="cpu",
        compute_type=document.compute_type or "int8",
        language=document.language_requested,
        decoding_fingerprint=fingerprint,
        artifact_sha256=digest,
        size_bytes=size,
        validation_status="passed",
        created_at=STAMP,
    )


def transcript_job(document: Transcript, source_sha256: str) -> JobRecord:
    assert document.provenance.job_id is not None
    assert document.asr_audio_sha256 is not None
    return JobRecord(
        job_id=document.provenance.job_id,
        project_id=document.project_id,
        kind="transcribe",
        status=JobStatus.SUCCEEDED,
        created_at=STAMP,
        updated_at=STAMP,
        payload={
            "source_asset_id": document.source_asset_id,
            "source_sha256": source_sha256,
            "asr_audio_sha256": document.asr_audio_sha256,
            "model_revision": document.model_revision or "",
            "device": document.device or "",
            "compute_type": document.compute_type or "",
            "language": document.language_requested or "",
            "recipe_version": TRANSCRIPT_RECIPE_VERSION,
            "transcript_id": document.transcript_id,
        },
    )


def visual_document(
    duration_us: int,
    scene_bounds: list[tuple[int, int]],
    *,
    source_id: str = SOURCE_ID,
    project_id: str = PROJECT_ID,
    source_sha256: str,
    proxy_sha256: str,
    job_id: str = "job-visual",
    analysis_id: str = "analysis-1",
    frame_times: list[int] | None = None,
    faces: bool = False,
    differences: list[float] | None = None,
    run_dir: Path | None = None,
) -> VisualAnalysisDocument:
    """Build one valid visual document. Evidence bytes are written when ``run_dir`` is set."""
    if not scene_bounds:
        scene_bounds = [(0, duration_us)]
    scenes: list[Scene] = []
    evidence: list[SceneVisualEvidence] = []
    frames: list[FrameEvidence] = []
    samples: list[FaceDetectionSample] = []
    observations: list[FaceObservation] = []
    files: list[EvidenceFile] = []
    frame_payload = b"representative-frame"
    sheet_payload = b"contact-sheet"
    frame_sha = sha256_bytes(frame_payload)
    sheet_sha = sha256_bytes(sheet_payload)
    if run_dir is not None:
        (run_dir / "frames").mkdir(parents=True, exist_ok=True)
        (run_dir / "contact-sheets").mkdir(parents=True, exist_ok=True)
    for index, (start, end) in enumerate(scene_bounds):
        scene_id = f"scene-{index}"
        evidence_id = f"scene-evidence-{index}"
        when = frame_times[index] if frame_times is not None else start + max(1, (end - start) // 2)
        if when >= end:
            when = end - 1
        relative = f"frames/frame-{index}.jpg"
        if run_dir is not None:
            (run_dir / relative).write_bytes(frame_payload)
            frame_sha = sha256_file(run_dir / relative)
        difference = None if differences is None else differences[index]
        frame = FrameEvidence(
            frame_id=f"frame-{index}",
            scene_id=scene_id,
            requested_us=when,
            matched_requests_us=[when],
            actual_timestamp_us=when,
            labels=["mid"],
            width=320,
            height=180,
            relative_path=relative,
            sha256=frame_sha,
            size_bytes=len(frame_payload),
            metrics=FrameVisualMetrics(
                mean_luma=40.0 + index,
                luma_stddev=5.0,
                sharpness_laplacian_variance=12.0,
                difference_from_previous_sample=difference,
            ),
        )
        frames.append(frame)
        files.append(
            EvidenceFile(
                relative_path=relative,
                sha256=frame_sha,
                size_bytes=len(frame_payload),
                kind="representative_frame",
                scene_id=scene_id,
                timestamp_us=when,
            )
        )
        scene_samples: list[FaceDetectionSample] = []
        if faces and end - start > 2:
            first = min(start + 1, end - 2)
            second = min(first + 1, end - 1)
            for sample_index, stamp in enumerate((first, second)):
                box = NormalizedBoundingBox(x=0.1 + (sample_index * 0.05), y=0.1, width=0.2, height=0.2)
                scene_samples.append(
                    FaceDetectionSample(
                        detection_id=f"det-{index}-{sample_index}",
                        scene_id=scene_id,
                        timestamp_us=stamp,
                        confidence=0.8,
                        bounding_box=box,
                        center_x=box.x + (box.width / 2),
                        center_y=box.y + (box.height / 2),
                        area_ratio=box.width * box.height,
                        track_id=f"track-{index}",
                    )
                )
            observations.append(
                FaceObservation(
                    observation_id=f"face-{index}",
                    source_asset_id=source_id,
                    time_range=SourceTimeRange(start_us=first, end_us=second),
                    track_id=f"track-{index}",
                    confidence=0.8,
                    provenance=provenance(source_id, job_id, proxy_sha256),
                )
            )
        samples.extend(scene_samples)
        tracked = 1 if scene_samples else 0
        largest = max((sample.area_ratio for sample in scene_samples), default=None)
        evidence.append(
            SceneVisualEvidence(
                evidence_id=evidence_id,
                scene_id=scene_id,
                representative_frame_ids=[frame.frame_id],
                duration_us=end - start,
                sample_count=1,
                face_sample_count=1,
                frames_with_faces=len({sample.timestamp_us for sample in scene_samples}),
                max_face_count=1 if scene_samples else 0,
                mean_luma=frame.metrics.mean_luma,
                mean_sharpness=frame.metrics.sharpness_laplacian_variance,
                mean_visual_difference=difference,
                largest_face_area_ratio_max=largest,
                tracked_face_count=tracked,
            )
        )
        scenes.append(
            Scene(
                scene_id=scene_id,
                source_asset_id=source_id,
                time_range=SourceTimeRange(start_us=start, end_us=end),
                visual_evidence=evidence_id,
                provenance=provenance(source_id, job_id, proxy_sha256),
            )
        )
    sheet_relative = "contact-sheets/sheet-0.jpg"
    if run_dir is not None:
        (run_dir / sheet_relative).write_bytes(sheet_payload)
        sheet_sha = sha256_file(run_dir / sheet_relative)
    files.append(
        EvidenceFile(
            relative_path=sheet_relative,
            sha256=sheet_sha,
            size_bytes=len(sheet_payload),
            kind="contact_sheet",
        )
    )
    durations = [end - start for start, end in scene_bounds]
    from decimal import ROUND_HALF_UP, Decimal

    mean = int((Decimal(sum(durations)) / Decimal(len(durations))).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    per_frame: dict[tuple[str, int], int] = {}
    for sample in samples:
        key = (sample.scene_id, sample.timestamp_us)
        per_frame[key] = per_frame.get(key, 0) + 1
    summary = VisualAnalysisSummary(
        scene_count=len(scenes),
        representative_frame_count=len(frames),
        face_sample_frame_count=len(scenes),
        face_detection_count=len(samples),
        face_track_count=len(observations),
        frames_with_faces=sum(1 for count in per_frame.values() if count > 0),
        max_simultaneous_faces=max(per_frame.values(), default=0),
        mean_scene_duration_us=mean,
        shortest_scene_duration_us=min(durations),
        longest_scene_duration_us=max(durations),
    )
    scene_fp = scene_fingerprint()
    sampling_fp = sampling_fingerprint()
    face_fp = face_fingerprint()
    tracking_fp = tracking_fingerprint()
    return VisualAnalysisDocument(
        analysis_id=analysis_id,
        project_id=project_id,
        source_asset_id=source_id,
        created_at=STAMP,
        canonical_duration_us=duration_us,
        source_sha256=source_sha256,
        proxy_sha256=proxy_sha256,
        proxy_recipe_name="analysis-proxy",
        proxy_recipe_version="1",
        proxy_width=320,
        proxy_height=180,
        recipe_name=VISUAL_RECIPE,
        recipe_version=VISUAL_RECIPE_VERSION,
        scene_engine="fake",
        pyscenedetect_version="0.7.1",
        scene_backend=SCENE_BACKEND,
        scene_detector=SCENE_DETECTOR,
        scene_profile_fingerprint=scene_fp,
        adaptive_threshold=ADAPTIVE_THRESHOLD,
        min_content_val=MIN_CONTENT_VAL,
        window_width=WINDOW_WIDTH,
        min_scene_len_frames=MIN_SCENE_LEN_FRAMES,
        sampling_profile_fingerprint=sampling_fp,
        representative_fractions=list(REPRESENTATIVE_FRACTIONS),
        short_scene_us=SHORT_SCENE_US,
        face_sample_interval_us=FACE_SAMPLE_INTERVAL_US,
        jpeg_quality=JPEG_QUALITY,
        jpeg_long_edge=JPEG_LONG_EDGE,
        pyav_version="14.0.0",
        opencv_version="4.10.0",
        face_engine="fake",
        mediapipe_version="1.0.1",
        face_model_filename="blaze_face_short_range.tflite",
        face_model_sha256="b" * 64,
        face_model_source="test",
        face_profile_fingerprint=face_fp,
        min_detection_confidence=MIN_DETECTION_CONFIDENCE,
        min_suppression_threshold=MIN_SUPPRESSION_THRESHOLD,
        tracking_profile_fingerprint=tracking_fp,
        tracking_iou_threshold=TRACKING_IOU_THRESHOLD,
        tracking_center_distance_threshold=TRACKING_CENTER_DISTANCE,
        tracking_max_gap_us=TRACKING_MAX_GAP_US,
        scenes=scenes,
        scene_evidence=evidence,
        frame_evidence=frames,
        face_detection_samples=samples,
        face_observations=observations,
        contact_sheets=[
            ContactSheet(
                relative_path=sheet_relative,
                sha256=sheet_sha,
                size_bytes=len(sheet_payload),
                width=640,
                height=360,
                scene_ordinals=list(range(len(scenes))),
            )
        ],
        evidence_files=files,
        evidence_manifest_digest=digest_evidence(files),
        summary=summary,
        provenance=provenance(source_id, job_id, proxy_sha256),
        schema_version=SCHEMA_VERSION,
    )


def visual_sidecar(
    document: VisualAnalysisDocument,
    *,
    digest: str,
    size: int,
) -> VisualAnalysisCacheRecord:
    assert document.provenance.job_id is not None
    return VisualAnalysisCacheRecord(
        project_id=document.project_id,
        source_asset_id=document.source_asset_id,
        analysis_id=document.analysis_id,
        job_id=document.provenance.job_id,
        source_sha256=document.source_sha256,
        proxy_sha256=document.proxy_sha256,
        proxy_recipe_name=document.proxy_recipe_name,
        proxy_recipe_version=document.proxy_recipe_version,
        recipe_name=document.recipe_name,
        recipe_version=document.recipe_version,
        pyscenedetect_version=document.pyscenedetect_version,
        scene_backend=document.scene_backend,
        scene_profile_fingerprint=document.scene_profile_fingerprint,
        pyav_version=document.pyav_version,
        opencv_version=document.opencv_version,
        mediapipe_version=document.mediapipe_version,
        face_model_sha256=document.face_model_sha256,
        face_profile_fingerprint=document.face_profile_fingerprint,
        sampling_profile_fingerprint=document.sampling_profile_fingerprint,
        tracking_profile_fingerprint=document.tracking_profile_fingerprint,
        analysis_artifact_sha256=digest,
        analysis_artifact_size=size,
        evidence_manifest_digest=document.evidence_manifest_digest,
        validation_status="passed",
        created_at=STAMP,
    )


def visual_job(document: VisualAnalysisDocument) -> JobRecord:
    assert document.provenance.job_id is not None
    return JobRecord(
        job_id=document.provenance.job_id,
        project_id=document.project_id,
        kind="visual_analyze",
        status=JobStatus.SUCCEEDED,
        created_at=STAMP,
        updated_at=STAMP,
        payload={
            "source_asset_id": document.source_asset_id,
            "source_sha256": document.source_sha256,
            "proxy_sha256": document.proxy_sha256,
            "recipe_version": document.recipe_version,
            "analysis_id": document.analysis_id,
        },
    )


def manifest(source_sha256: str, size: int, mtime_ns: int, duration_us: int) -> SourceIngestManifest:
    video = VideoStreamInfo(
        index=0,
        width=320,
        height=180,
        display_width=320,
        display_height=180,
        avg_frame_rate=RationalNumber(numerator=30, denominator=1),
        r_frame_rate=RationalNumber(numerator=30, denominator=1),
        time_base=RationalNumber(numerator=1, denominator=30),
        start_time_us=0,
        duration_ts=duration_us,
        duration_us=duration_us,
    )
    return SourceIngestManifest(
        source_asset_id=SOURCE_ID,
        project_id=PROJECT_ID,
        content_sha256=source_sha256,
        size_bytes=size,
        mtime_ns=mtime_ns,
        original_filename="source.bin",
        transcription_eligible=True,
        video_stream_index=0,
        audio_stream_index=1,
        canonical_duration_us=duration_us,
        video_origin_us=0,
        ingested_at=STAMP,
        probe=NormalizedMediaProbe(
            format=MediaFormatInfo(duration_us=duration_us),
            video_streams=[video],
            audio_streams=[AudioStreamInfo(index=1, sample_rate=16000, channels=1)],
            chapter_count=0,
            ffprobe_version="test",
            selection=StreamSelection(
                video_stream_index=0,
                audio_stream_index=1,
                video_selection="automatic",
                audio_selection="automatic",
            ),
            timeline=MediaTimelineInfo(
                video_origin_us=0,
                video_start_assumed_zero=False,
                audio_start_us=0,
                audio_offset_us=0,
                canonical_duration_us=duration_us,
                duration_evidence="selected_video_duration_ts",
            ),
            classification=MediaClassification(
                frame_timing=FrameTimingClass.CFR_LIKELY,
                hdr=HdrSignal.NONE,
                transcription_eligible=True,
            ),
        ),
    )


def owned_license() -> AssetLicenseRecord:
    return AssetLicenseRecord(
        license_record_id="lic-1",
        asset_id=SOURCE_ID,
        status=RightsStatus.OWNED,
        evidence_uri="file:///licenses/owned.txt",
        recorded_at=STAMP,
        recorded_by="tester",
    )


def source_asset(uri: str) -> SourceAsset:
    return SourceAsset(
        source_asset_id=SOURCE_ID,
        project_id=PROJECT_ID,
        uri=uri,
        license_record_id="lic-1",
        provenance=ArtifactProvenance(
            created_at=STAMP,
            created_by="tester",
            tool="pytest",
            tool_version="0.1.0",
            source_asset_ids=[SOURCE_ID],
        ),
    )
