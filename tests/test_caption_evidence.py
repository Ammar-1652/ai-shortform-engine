from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.caption_evidence import (
    caption_frame_samples,
    verify_caption_coverage_report,
    write_caption_coverage_report,
)
from clipforge.hero.render_authorization import authorize_render_candidate
from clipforge.hero.render_checkpoint import renderer_dependency_sha256
from clipforge.media.hashing import sha256_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import (
    AdvancedHeroRenderInput,
    CaptionWordTiming,
    TypographyEvent,
    advanced_fingerprint,
)
from clipforge.schemas.campaign import TarteelSpeechInterval, TarteelSpeechReview
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance

_HASH = hashlib.sha256(b"caption-evidence").hexdigest()


def test_caption_coverage_report_decodes_edges_and_binds_encoded_hash(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "staging").mkdir(parents=True)
    (run / "staging/asr.flac").write_bytes(b"staged-audio")
    output = run / "candidates/candidate-1/advanced.mp4"
    output.parent.mkdir(parents=True)
    ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=1080x1920:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ],
        log_path=run / "render.log",
    )
    word = CaptionWordTiming(
        word_id="word-1",
        text=" hello",
        output_start_us=0,
        output_end_us=1_000_000,
        output_start_frame=0,
        output_end_frame_exclusive=30,
    )
    cue = TypographyEvent(
        event_id="cue-1",
        interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
        purpose=MotionPurpose.KEY_PHRASE,
        component_id="caption-main",
        text="hello",
        x=100,
        y=1400,
        font_size=64,
        words=[word],
    )
    render_input = AdvancedHeroRenderInput(
        candidate_id="candidate-1",
        advanced_set_id="set-1",
        duration_in_frames=30,
        reframing_strategy="contain",
        reframing_config_sha256=_HASH,
        profile_fingerprint=_HASH,
        alignment_sha256=_HASH,
        hero_plan_sha256=_HASH,
        advanced_plan_sha256=_HASH,
        source_sha256=_HASH,
        time_map_sha256=_HASH,
        output_duration_us=1_000_000,
        captions=[cue],
    )
    shutil.copyfile(output, run / "staging/analysis.mp4")
    input_digest = advanced_fingerprint(render_input.model_dump(mode="json"))
    (run / "batch-input.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "input": render_input.model_dump(mode="json"),
                        "input_sha256": input_digest,
                        "outputPath": str(output),
                        "h264Crf": 18,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    authorize_render_candidate(
        workspace=SourceWorkspace(tmp_path, "project-1", "source-1"),
        root=tmp_path,
        run_dir=run,
        render_input=render_input,
        output=output,
        dependency_sha256=renderer_dependency_sha256(),
        job_id="job-1",
        parent_artifact_id="hero-1",
        actor="test",
    )
    render_path = output.parent / "render-input.json"
    render_path.write_text(render_input.model_dump_json(), encoding="utf-8")
    render_input_sha256 = sha256_file(render_path)
    report_path, report = write_caption_coverage_report(
        root=tmp_path,
        run_dir=run,
        output=output,
        render_input=render_input,
        source_asset_id="source-1",
        staged_audio_sha256=hashlib.sha256(b"staged-audio").hexdigest(),
        render_input_sha256=render_input_sha256,
        job_id="job-1",
        actor="test",
        parent_artifact_id="hero-1",
        log_path=run / "coverage.log",
    )
    assert report_path.is_file()
    assert report.encoded_media_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert report.staged_audio_sha256 == hashlib.sha256(b"staged-audio").hexdigest()
    assert {obs.phase for frame in report.frames for obs in frame.observations} >= {
        "first",
        "last",
        "start",
        "middle",
        "end",
        "word_start",
        "word_end",
    }
    assert report.speech_coverage_status == "insufficient_evidence"
    assert {frame.frame_index for frame in report.frames} >= {0, 29}
    assert all((run / frame.relative_path).is_file() for frame in report.frames)
    verify_caption_coverage_report(
        root=tmp_path,
        run_dir=run,
        output=output,
        report=report,
        render_input=render_input,
        render_input_sha256=render_input_sha256,
        source_asset_id="source-1",
    )
    frame_path = run / report.frames[0].relative_path
    original_frame = frame_path.read_bytes()
    frame_path.write_bytes(original_frame + b"tampered")
    with pytest.raises(MediaError, match="decoded frame hash is stale"):
        verify_caption_coverage_report(
            root=tmp_path,
            run_dir=run,
            output=output,
            report=report,
            render_input=render_input,
            render_input_sha256=render_input_sha256,
            source_asset_id="source-1",
        )
    frame_path.write_bytes(original_frame)
    with pytest.raises(MediaError, match="staged audio"):
        verify_caption_coverage_report(
            root=tmp_path,
            run_dir=run,
            output=output,
            report=report.model_copy(update={"staged_audio_sha256": _HASH}),
            render_input=render_input,
            render_input_sha256=render_input_sha256,
            source_asset_id="source-1",
        )


def test_subframe_cue_samples_the_frame_remotion_displays() -> None:
    word = CaptionWordTiming(
        word_id="short-word",
        text="Hi",
        output_start_us=15_000,
        output_end_us=20_000,
        output_start_frame=1,
        output_end_frame_exclusive=2,
    )
    cue = TypographyEvent(
        event_id="short-cue",
        interval=OutputInterval(output_start_us=15_000, output_end_us=20_000),
        purpose=MotionPurpose.KEY_PHRASE,
        component_id="caption-main",
        text="Hi",
        x=100,
        y=1400,
        font_size=64,
        words=[word],
    )
    render_input = AdvancedHeroRenderInput(
        candidate_id="candidate-1",
        advanced_set_id="set-1",
        duration_in_frames=30,
        reframing_strategy="contain",
        reframing_config_sha256=_HASH,
        profile_fingerprint=_HASH,
        alignment_sha256=_HASH,
        hero_plan_sha256=_HASH,
        advanced_plan_sha256=_HASH,
        source_sha256=_HASH,
        time_map_sha256=_HASH,
        output_duration_us=1_000_000,
        captions=[cue],
    )
    samples = caption_frame_samples(render_input)
    assert {item.phase for item in samples[1]} >= {"start", "middle", "end", "word_start", "word_end"}
    assert any(item.phase == "after" for item in samples[2])


def test_complete_speech_coverage_requires_source_bound_review(tmp_path: Path) -> None:
    review = TarteelSpeechReview(
        review_id="speech-review-1",
        campaign="tarteel",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256=_HASH,
        raw_asr_sha256=_HASH,
        transcript_sha256=_HASH,
        locale="ar",
        intervals=[
            TarteelSpeechInterval(
                span_id="speech-1",
                source_start_us=0,
                source_end_us=1_000_000,
                kind="dialogue",
                caption_decision="captioned",
                observed_text="مرحبا",
                review_note="reviewed against the selected audio",
            )
        ],
        reviewer="reviewer-1",
        reviewed_at=datetime.now(UTC),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="reviewer-1",
            tool="tarteel-review",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )
    report = {
        "schema_version": "1.0.0",
        "report_id": "report-1",
        "source_asset_id": "source-1",
        "candidate_id": "candidate-1",
        "source_sha256": _HASH,
        "alignment_sha256": _HASH,
        "time_map_sha256": _HASH,
        "render_input_sha256": _HASH,
        "encoded_media_sha256": _HASH,
        "staged_audio_sha256": _HASH,
        "output_duration_us": 1_000_000,
        "output_frame_count": 30,
        "forced_word_ids": ["word-1"],
        "caption_cue_ids": ["cue-1"],
        "frames": [],
        "speech_coverage_status": "complete",
        "speech_review_relative_path": "candidates/candidate-1/speech-review.json",
        "speech_review_sha256": _HASH,
        "provenance": {
            "schema_version": "1.0.0",
            "created_at": datetime.now(UTC).isoformat(),
            "created_by": "reviewer-1",
            "tool": "test",
            "tool_version": "1",
            "source_asset_ids": ["source-1"],
        },
    }
    # A complete report cannot use an empty frame list even if the speech
    # inventory is otherwise valid.
    with pytest.raises(ValueError, match="frames"):
        from clipforge.schemas.caption_evidence import CaptionAudioCoverageReport

        CaptionAudioCoverageReport.model_validate(report)
    speech_path = tmp_path / "candidates/candidate-1/speech-review.json"
    speech_path.parent.mkdir(parents=True)
    speech_path.write_text(review.model_dump_json(), encoding="utf-8")
    assert speech_path.is_file()
