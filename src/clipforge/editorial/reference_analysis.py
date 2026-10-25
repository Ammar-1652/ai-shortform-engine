"""Authorized local reference-video intake and deterministic probe analysis."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Literal

from pydantic import ValidationError

from clipforge import __version__
from clipforge.errors import MediaError
from clipforge.media.clock import us_to_seconds_str
from clipforge.media.hashing import sha256_file
from clipforge.media.probe import probe_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import atomic_replace, ensure_within
from clipforge.paths import resolve_work_dir
from clipforge.schemas.editorial_knowledge import (
    EditorialStyleCard,
    ReferenceAnalysis,
    ReferenceMetric,
)
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.vision.images import write_contact_sheet
from clipforge.vision.scene_backend import PySceneDetectBackend


class ReferenceAnalysisError(MediaError):
    """Reference analysis was not authorized or could not be verified."""


def analyze_reference_file(
    source: Path,
    *,
    work_root: Path | None = None,
    permission: Literal["analysis_allowed", "reuse_allowed"] = "analysis_allowed",
    permission_evidence: str,
    source_id: str | None = None,
) -> ReferenceAnalysis:
    """Probe one authorized local reference and record unknown creative metrics honestly."""
    root = resolve_work_dir(work_root).resolve()
    source = source.absolute()
    ensure_within(root, source)
    cursor = root
    for component in source.relative_to(root).parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise ReferenceAnalysisError("reference source cannot contain symlinks")
    if not source.is_file():
        raise ReferenceAnalysisError("reference source must be a regular file inside the work root")
    media_sha256 = sha256_file(source)
    stable_id = source_id or f"reference-{media_sha256[:16]}"
    analysis_id = f"analysis-{media_sha256[:16]}"
    analysis_dir = root / "editorial" / "analyses"
    log_dir = root / "editorial" / "logs"
    ensure_within(root, analysis_dir)
    ensure_within(root, log_dir)
    if analysis_dir.is_symlink() or log_dir.is_symlink():
        raise ReferenceAnalysisError("reference analysis directories cannot be symlinks")
    analysis_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        _, probe = probe_file(
            source,
            ProcessRunner(),
            video_override=None,
            audio_override=None,
            log_path=log_dir / f"{analysis_id}.ffprobe.log",
        )
    except (MediaError, OSError) as exc:
        raise ReferenceAnalysisError(f"reference probe failed: {exc}") from exc
    duration_us = probe.timeline.canonical_duration_us
    relative = source.relative_to(root).as_posix()
    try:
        scenes = PySceneDetectBackend().detect(source, duration_us)
    except (MediaError, OSError) as exc:
        raise ReferenceAnalysisError(f"reference shot analysis failed: {exc}") from exc
    if not scenes:
        scenes = [(0, duration_us)]
    shot_durations = [end - start for start, end in scenes if end > start]
    if not shot_durations:
        raise ReferenceAnalysisError("reference shot analysis returned no positive scenes")
    frame_paths, _frame_times, contact_sheet = _write_reference_evidence(
        source=source,
        scenes=scenes,
        root=root,
        analysis_dir=analysis_dir,
        log_dir=log_dir,
        analysis_id=analysis_id,
    )
    cuts_per_minute = (len(scenes) - 1) / (duration_us / 60_000_000)
    audio_duration_us = next(
        (item.duration_us for item in probe.audio_streams if item.duration_us is not None),
        None,
    )
    loudness: float | None = None
    true_peak: float | None = None
    audio_log = f"editorial/logs/{analysis_id}.ebur128.log"
    if probe.audio_streams:
        try:
            audio_result = ProcessRunner().run(
                [
                    resolve_ffmpeg(),
                    "-hide_banner",
                    "-nostats",
                    "-i",
                    str(source),
                    "-filter_complex",
                    "ebur128=peak=true",
                    "-f",
                    "null",
                    "-",
                ],
                log_path=root / audio_log,
            )
        except (MediaError, OSError) as exc:
            raise ReferenceAnalysisError(f"reference audio measurement failed: {exc}") from exc
        loudness_match = re.search(
            r"Integrated loudness:\s*I:\s*(-?\d+(?:\.\d+)?)\s*LUFS",
            audio_result.stderr_tail,
            re.S,
        )
        peak_match = re.search(
            r"True peak:\s*Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS",
            audio_result.stderr_tail,
            re.S,
        )
        if loudness_match is None or peak_match is None:
            raise ReferenceAnalysisError("reference audio measurement did not report LUFS and true peak")
        loudness = float(loudness_match.group(1))
        true_peak = float(peak_match.group(1))
    metrics = [
        ReferenceMetric(
            name="duration",
            value=float(duration_us),
            unit="microseconds",
            evidence_kind="observed",
            method="ffprobe",
        ),
        ReferenceMetric(
            name="audio_duration",
            value=None if audio_duration_us is None else float(audio_duration_us),
            unit="microseconds" if audio_duration_us is not None else None,
            evidence_kind="observed",
            method="ffprobe" if audio_duration_us is not None else "unavailable",
            limitation=None if audio_duration_us is not None else "No audio duration was present.",
        ),
        ReferenceMetric(
            name="integrated_loudness",
            value=loudness,
            unit="LUFS" if loudness is not None else None,
            evidence_kind="observed",
            method="audio_probe" if loudness is not None else "unavailable",
            limitation=None if loudness is not None else "No audio stream was present.",
        ),
        ReferenceMetric(
            name="true_peak",
            value=true_peak,
            unit="dBFS" if true_peak is not None else None,
            evidence_kind="observed",
            method="audio_probe" if true_peak is not None else "unavailable",
            limitation=None if true_peak is not None else "No audio stream was present.",
        ),
        ReferenceMetric(
            name="hook_duration",
            value=None,
            unit=None,
            evidence_kind="heuristic",
            method="unavailable",
            limitation="Hook boundaries require frame/transcript or human-watch evidence.",
        ),
        ReferenceMetric(
            name="first_visual_change",
            value=float(shot_durations[0]) if len(scenes) > 1 else None,
            unit="microseconds" if len(scenes) > 1 else None,
            evidence_kind="observed" if len(scenes) > 1 else "heuristic",
            method="frame_probe" if len(scenes) > 1 else "unavailable",
            limitation=None if len(scenes) > 1 else "No detected shot change was available.",
        ),
        ReferenceMetric(
            name="shot_count",
            value=float(len(scenes)),
            unit="count",
            evidence_kind="observed",
            method="frame_probe",
        ),
        ReferenceMetric(
            name="median_shot_duration",
            value=float(median(shot_durations)),
            unit="microseconds",
            evidence_kind="observed",
            method="frame_probe",
        ),
        ReferenceMetric(
            name="cut_density",
            value=cuts_per_minute,
            unit="cuts_per_minute",
            evidence_kind="observed",
            method="frame_probe",
        ),
        ReferenceMetric(
            name="words_per_second",
            value=None,
            unit=None,
            evidence_kind="observed",
            method="unavailable",
            limitation="Transcript timing was not supplied for this intake.",
        ),
        ReferenceMetric(
            name="caption_line_count",
            value=None,
            unit=None,
            evidence_kind="observed",
            method="unavailable",
            limitation="Caption layout requires decoded-frame inspection or sidecar evidence.",
        ),
        ReferenceMetric(
            name="caption_position",
            value=None,
            unit=None,
            evidence_kind="observed",
            method="unavailable",
            limitation="Caption geometry requires decoded-frame inspection or a caption sidecar.",
        ),
        ReferenceMetric(
            name="transition_class",
            value=None,
            unit=None,
            evidence_kind="observed",
            method="unavailable",
            limitation="Transition class requires frame-window inspection around each cut.",
        ),
        ReferenceMetric(
            name="sfx_timing",
            value=None,
            unit=None,
            evidence_kind="observed",
            method="unavailable",
            limitation="SFX timing requires separated audio evidence or a human-watch record.",
        ),
        ReferenceMetric(
            name="silence_windows",
            value=None,
            unit=None,
            evidence_kind="observed",
            method="unavailable",
            limitation="Silence windows require waveform threshold analysis.",
        ),
        ReferenceMetric(
            name="motion_intensity",
            value=None,
            unit=None,
            evidence_kind="heuristic",
            method="unavailable",
            limitation="Motion intensity requires decoded motion-vector or human-watch evidence.",
        ),
        ReferenceMetric(
            name="payoff_position",
            value=None,
            unit=None,
            evidence_kind="heuristic",
            method="unavailable",
            limitation="Payoff position requires narrative review evidence.",
        ),
        ReferenceMetric(
            name="cta_hold",
            value=None,
            unit=None,
            evidence_kind="observed",
            method="unavailable",
            limitation="CTA timing requires frame or human-watch evidence.",
        ),
    ]
    now = datetime.now(UTC)
    provenance = ArtifactProvenance(
        created_at=now,
        created_by="codex_operator",
        tool="clipforge editorial reference analyzer",
        tool_version=__version__,
        source_asset_ids=[stable_id],
        inputs_sha256=media_sha256,
    )
    payload = {
        "analysis_id": analysis_id,
        "source_id": stable_id,
        "source_locator": relative,
        "permission": permission,
        "permission_evidence": permission_evidence,
        "media_sha256": media_sha256,
        "analyzer_version": f"reference-probe-v3/{__version__}",
        "metrics": [metric.model_dump(mode="json") for metric in metrics],
        "observation_ids": [],
        "evidence_paths": [
            f"editorial/logs/{analysis_id}.ffprobe.log",
            *([audio_log] if probe.audio_streams else []),
            *[path.relative_to(root).as_posix() for path in frame_paths],
            contact_sheet.relative_to(root).as_posix(),
        ],
        "unknowns": [
            "hook timing",
            "payoff and CTA timing",
            "transcript timing",
            "caption placement",
            "sound-design stem identity",
        ],
        "analysis_sha256": "0" * 64,
        "provenance": provenance.model_dump(mode="json"),
        "created_at": now.isoformat(),
    }
    document = ReferenceAnalysis.model_validate(payload)
    document = document.model_copy(
        update={
            "analysis_sha256": _digest(document),
        }
    )
    final = analysis_dir / f"{analysis_id}.json"
    temporary = final.with_name(f".{final.name}.partial")
    temporary.write_text(
        json.dumps(document.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    atomic_replace(temporary, final, root)
    return document


def _write_reference_evidence(
    *,
    source: Path,
    scenes: list[tuple[int, int]],
    root: Path,
    analysis_dir: Path,
    log_dir: Path,
    analysis_id: str,
) -> tuple[list[Path], list[int], Path]:
    """Decode bounded scene-midpoint frames and an inspectable contact sheet.

    This is visual evidence only. It intentionally does not run OCR, infer a
    hook, or assign a speaker. A reference with more than sixteen scenes is
    sampled deterministically across the scene list so the evidence remains
    small and reviewable.
    """
    candidates = [start + max(0, (end - start) // 2) for start, end in scenes if end > start]
    if not candidates:
        raise ReferenceAnalysisError("reference has no positive scene midpoint for visual evidence")
    if len(candidates) > 16:
        indexes = [round(index * (len(candidates) - 1) / 15) for index in range(16)]
        candidates = [candidates[index] for index in indexes]
    frame_dir = analysis_dir / analysis_id / "frames"
    contact_dir = analysis_dir / analysis_id / "contact-sheets"
    ensure_within(root, frame_dir)
    ensure_within(root, contact_dir)
    if frame_dir.is_symlink() or contact_dir.is_symlink():
        raise ReferenceAnalysisError("reference evidence directories cannot be symlinks")
    frame_dir.mkdir(parents=True, exist_ok=True)
    contact_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    for ordinal, timestamp_us in enumerate(candidates):
        final = frame_dir / f"frame-{ordinal:03d}.jpg"
        # Keep the image suffix last so ffmpeg's image2 muxer can infer the
        # output format while the partial file remains outside the published
        # name.
        partial = final.with_name(f".{final.stem}.partial.jpg")
        ProcessRunner().run(
            [
                resolve_ffmpeg(),
                "-y",
                "-v",
                "error",
                "-ss",
                us_to_seconds_str(timestamp_us),
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(partial),
            ],
            log_path=log_dir / f"{analysis_id}.frame-{ordinal:03d}.log",
            check=True,
            timeout_s=90,
            reap_group=True,
        )
        if not partial.is_file() or partial.stat().st_size == 0:
            raise ReferenceAnalysisError(f"reference frame {ordinal} could not be decoded")
        atomic_replace(partial, final, root)
        frames.append(final)
    contact = contact_dir / "contact-001.jpg"
    partial_contact = contact.with_name(f".{contact.stem}.partial.jpg")
    write_contact_sheet(
        partial_contact,
        [
            (path, ordinal, timestamp_us)
            for ordinal, (path, timestamp_us) in enumerate(zip(frames, candidates, strict=True))
        ],
    )
    atomic_replace(partial_contact, contact, root)
    return frames, candidates, contact


def _digest(document: ReferenceAnalysis) -> str:
    payload = document.model_dump(mode="json")
    payload.pop("analysis_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_reference_analysis(path: Path, *, work_root: Path | None = None) -> ReferenceAnalysis:
    path = path.absolute()
    if path.is_symlink() or not path.is_file():
        raise ReferenceAnalysisError(f"reference analysis must be a regular file: {path}")
    try:
        document = ReferenceAnalysis.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ReferenceAnalysisError(f"reference analysis is invalid: {path}") from exc
    if _digest(document) != document.analysis_sha256:
        raise ReferenceAnalysisError("reference analysis hash is stale")
    root = (work_root or path.parents[2]).absolute()
    try:
        source = root / document.source_locator
        ensure_within(root, source)
        cursor = root
        for component in source.relative_to(root).parts:
            cursor = cursor / component
            if cursor.is_symlink():
                raise ReferenceAnalysisError("reference source contains a symlink")
        if not source.is_file() or sha256_file(source) != document.media_sha256:
            raise ReferenceAnalysisError("reference analysis source bytes are stale or missing")
        for evidence_path in document.evidence_paths:
            evidence = root / evidence_path
            ensure_within(root, evidence)
            if evidence.is_symlink() or not evidence.is_file():
                raise ReferenceAnalysisError("reference analysis evidence is missing or unsafe")
    except (OSError, ValueError) as exc:
        raise ReferenceAnalysisError("reference analysis source/evidence paths are unsafe") from exc
    return document


def propose_style_card(
    analysis: ReferenceAnalysis,
    *,
    style_card_id: str,
    name: str,
    work_root: Path | None = None,
) -> tuple[EditorialStyleCard, Path]:
    """Create a reviewable style proposal from measured reference facts.

    The proposal remains ``state=proposed``. Activation requires a knowledge
    release update and its evaluation cases; reference metrics never become a
    performance claim automatically.
    """
    metric_by_name = {metric.name: metric for metric in analysis.metrics}
    shot = metric_by_name.get("median_shot_duration")
    density = metric_by_name.get("cut_density")
    loudness = metric_by_name.get("integrated_loudness")
    pacing = [
        "Use the measured reference cadence as a comparison input, not a universal target.",
        f"Median shot duration observed: {shot.value:.0f} microseconds."
        if shot and shot.value is not None
        else "Shot cadence is unavailable.",
        f"Cut density observed: {density.value:.2f} cuts per minute."
        if density and density.value is not None
        else "Cut density is unavailable.",
    ]
    audio_rules = [
        "Keep speech intelligible and verify the final encoded mix.",
        f"Reference integrated loudness observed: {loudness.value:.1f} LUFS."
        if loudness and loudness.value is not None
        else "Reference loudness is unavailable.",
        "Do not infer individual SFX stems from a mixed reference.",
    ]
    card = EditorialStyleCard(
        style_card_id=style_card_id,
        name=name,
        state="proposed",
        source_ids=[analysis.source_id],
        observation_ids=[],
        reference_analysis_ids=[analysis.analysis_id],
        reference_analysis_sha256=[analysis.analysis_sha256],
        guidance_card_ids=[],
        narrative_pattern_ids=[],
        motion_recipe_ids=[],
        caption_style_id=None,
        visual_identity=["Requires frame inspection before identity claims."],
        pacing_rules=pacing,
        audio_rules=audio_rules,
        ending_rules=[
            "Hook, payoff, CTA, and ending remain unknown until transcript or human review evidence is added."
        ],
        limitations=[
            "A single reference does not prove performance or causality.",
            *analysis.unknowns,
        ],
        confidence="low",
        content_sha256="0" * 64,
        updated_at=datetime.now(UTC),
    )
    card = card.model_copy(update={"content_sha256": _style_digest(card)})
    root = resolve_work_dir(work_root).resolve()
    directory = root / "editorial" / "style-proposals"
    ensure_within(root, directory)
    if directory.is_symlink():
        raise ReferenceAnalysisError("style proposal directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / f"{style_card_id}.json"
    ensure_within(root, final)
    if final.exists():
        raise ReferenceAnalysisError("style card proposal ids are immutable")
    temporary = final.with_name(f".{final.name}.partial")
    temporary.write_text(
        json.dumps(card.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    atomic_replace(temporary, final, root)
    return card, final


def _style_digest(card: EditorialStyleCard) -> str:
    payload = card.model_dump(mode="json")
    payload.pop("content_sha256", None)
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
