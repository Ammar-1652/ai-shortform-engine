"""Collect encoded caption frames; speech accuracy remains a separate review."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from clipforge import __version__
from clipforge.campaign.speech import validate_speech_captions
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.hero.probe import probe_hero
from clipforge.media.hashing import sha256_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.preview.timing import frame_at_or_after
from clipforge.schemas.advanced import AdvancedHeroRenderInput, advanced_fingerprint
from clipforge.schemas.campaign import TarteelSpeechReview
from clipforge.schemas.caption_evidence import (
    CaptionAudioCoverageReport,
    CaptionCoverageFrame,
    CaptionFrameObservation,
)
from clipforge.schemas.hero import ForcedAlignmentDocument
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.render_checkpoint import AdvancedRenderAuthorization
from clipforge.schemas.time import TimeMapDocument, digest_time_map
from clipforge.timeline import FrameRate, frame_start_us
from clipforge.transcription.io import publish_json

CAPTION_EVIDENCE_RECIPE = "decoded-caption-edges-v2"


def _safe(root: Path, path: Path) -> Path:
    try:
        return confine_work_path(root, path.relative_to(root).as_posix(), label="caption evidence")
    except ValueError as exc:
        raise MediaError("caption evidence path escapes the work root") from exc


def caption_frame_samples(render_input: AdvancedHeroRenderInput) -> dict[int, list[CaptionFrameObservation]]:
    """Sample displayed cue boundaries and all word edges on the renderer grid.

    Short cues can have start/middle/end on the same frame. Keep every role;
    an adjacent cue can also start on the preceding cue's first absent frame.
    """
    total = render_input.duration_in_frames
    result: dict[int, list[CaptionFrameObservation]] = {}

    def add(frame: int, observation: CaptionFrameObservation) -> None:
        if 0 <= frame < total:
            result.setdefault(frame, []).append(observation)

    add(0, CaptionFrameObservation(phase="first"))
    add(total - 1, CaptionFrameObservation(phase="last"))
    if not render_input.captions:
        raise MediaError("caption evidence requires at least one rendered cue")
    for cue in render_input.captions:
        if not cue.words:
            raise MediaError(f"caption cue {cue.event_id} has no forced words")
        start = frame_at_or_after(cue.interval.output_start_us, total)
        # Remotion gives a positive sub-frame cue one complete output frame.
        # Evidence must sample the displayed interval, including that frame.
        endpoint = max(start + 1, frame_at_or_after(cue.interval.output_end_us, total))
        if start >= endpoint or cue.interval.output_end_us > render_input.output_duration_us:
            raise MediaError(f"caption cue {cue.event_id} owns no legal output frames")
        add(start - 1, CaptionFrameObservation(phase="before", cue_id=cue.event_id))
        add(start, CaptionFrameObservation(phase="start", cue_id=cue.event_id))
        add((start + endpoint - 1) // 2, CaptionFrameObservation(phase="middle", cue_id=cue.event_id))
        add(endpoint - 1, CaptionFrameObservation(phase="end", cue_id=cue.event_id))
        add(endpoint, CaptionFrameObservation(phase="after", cue_id=cue.event_id))
        for word in cue.words:
            if not 0 <= word.output_start_frame < word.output_end_frame_exclusive <= total:
                raise MediaError(f"caption word {word.word_id} is outside the output frames")
            add(
                word.output_start_frame,
                CaptionFrameObservation(phase="word_start", cue_id=cue.event_id, word_id=word.word_id),
            )
            add(
                word.output_end_frame_exclusive - 1,
                CaptionFrameObservation(phase="word_end", cue_id=cue.event_id, word_id=word.word_id),
            )
    return dict(sorted(result.items()))


def verify_caption_coverage_report(
    *,
    root: Path,
    run_dir: Path,
    output: Path,
    report: CaptionAudioCoverageReport,
    render_input: AdvancedHeroRenderInput,
    render_input_sha256: str,
    source_asset_id: str,
) -> None:
    """Recompute every required observation; existence of a PNG is not a pass."""
    if (
        report.candidate_id != render_input.candidate_id
        or report.source_asset_id != source_asset_id
        or report.source_sha256 != render_input.source_sha256
        or report.alignment_sha256 != render_input.alignment_sha256
        or report.time_map_sha256 != render_input.time_map_sha256
        or report.render_input_sha256 != render_input_sha256
        or report.encoded_media_sha256 != sha256_file(_safe(root, output))
        or report.output_frame_count != render_input.duration_in_frames
        or report.output_duration_us != render_input.output_duration_us
        or report.forced_word_ids != [word.word_id for cue in render_input.captions for word in cue.words]
        or report.caption_cue_ids != [cue.event_id for cue in render_input.captions]
    ):
        raise MediaError("caption evidence binding does not match the current encoded draft")
    probe_hero(_safe(root, output), expected_duration_us=render_input.output_duration_us)
    expected = caption_frame_samples(render_input)
    if {frame.frame_index: frame.observations for frame in report.frames} != expected:
        raise MediaError("caption evidence is missing required cue/word boundary observations")
    for frame in report.frames:
        if frame.output_time_us != frame_start_us(frame.frame_index, FrameRate(30, 1)):
            raise MediaError("caption evidence has a stale output clock")
        frame_path = _safe(root, run_dir / frame.relative_path)
        if not frame_path.is_file() or sha256_file(frame_path) != frame.sha256:
            raise MediaError("caption evidence decoded frame hash is stale")
    receipt_path = _safe(root, output.parent / "authorization.json")
    receipt = AdvancedRenderAuthorization.model_validate_json(receipt_path.read_text(encoding="utf-8"))
    item = next((item for item in receipt.items if item.candidate_id == render_input.candidate_id), None)
    if (
        item is None
        or receipt.source_asset_id != source_asset_id
        or receipt.source_sha256 != render_input.source_sha256
        or receipt.advanced_set_id != render_input.advanced_set_id
        or receipt.provenance.inputs_sha256 != item.input_sha256
        or item.input_sha256 != advanced_fingerprint(render_input.model_dump(mode="json"))
        or item.staged_sha256.get(render_input.speech_name) != report.staged_audio_sha256
    ):
        raise MediaError("caption evidence staged audio does not match this candidate's authorization")
    if report.speech_coverage_status == "complete":
        if not report.speech_review_relative_path or not report.speech_review_sha256:
            raise MediaError("complete caption evidence requires a speech review")
        speech_path = _safe(root, run_dir / report.speech_review_relative_path)
        if sha256_file(speech_path) != report.speech_review_sha256:
            raise MediaError("caption evidence speech review hash is stale")
        speech = TarteelSpeechReview.model_validate_json(speech_path.read_text(encoding="utf-8"))
        if (
            speech.source_asset_id != source_asset_id
            or speech.candidate_id != render_input.candidate_id
            or speech.source_sha256 != render_input.source_sha256
        ):
            raise MediaError("caption evidence speech review is bound to another candidate")
        if (
            report.speech_review_sha256 != render_input.speech_review_sha256
            or not render_input.caption_alignment_sha256
        ):
            raise MediaError("complete speech coverage is not bound to the render input")
        alignment_path = _safe(root, output.parent / "caption-alignment.json")
        if sha256_file(alignment_path) != render_input.caption_alignment_sha256:
            raise MediaError("caption evidence display alignment hash is stale")
        alignment = ForcedAlignmentDocument.model_validate_json(alignment_path.read_text(encoding="utf-8"))
        map_path = _safe(root, output.parent / "caption-time-map.json")
        time_map = TimeMapDocument.model_validate_json(map_path.read_text(encoding="utf-8"))
        if digest_time_map(time_map) != render_input.time_map_sha256:
            raise MediaError("caption evidence TimeMap is stale")
        if render_input.arabic_corrections_sha256:
            correction_path = _safe(root, output.parent / "arabic-corrections.json")
            if sha256_file(correction_path) != render_input.arabic_corrections_sha256:
                raise MediaError("caption evidence Arabic corrections are stale")
        validate_speech_captions(speech, alignment=alignment, time_map=time_map, captions=render_input.captions)


def write_caption_coverage_report(
    *,
    root: Path,
    run_dir: Path,
    output: Path,
    render_input: AdvancedHeroRenderInput,
    source_asset_id: str,
    staged_audio_sha256: str,
    render_input_sha256: str,
    speech_review_relative_path: str = "",
    speech_review_sha256: str = "",
    speech_coverage_status: Literal["insufficient_evidence", "complete"] = "insufficient_evidence",
    job_id: str,
    actor: str,
    parent_artifact_id: str,
    log_path: Path,
) -> tuple[Path, CaptionAudioCoverageReport]:
    """Decode once and publish only complete capture for one encoded draft.

    The caller obtains staged_audio_sha256 from this candidate's persisted
    authorization before shared staging advances. Decoded frames alone do not
    establish glyph readability or complete coverage of audible speech.
    """
    output = _safe(root, output)
    if not output.is_file() or output.stat().st_size == 0:
        raise MediaError("caption evidence requires a regular encoded output")
    probe_hero(output, expected_duration_us=render_input.output_duration_us)
    samples = caption_frame_samples(render_input)
    destination = _safe(root, output.parent / "caption-coverage.json")
    frame_dir = _safe(root, output.parent / "caption-frames")
    frame_dir.mkdir(parents=True, exist_ok=True)
    capture_id = uuid.uuid4().hex
    # FFmpeg's expression parser has a finite expression length. A complete
    # caption/word-boundary report can contain hundreds of frames, so one
    # giant ``eq(n,...) + ...`` expression fails only after an otherwise
    # successful production render. Decode bounded batches and keep the
    # deterministic sorted sample order in the output filenames.
    sample_items = list(samples.items())
    captured_paths: list[tuple[int, Path]] = []
    batch_size = 48
    for batch_index in range(0, len(sample_items), batch_size):
        batch = sample_items[batch_index : batch_index + batch_size]
        selection = "+".join(f"eq(n\\,{index})" for index, _observations in batch)
        pattern = _safe(root, frame_dir / f"capture-{capture_id}-{batch_index:04d}-%06d.png")
        ProcessRunner().run(
            [
                resolve_ffmpeg(),
                "-y",
                "-v",
                "error",
                "-i",
                str(output),
                "-vf",
                f"select={selection}",
                "-fps_mode",
                "passthrough",
                "-frames:v",
                str(len(batch)),
                "-start_number",
                "0",
                str(pattern),
            ],
            log_path=log_path,
            check=True,
            timeout_s=180,
            reap_group=True,
        )
        for ordinal in range(len(batch)):
            captured = _safe(root, frame_dir / f"capture-{capture_id}-{batch_index:04d}-{ordinal:06d}.png")
            if not captured.is_file() or captured.stat().st_size == 0:
                raise MediaError(f"caption evidence batch frame {batch_index + ordinal} could not be decoded")
            captured_paths.append((batch_index + ordinal, captured))
    if len(captured_paths) != len(sample_items):
        raise MediaError("caption evidence decoder returned an incomplete frame set")
    frames: list[CaptionCoverageFrame] = []
    for _ordinal, ((frame_index, observations), (_captured_ordinal, captured)) in enumerate(
        zip(sample_items, captured_paths, strict=True)
    ):
        frame_path = _safe(root, frame_dir / f"frame-{frame_index:06d}.png")
        captured.replace(frame_path)
        frames.append(
            CaptionCoverageFrame(
                frame_id=f"caption-frame-{frame_index}",
                frame_index=frame_index,
                output_time_us=frame_start_us(frame_index, FrameRate(30, 1)),
                observations=observations,
                relative_path=frame_path.relative_to(run_dir).as_posix(),
                sha256=sha256_file(frame_path),
            )
        )
    report = CaptionAudioCoverageReport(
        report_id=str(uuid.uuid4()),
        source_asset_id=source_asset_id,
        candidate_id=render_input.candidate_id,
        source_sha256=render_input.source_sha256,
        alignment_sha256=render_input.alignment_sha256,
        time_map_sha256=render_input.time_map_sha256,
        render_input_sha256=render_input_sha256,
        encoded_media_sha256=sha256_file(output),
        staged_audio_sha256=staged_audio_sha256,
        output_duration_us=render_input.output_duration_us,
        output_frame_count=render_input.duration_in_frames,
        forced_word_ids=[word.word_id for cue in render_input.captions for word in cue.words],
        caption_cue_ids=[cue.event_id for cue in render_input.captions],
        frames=frames,
        speech_review_relative_path=speech_review_relative_path,
        speech_review_sha256=speech_review_sha256,
        speech_coverage_status=speech_coverage_status,
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by=actor,
            tool=CAPTION_EVIDENCE_RECIPE,
            tool_version=__version__,
            source_asset_ids=[source_asset_id],
            parent_artifact_ids=[parent_artifact_id],
            job_id=job_id,
            inputs_sha256=render_input_sha256,
        ),
    )
    if speech_coverage_status == "complete":
        verify_caption_coverage_report(
            root=root,
            run_dir=run_dir,
            output=output,
            report=report,
            render_input=render_input,
            render_input_sha256=render_input_sha256,
            source_asset_id=source_asset_id,
        )
    partial = _safe(root, destination.with_name(f"coverage.partial.{capture_id}.json"))
    publish_json(destination, report, root, partial)
    return destination, report
