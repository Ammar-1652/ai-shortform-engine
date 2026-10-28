from datetime import UTC, datetime
from pathlib import Path

import pytest

from clipforge.hero.motion_style import style_for_id
from clipforge.hero.viewer_evidence import _decoded_intelligibility, write_viewer_evidence_bundle
from clipforge.media.hashing import sha256_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.schemas.advanced import AdvancedHeroRenderInput, AudioMixEvent
from clipforge.schemas.editorial import OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.qa import HumanWatchRecord, ViewerEvidenceBundle, ViewerEvidenceFile
from clipforge.schemas.treatment import TreatmentAudioMeasurement, TreatmentAudioMixResult


def _file(kind: str, name: str) -> ViewerEvidenceFile:
    return ViewerEvidenceFile(
        relative_path=f"candidates/candidate-1/viewer-evidence/{name}",
        sha256="a" * 64,
        kind=kind,
    )


def _bundle(*, watch: HumanWatchRecord | None) -> ViewerEvidenceBundle:
    return ViewerEvidenceBundle(
        evidence_id="viewer-evidence-1",
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        artifact_id="artifact-1",
        manifest_sha256="a" * 64,
        encoded_media_sha256="b" * 64,
        render_input_sha256="c" * 64,
        style_fingerprint="d" * 64,
        font_dependency_sha256="e" * 64,
        width=1080,
        height=1920,
        frame_rate="30/1",
        duration_us=1_000_000,
        integrated_lufs=-16,
        true_peak_dbfs=-1.5,
        decoded_frames=[_file("frame", "frame-000000.png")],
        contact_sheets=[_file("contact_sheet", "contact-sheet.png")],
        platform_crop_previews=[_file("platform_crop", "tiktok.png")],
        human_watch=watch,
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
            parent_artifact_ids=["artifact-1"],
        ),
    )


def test_viewer_evidence_requires_audio_and_muted_watch() -> None:
    with pytest.raises(ValueError, match="audio and muted"):
        _bundle(
            watch=HumanWatchRecord(
                reviewer="reviewer-1",
                watched_with_audio=True,
                watched_muted=False,
                observations=["caption readable"],
                decision="reviewed_pending_final",
                reviewed_at=datetime.now(UTC),
            )
        )


def test_viewer_evidence_accepts_complete_human_watch() -> None:
    bundle = _bundle(
        watch=HumanWatchRecord(
            reviewer="reviewer-1",
            watched_with_audio=True,
            watched_muted=True,
            observations=["caption readable", "CTA clear"],
            decision="reviewed_pending_final",
            reviewed_at=datetime.now(UTC),
        )
    )
    assert bundle.human_watch is not None


def test_viewer_evidence_writer_decodes_frames_crops_and_loudness(tmp_path: Path) -> None:
    run = tmp_path / "run"
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
    style = style_for_id("editorial-clean-v1")
    render_input = AdvancedHeroRenderInput(
        candidate_id="candidate-1",
        advanced_set_id="set-1",
        duration_in_frames=30,
        reframing_strategy="contain",
        reframing_config_sha256="a" * 64,
        profile_fingerprint="b" * 64,
        style_id=style.style_id,
        style_fingerprint=style.fingerprint(),
        motion_style=style.contract(),
        alignment_sha256="c" * 64,
        hero_plan_sha256="d" * 64,
        advanced_plan_sha256="e" * 64,
        source_sha256="f" * 64,
        time_map_sha256="1" * 64,
        output_duration_us=1_000_000,
    )
    evidence_path, bundle = write_viewer_evidence_bundle(
        root=tmp_path,
        run_dir=run,
        output=output,
        render_input=render_input,
        source_asset_id="source-1",
        project_id="project-1",
        artifact_id="artifact-1",
        manifest_sha256="2" * 64,
        encoded_media_sha256=sha256_file(output),
        render_input_sha256="4" * 64,
        parent_artifact_ids=["hero-1"],
        job_id="job-1",
        actor="test",
        log_path=run / "viewer.log",
    )
    assert evidence_path.is_file()
    assert len(bundle.decoded_frames) == 3
    assert len(bundle.platform_crop_previews) == 9
    assert sum(item.kind == "platform_crop_lateral_10_percent" for item in bundle.platform_crop_previews) == 3
    assert len(bundle.contact_sheets) == 2
    assert bundle.integrated_lufs < -1
    assert bundle.true_peak_dbfs < 0
    assert all((run / item.relative_path).is_file() for item in bundle.decoded_frames)


def _audio_mix() -> TreatmentAudioMixResult:
    return TreatmentAudioMixResult(
        mix_id="mix-1",
        treatment_fingerprint="a" * 64,
        policy_fingerprint="b" * 64,
        cue_event_ids=["sfx-1"],
        applied_gain_db=[-18],
        duck_db=[6],
        source_in_us=[0],
        fade_in_us=[20_000],
        fade_out_us=[60_000],
        speech_overlap_windows=[OutputInterval(output_start_us=0, output_end_us=500_000)],
    )


def test_decoded_intelligibility_gate_requires_signal_and_ducking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("clipforge.hero.viewer_evidence._window_rms", lambda **_kwargs: -40.0)
    passed = _decoded_intelligibility(
        root=tmp_path,
        output=tmp_path / "encoded.mp4",
        mix=_audio_mix().model_copy(
            update={
                "status": "measured",
                "measured_integrated_lufs": -16,
                "measured_true_peak_dbfs": -2,
                "measured_rms_windows": [-40],
            }
        ),
        true_peak_dbfs=-2,
        peak_limit_dbfs=-1.5,
        log_path=tmp_path / "audio.log",
    )
    assert passed.intelligibility_status == "pass"
    assert passed.intelligibility_method == "decoded_window_signal_v1"

    monkeypatch.setattr("clipforge.hero.viewer_evidence._window_rms", lambda **_kwargs: -60.0)
    failed = _decoded_intelligibility(
        root=tmp_path,
        output=tmp_path / "encoded.mp4",
        mix=_audio_mix().model_copy(
            update={
                "status": "measured",
                "measured_integrated_lufs": -16,
                "measured_true_peak_dbfs": -2,
                "measured_rms_windows": [-60],
            }
        ),
        true_peak_dbfs=-2,
        peak_limit_dbfs=-1.5,
        log_path=tmp_path / "audio.log",
    )
    assert failed.intelligibility_status == "fail"
    assert failed.intelligibility_failed_windows


def test_viewer_evidence_persists_decoded_audio_measurement_sidecar(tmp_path: Path) -> None:
    run = tmp_path / "run"
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
    style = style_for_id("editorial-clean-v1")
    mix = _audio_mix()
    # Production Advanced Hero stages all candidates in the run-level
    # directory, while the encoded output lives below candidates/<id>.
    staging = run / "staging"
    staging.mkdir(parents=True)
    for name in ("asr.flac", "effect.wav"):
        ProcessRunner().run(
            [
                resolve_ffmpeg(),
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:d=1",
                "-c:a",
                "flac" if name.endswith("flac") else "pcm_s16le",
                str(staging / name),
            ],
            log_path=run / f"{name}.log",
        )
    render_input = AdvancedHeroRenderInput(
        candidate_id="candidate-1",
        advanced_set_id="set-1",
        duration_in_frames=30,
        reframing_strategy="contain",
        reframing_config_sha256="a" * 64,
        profile_fingerprint="b" * 64,
        style_id=style.style_id,
        style_fingerprint=style.fingerprint(),
        motion_style=style.contract(),
        alignment_sha256="c" * 64,
        hero_plan_sha256="d" * 64,
        advanced_plan_sha256="e" * 64,
        source_sha256="f" * 64,
        time_map_sha256="1" * 64,
        output_duration_us=1_000_000,
        treatment_fingerprint="a" * 64,
        treatment_evidence_sha256="2" * 64,
        treatment_evidence_relative_path="candidates/candidate-1/treatment-evidence.json",
        treatment_audio_mix=mix,
        asset_names={"sfx-1": "effect.wav"},
        sfx=[
            AudioMixEvent(
                event_id="sfx-1",
                interval=OutputInterval(output_start_us=0, output_end_us=200_000),
                asset_id="sfx-1",
                gain_db=-18,
            )
        ],
    )
    evidence_path, bundle = write_viewer_evidence_bundle(
        root=tmp_path,
        run_dir=run,
        output=output,
        render_input=render_input,
        source_asset_id="source-1",
        project_id="project-1",
        artifact_id="artifact-1",
        manifest_sha256="2" * 64,
        encoded_media_sha256=sha256_file(output),
        render_input_sha256="4" * 64,
        parent_artifact_ids=["hero-1"],
        job_id="job-1",
        actor="test",
        log_path=run / "viewer.log",
        staging_dir=staging,
    )
    assert bundle.treatment_audio_intelligibility_status == "pass"
    measurement_path = run / bundle.treatment_audio_measurement_relative_path
    assert measurement_path.is_file()
    measurement = TreatmentAudioMeasurement.model_validate_json(measurement_path.read_text(encoding="utf-8"))
    assert measurement.encoded_media_sha256 == sha256_file(output)
    assert measurement.mix.intelligibility_method == "decoded_window_signal_v2"
    assert measurement.mix.intelligibility_margin_db
    assert measurement.mix.status == "measured"
    assert bundle.treatment_audio_measurement_sha256 == sha256_file(measurement_path)
    assert evidence_path.is_file()
