"""Create objective, decoded viewer evidence for a clean Advanced Hero draft.

The bundle is deliberately separate from human review.  It proves that the
exact encoded bytes can be decoded at representative times, shows the common
platform crop windows, and records loudness measured from those bytes.  It
does not claim that a human found the edit good.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from clipforge import __version__
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.hero.constants import OUTPUT_HEIGHT, OUTPUT_WIDTH
from clipforge.hero.probe import probe_hero
from clipforge.media.hashing import sha256_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.preview.timing import frame_at_or_after
from clipforge.schemas.advanced import AdvancedHeroRenderInput, advanced_fingerprint
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.qa import ViewerEvidenceBundle, ViewerEvidenceFile
from clipforge.schemas.treatment import TreatmentAudioMeasurement, TreatmentAudioMixResult
from clipforge.transcription.io import publish_json
from clipforge.vision.images import write_contact_sheet

VIEWER_EVIDENCE_RECIPE = "decoded-viewer-evidence-v3"
_LOUDNESS_RE = re.compile(r"Integrated loudness:\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", re.S)
_TRUE_PEAK_RE = re.compile(r"True peak:\s*Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", re.S)
_RMS_RE = re.compile(r"RMS level dB:\s*(-?\d+(?:\.\d+)?)", re.S)
_RMS_WINDOW_LIMIT_DB = -55.0


def _safe(root: Path, path: Path) -> Path:
    try:
        return confine_work_path(root, path.relative_to(root).as_posix(), label="viewer evidence")
    except ValueError as exc:
        raise MediaError("viewer evidence path escapes the work root") from exc


def _font_dependency_sha256(render_input: AdvancedHeroRenderInput) -> str:
    fonts = list(render_input.motion_style.font_sha256) if render_input.motion_style else []
    raw = json.dumps(sorted(fonts), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _sample_frames(render_input: AdvancedHeroRenderInput) -> list[int]:
    count = render_input.duration_in_frames
    if count < 1:
        raise MediaError("viewer evidence requires a positive frame count")
    frames = {0, count // 2, count - 1, *range(0, count, 30)}
    # Inspect shot/cut boundaries and the complete entrance/hold/exit of every
    # optional layer. The separate caption report owns every forced-word edge.
    intervals = [
        *(event.interval for event in render_input.transitions),
        *(event.interval for event in render_input.broll),
        *(event.interval for event in render_input.typography),
        *(event.interval for event in render_input.diagrams),
        *(event.interval for event in render_input.motion_graphics),
        *(event.interval for event in render_input.camera_motion),
        *(event.interval for event in render_input.sfx),
    ]
    for interval in intervals:
        start = frame_at_or_after(interval.output_start_us, count)
        end = frame_at_or_after(interval.output_end_us, count)
        frames.update((start - 1, start, (start + end - 1) // 2, end - 1, end))
    for window in render_input.windows:
        frame = frame_at_or_after(window.output_start_us, count)
        frames.update((frame - 1, frame, frame + 1))
    if render_input.campaign_overlay is not None:
        overlay = render_input.campaign_overlay
        start = frame_at_or_after(overlay.cta_start_us, count)
        end = frame_at_or_after(overlay.cta_end_us, count)
        frames.update((start - 1, start, (start + end - 1) // 2, end - 1, end))
    return sorted(frame for frame in frames if 0 <= frame < count)


def _contact_pages(destination: Path, stem: str, tiles: list[tuple[Path, int, int]]) -> list[Path]:
    pages: list[Path] = []
    for offset in range(0, len(tiles), 16):
        page = destination / f"{stem}-{offset // 16 + 1:03d}.jpg"
        page_tiles = tiles[offset : offset + 16]
        write_contact_sheet(page, page_tiles, columns=4, rows=(len(page_tiles) + 3) // 4)
        pages.append(page)
    return pages


def _decode(
    *,
    root: Path,
    output: Path,
    destination: Path,
    frames: list[int],
    crop: str | None,
    log_path: Path,
) -> list[Path]:
    destination = _safe(root, destination)
    destination.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = _safe(root, destination / f"capture-{token}-%06d.png")
    selection = "+".join(f"eq(n\\,{index})" for index in frames)
    filters = f"select={selection}"
    if crop is not None:
        filters += f",crop={crop}"
    ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-y",
            "-v",
            "error",
            "-i",
            str(_safe(root, output)),
            "-vf",
            filters,
            "-fps_mode",
            "passthrough",
            "-frames:v",
            str(len(frames)),
            "-start_number",
            "0",
            str(temporary),
        ],
        log_path=_safe(root, log_path),
        check=True,
        timeout_s=180,
        reap_group=True,
    )
    decoded: list[Path] = []
    for ordinal, frame_index in enumerate(frames):
        captured = _safe(root, destination / f"capture-{token}-{ordinal:06d}.png")
        if not captured.is_file() or captured.stat().st_size == 0:
            raise MediaError(f"viewer evidence frame {frame_index} could not be decoded")
        final = _safe(root, destination / f"frame-{frame_index:06d}.png")
        if final.exists() or final.is_symlink():
            final.unlink()
        captured.replace(final)
        decoded.append(final)
    return decoded


def _measured_audio(root: Path, output: Path, log_path: Path) -> tuple[float, float, list[float]]:
    result = ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-v",
            "info",
            "-i",
            str(_safe(root, output)),
            "-map",
            "0:a:0",
            "-af",
            "ebur128=peak=true,astats=metadata=1:reset=1",
            "-f",
            "null",
            "-",
        ],
        log_path=_safe(root, log_path),
        check=True,
        timeout_s=180,
        reap_group=True,
    )
    loudness = _LOUDNESS_RE.search(result.stderr_tail)
    peak = _TRUE_PEAK_RE.search(result.stderr_tail)
    rms = [float(value) for value in _RMS_RE.findall(result.stderr_tail)]
    if loudness is None or peak is None or not rms:
        raise MediaError("viewer evidence could not measure encoded loudness, peak, and RMS")
    return float(loudness.group(1)), float(peak.group(1)), rms[:128]


def _window_rms(
    root: Path, output: Path, interval_start_us: int, interval_end_us: int, log_path: Path
) -> float:
    """Measure one encoded output window without introducing a second clock.

    The interval remains canonical integer microseconds in the evidence. The
    decimal strings below are only ffmpeg argv values; they are never persisted
    as timing data.
    """
    if interval_end_us <= interval_start_us:
        raise MediaError("audio intelligibility window is empty")
    start_s = f"{interval_start_us / 1_000_000:.6f}"
    duration_s = f"{(interval_end_us - interval_start_us) / 1_000_000:.6f}"
    result = ProcessRunner().run(
        [
            resolve_ffmpeg(),
            "-v",
            "info",
            "-ss",
            start_s,
            "-t",
            duration_s,
            "-i",
            str(_safe(root, output)),
            "-map",
            "0:a:0",
            "-af",
            "astats=metadata=1:reset=0",
            "-f",
            "null",
            "-",
        ],
        log_path=_safe(root, log_path),
        check=True,
        timeout_s=180,
        reap_group=True,
    )
    values = [float(value) for value in _RMS_RE.findall(result.stderr_tail)]
    if not values:
        raise MediaError("audio intelligibility window did not report RMS")
    return max(values)


def _reference_window_rms(
    *, root: Path, media: Path, interval_start_us: int, interval_end_us: int, log_path: Path
) -> float:
    """Measure a staged speech/SFX reference window on the same output clock."""
    return _window_rms(
        root=root,
        output=media,
        interval_start_us=interval_start_us,
        interval_end_us=interval_end_us,
        log_path=log_path,
    )


def _decoded_intelligibility(
    *,
    root: Path,
    output: Path,
    mix: TreatmentAudioMixResult,
    true_peak_dbfs: float,
    peak_limit_dbfs: float,
    log_path: Path,
    render_input: AdvancedHeroRenderInput | None = None,
    staging_dir: Path | None = None,
) -> TreatmentAudioMixResult:
    """Return technical decoded speech-window evidence for a treatment mix.

    This deliberately proves signal presence and duck-policy coverage, not
    semantic word recognition. Human playback remains a separate review gate.
    """
    if not mix.cue_event_ids:
        return mix.model_copy(
            update={
                "status": "measured",
                "intelligibility_status": "pass",
                "intelligibility_method": "no_audio_cues_v1",
                "intelligibility_checked_windows": [],
                "intelligibility_failed_windows": [],
                "intelligibility_note": "No treatment audio cues required a speech-overlap check.",
            }
        )
    overlap_groups = (
        mix.speech_overlap_windows_v2
        if mix.speech_overlap_windows_v2
        else [[window] if window is not None else [] for window in mix.speech_overlap_windows]
    )
    checked = [window for group in overlap_groups for window in group]
    failed = []
    encoded_rms: list[float] = []
    speech_rms: list[float] = []
    sfx_rms: list[float] = []
    margins: list[float] = []
    if render_input is not None and checked:
        references = staging_dir if staging_dir is not None else output.parent / "staging"
        speech_path = _safe(root, references / render_input.speech_name)
        if speech_path.is_symlink() or not speech_path.is_file():
            return mix.model_copy(
                update={
                    "status": "measured",
                    "intelligibility_status": "fail",
                    "intelligibility_method": "decoded_window_signal_v2",
                    "intelligibility_checked_windows": checked,
                    "intelligibility_failed_windows": checked,
                    "intelligibility_encoded_rms_windows": [-120.0] * len(checked),
                    "intelligibility_speech_reference_rms_windows": [-120.0] * len(checked),
                    "intelligibility_sfx_reference_rms_windows": [-120.0] * len(checked),
                    "intelligibility_margin_db": [-120.0] * len(checked),
                    "intelligibility_note": "Staged speech reference is missing for decoded mix comparison.",
                }
            )
        try:
            sfx_by_id = {event.event_id: event for event in render_input.sfx}
            for index, window in enumerate(checked):
                encoded_level = _window_rms(
                    root=root,
                    output=output,
                    interval_start_us=window.output_start_us,
                    interval_end_us=window.output_end_us,
                    log_path=log_path.with_name(f"{log_path.stem}.window-{index:02d}.log"),
                )
                speech_level = _reference_window_rms(
                    root=root,
                    media=speech_path,
                    interval_start_us=window.output_start_us,
                    interval_end_us=window.output_end_us,
                    log_path=log_path.with_name(f"{log_path.stem}.speech-{index:02d}.log"),
                )
                overlapping_sfx: list[float] = []
                overlapping_duck: list[float] = []
                for event_index, event_id in enumerate(mix.cue_event_ids):
                    event = sfx_by_id.get(event_id)
                    event_windows = overlap_groups[event_index] if event_index < len(overlap_groups) else []
                    if event is None or not event_windows:
                        continue
                    if not any(
                        event_window.output_start_us < window.output_end_us
                        and window.output_start_us < event_window.output_end_us
                        for event_window in event_windows
                    ):
                        continue
                    name = render_input.asset_names.get(event.asset_id)
                    if not name:
                        raise MediaError(f"staged SFX asset name is missing: {event.asset_id}")
                    sfx_path = _safe(root, references / name)
                    if sfx_path.is_symlink() or not sfx_path.is_file():
                        raise MediaError(f"staged SFX asset is missing: {event.asset_id}")
                    sfx_level = _reference_window_rms(
                        root=root,
                        media=sfx_path,
                        interval_start_us=event.sfx_source_in_us or 0,
                        interval_end_us=(event.sfx_source_in_us or 0)
                        + (event.interval.output_end_us - event.interval.output_start_us),
                        log_path=log_path.with_name(f"{log_path.stem}.sfx-{index:02d}-{event_index:02d}.log"),
                    )
                    overlapping_sfx.append(sfx_level + event.gain_db)
                    overlapping_duck.append(mix.duck_db[event_index])
                max_sfx = max(overlapping_sfx, default=-120.0)
                speech_after_duck = (
                    speech_level + (render_input.source_gain_db or 0) - max(overlapping_duck, default=0.0)
                )
                margin = speech_after_duck - max_sfx
                encoded_rms.append(encoded_level)
                speech_rms.append(speech_level)
                sfx_rms.append(max_sfx)
                margins.append(margin)
                if encoded_level <= _RMS_WINDOW_LIMIT_DB or speech_level <= _RMS_WINDOW_LIMIT_DB or margin < 0:
                    failed.append(window)
        except MediaError as exc:
            missing = len(checked) - len(encoded_rms)
            return mix.model_copy(
                update={
                    "status": "measured",
                    "intelligibility_status": "fail",
                    "intelligibility_method": "decoded_window_signal_v2",
                    "intelligibility_checked_windows": checked,
                    "intelligibility_failed_windows": checked,
                    "intelligibility_encoded_rms_windows": encoded_rms + [-120.0] * missing,
                    "intelligibility_speech_reference_rms_windows": speech_rms + [-120.0] * missing,
                    "intelligibility_sfx_reference_rms_windows": sfx_rms + [-120.0] * missing,
                    "intelligibility_margin_db": margins + [-120.0] * missing,
                    "intelligibility_note": str(exc),
                }
            )
        passed = not failed and all(margin >= 0 for margin in margins)
        return mix.model_copy(
            update={
                "status": "measured",
                "intelligibility_status": "pass" if passed else "fail",
                "intelligibility_method": "decoded_window_signal_v2",
                "intelligibility_checked_windows": checked,
                "intelligibility_failed_windows": failed,
                "intelligibility_encoded_rms_windows": encoded_rms,
                "intelligibility_speech_reference_rms_windows": speech_rms,
                "intelligibility_sfx_reference_rms_windows": sfx_rms,
                "intelligibility_margin_db": margins,
                "intelligibility_note": (
                    "Decoded mix, staged speech reference, and staged SFX references show speech "
                    "at or above the applied SFX level."
                    if passed
                    else "Decoded mix comparison found a silent speech window or SFX level "
                    "above the speech reference."
                ),
            }
        )
    for index, window in enumerate(checked):
        rms_db = _window_rms(
            root=root,
            output=output,
            interval_start_us=window.output_start_us,
            interval_end_us=window.output_end_us,
            log_path=log_path.with_name(f"{log_path.stem}.window-{index:02d}.log"),
        )
        if rms_db <= _RMS_WINDOW_LIMIT_DB:
            failed.append(window)
    overlap_indices = [index for index, windows in enumerate(overlap_groups) if windows]
    ducking_ok = all(mix.duck_db[index] > 0 for index in overlap_indices)
    peak_ok = true_peak_dbfs <= peak_limit_dbfs + 0.1
    passed = not failed and ducking_ok and peak_ok
    note = (
        "Decoded speech-overlap windows contain measurable signal; configured SFX ducking "
        "and true-peak policy are satisfied. Semantic intelligibility still requires human listening."
        if passed
        else "Decoded speech-overlap evidence failed signal, ducking, or true-peak checks."
    )
    return mix.model_copy(
        update={
            "status": "measured",
            "intelligibility_status": "pass" if passed else "fail",
            "intelligibility_method": "decoded_window_signal_v1",
            "intelligibility_checked_windows": checked,
            "intelligibility_failed_windows": failed or ([checked[0]] if not ducking_ok and checked else []),
            "intelligibility_encoded_rms_windows": [],
            "intelligibility_speech_reference_rms_windows": [],
            "intelligibility_sfx_reference_rms_windows": [],
            "intelligibility_margin_db": [],
            "intelligibility_note": note,
        }
    )


def _files(
    paths: list[Path],
    run_dir: Path,
    *,
    kind: str,
    frames: list[int] | None = None,
) -> list[ViewerEvidenceFile]:
    return [
        ViewerEvidenceFile(
            relative_path=path.relative_to(run_dir).as_posix(),
            sha256=sha256_file(path),
            kind=kind,
            frame_index=None if frames is None else frames[index],
        )
        for index, path in enumerate(paths)
    ]


def write_viewer_evidence_bundle(
    *,
    root: Path,
    run_dir: Path,
    output: Path,
    render_input: AdvancedHeroRenderInput,
    source_asset_id: str,
    project_id: str,
    artifact_id: str,
    manifest_sha256: str,
    encoded_media_sha256: str,
    render_input_sha256: str,
    parent_artifact_ids: list[str],
    job_id: str,
    actor: str,
    log_path: Path,
    staging_dir: Path | None = None,
) -> tuple[Path, ViewerEvidenceBundle]:
    """Decode representative frames and publish a hash-bound evidence bundle."""
    output = _safe(root, output)
    if not output.is_file() or output.stat().st_size == 0:
        raise MediaError("viewer evidence requires a regular encoded output")
    actual_media_sha256 = sha256_file(output)
    if encoded_media_sha256 != actual_media_sha256:
        raise MediaError("viewer evidence encoded media hash is stale")
    probe = probe_hero(output, expected_duration_us=render_input.output_duration_us)
    frames = _sample_frames(render_input)
    evidence_dir = _safe(root, output.parent / "viewer-evidence")
    decoded_dir = _safe(root, evidence_dir / "decoded")
    platform_dir = _safe(root, evidence_dir / "platform-crops")
    decoded = _decode(
        root=root,
        output=output,
        destination=decoded_dir,
        frames=frames,
        crop=None,
        log_path=log_path.with_name(log_path.stem + ".decode.log"),
    )
    crops_4x5 = _decode(
        root=root,
        output=output,
        destination=platform_dir / "4x5",
        frames=frames,
        crop="1080:1350:0:285",
        log_path=log_path.with_name(log_path.stem + ".crop-4x5.log"),
    )
    crops_1x1 = _decode(
        root=root,
        output=output,
        destination=platform_dir / "1x1",
        frames=frames,
        crop="1080:1080:0:420",
        log_path=log_path.with_name(log_path.stem + ".crop-1x1.log"),
    )
    # This is a named lateral-crop stress test, not a universal platform
    # guarantee. It exposes edge branding lost when a player zooms the asset.
    crops_lateral = _decode(
        root=root,
        output=output,
        destination=platform_dir / "lateral-10-percent",
        frames=frames,
        crop="972:1920:54:0",
        log_path=log_path.with_name(log_path.stem + ".crop-lateral.log"),
    )
    contacts_dir = _safe(root, evidence_dir / "contact-sheets")
    contacts_dir.mkdir(parents=True, exist_ok=True)
    timestamps = [frame * 1_000_000 // 30 for frame in frames]
    full_contacts = _contact_pages(
        contacts_dir, "full", list(zip(decoded, range(len(decoded)), timestamps, strict=True))
    )
    crop_tiles = [
        *list(zip(crops_4x5, range(len(crops_4x5)), timestamps, strict=True)),
        *list(zip(crops_1x1, range(len(crops_1x1)), timestamps, strict=True)),
        *list(zip(crops_lateral, range(len(crops_lateral)), timestamps, strict=True)),
    ]
    crop_contacts = _contact_pages(contacts_dir, "platform-crops", crop_tiles)
    integrated_lufs, true_peak_dbfs, rms_windows = _measured_audio(
        root, output, log_path.with_name(log_path.stem + ".loudness.log")
    )
    evidence_path = _safe(root, output.parent / "viewer-evidence" / "bundle.json")
    measured_mix = None
    if render_input.treatment_audio_mix is not None:
        measured_mix = _decoded_intelligibility(
            root=root,
            output=output,
            mix=render_input.treatment_audio_mix.model_copy(
                update={
                    "status": "measured",
                    "measured_integrated_lufs": integrated_lufs,
                    "measured_true_peak_dbfs": true_peak_dbfs,
                    "measured_rms_windows": rms_windows,
                }
            ),
            true_peak_dbfs=true_peak_dbfs,
            peak_limit_dbfs=render_input.audio_true_peak_dbfs,
            log_path=log_path.with_name(log_path.stem + ".intelligibility.log"),
            render_input=render_input,
            staging_dir=staging_dir,
        )
    measurement_relative_path = ""
    measurement_sha256 = ""
    if measured_mix is not None:
        measurement_path = _safe(root, evidence_path.with_name("treatment-audio-measurement.json"))
        measurement = TreatmentAudioMeasurement(
            measurement_id=str(uuid.uuid4()),
            source_asset_id=source_asset_id,
            candidate_id=render_input.candidate_id,
            treatment_evidence_sha256=render_input.treatment_evidence_sha256,
            encoded_media_sha256=actual_media_sha256,
            mix=measured_mix,
            created_at=datetime.now(UTC),
            provenance=ArtifactProvenance(
                created_at=datetime.now(UTC),
                created_by=actor,
                tool=VIEWER_EVIDENCE_RECIPE,
                tool_version=__version__,
                source_asset_ids=[source_asset_id],
                parent_artifact_ids=sorted(set([*parent_artifact_ids, artifact_id])),
                job_id=job_id,
                inputs_sha256=render_input_sha256,
            ),
        )
        publish_json(
            measurement_path,
            measurement,
            root,
            _safe(root, measurement_path.with_name(f"{measurement_path.stem}.partial.json")),
        )
        measurement_relative_path = measurement_path.relative_to(run_dir).as_posix()
        measurement_sha256 = sha256_file(measurement_path)
    bundle = ViewerEvidenceBundle(
        evidence_id=str(uuid.uuid4()),
        project_id=project_id,
        source_asset_id=source_asset_id,
        candidate_id=render_input.candidate_id,
        artifact_id=artifact_id,
        manifest_sha256=manifest_sha256,
        encoded_media_sha256=actual_media_sha256,
        render_input_sha256=render_input_sha256,
        pilot_sha256=render_input.pilot_sha256,
        treatment_fingerprint=render_input.treatment_fingerprint,
        treatment_evidence_sha256=render_input.treatment_evidence_sha256,
        treatment_evidence_relative_path=render_input.treatment_evidence_relative_path,
        treatment_audio_mix_sha256=(
            advanced_fingerprint(measured_mix.model_dump(mode="json")) if measured_mix is not None else ""
        ),
        treatment_audio_mix_status="measured" if measured_mix is not None else "",
        treatment_audio_intelligibility_status=(
            measured_mix.intelligibility_status if measured_mix is not None else ""
        ),
        treatment_audio_intelligibility_method=(
            measured_mix.intelligibility_method if measured_mix is not None else ""
        ),
        treatment_audio_intelligibility_note=(
            measured_mix.intelligibility_note if measured_mix is not None else ""
        ),
        treatment_audio_measurement_relative_path=measurement_relative_path,
        treatment_audio_measurement_sha256=measurement_sha256,
        treatment_audio_integrated_lufs=integrated_lufs if measured_mix is not None else None,
        treatment_audio_true_peak_dbfs=true_peak_dbfs if measured_mix is not None else None,
        treatment_audio_rms_windows=rms_windows if measured_mix is not None else [],
        style_fingerprint=render_input.style_fingerprint,
        font_dependency_sha256=_font_dependency_sha256(render_input),
        width=OUTPUT_WIDTH,
        height=OUTPUT_HEIGHT,
        frame_rate=f"{probe.fps_numerator}/{probe.fps_denominator}",
        duration_us=probe.duration_us,
        integrated_lufs=integrated_lufs,
        true_peak_dbfs=true_peak_dbfs,
        decoded_frames=_files(decoded, run_dir, kind="decoded_frame", frames=frames),
        contact_sheets=[
            *_files(full_contacts, run_dir, kind="full_contact_sheet"),
            *_files(crop_contacts, run_dir, kind="platform_crop_contact_sheet"),
        ],
        platform_crop_previews=[
            *_files(crops_4x5, run_dir, kind="platform_crop_4x5", frames=frames),
            *_files(crops_1x1, run_dir, kind="platform_crop_1x1", frames=frames),
            *_files(crops_lateral, run_dir, kind="platform_crop_lateral_10_percent", frames=frames),
        ],
        camera_motion_event_ids=sorted(item.event_id for item in render_input.camera_motion),
        transition_event_ids=sorted(item.event_id for item in render_input.transitions),
        motion_recipe_ids=sorted(render_input.motion_recipe_ids),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by=actor,
            tool=VIEWER_EVIDENCE_RECIPE,
            tool_version=__version__,
            source_asset_ids=[source_asset_id],
            parent_artifact_ids=sorted(set([*parent_artifact_ids, artifact_id])),
            job_id=job_id,
            inputs_sha256=render_input_sha256,
        ),
    )
    partial = _safe(root, evidence_path.with_name(f"bundle.partial.{uuid.uuid4().hex}.json"))
    publish_json(evidence_path, bundle, root, partial)
    return evidence_path, bundle
