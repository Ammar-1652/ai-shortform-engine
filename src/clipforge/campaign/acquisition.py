"""Acquire selected campaign sources into the work root. The production runner stays separate."""

from __future__ import annotations

import fcntl
import os
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from clipforge.campaign.antoine import inventory_sources, policy_sha256
from clipforge.campaign.providers import CampaignError
from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.media.local_file import path_from_file_uri
from clipforge.media.probe import probe_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import ensure_within, mkdir_contained, reject_symlink_chain
from clipforge.schemas.acquisition import (
    CampaignAcquisitionAttempt,
    CampaignAcquisitionRequest,
    CampaignAcquisitionResult,
    CampaignOperatorBinding,
    CampaignSourceBinding,
    MediaConstraints,
    ProbeFacts,
)
from clipforge.schemas.campaign_operator import CampaignSelectionDocument
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.storage import Database, insert_job
from clipforge.storage.repository import update_job

_MAX_BYTES = 200_000_000
_ZERO = "0" * 64
_RELOAD = "The campaign selection changed while this page was open; reload before saving."
_KIND = "campaign_acquisition"


def plan_acquisition(database: Database, work_root: Path, selection_id: str) -> str:
    """Describe an acquisition. This does not create files or jobs."""
    root = work_root.resolve()
    selection = _read_selection(root, selection_id)
    _require_current(root, selection, None)
    lines = [f"selection {selection.selection_id} {selection.status}"]
    for choice in selection.sources:
        rights = _rights(choice.source_id)
        reusable = (
            None if rights != "allowed" else _reusable(root, selection, choice.source_id, choice.source_sha256)
        )
        cache = "hit" if reusable is not None else "miss"
        lines.append(f"{choice.source_id} {rights} {cache} max_bytes {_MAX_BYTES}")
    return "\n".join(lines)


def run_acquisition(
    database: Database,
    work_root: Path,
    selection_id: str,
    *,
    operator_id: str,
    force: bool = False,
    expected_selection_sha256: str | None = None,
    max_bytes: int | None = None,
    constraints: MediaConstraints | None = None,
    expected_size_bytes: int | None = None,
    promotion_hook: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> CampaignAcquisitionAttempt:
    """Acquire every selected source. An unchanged verified attempt is returned as-is."""
    root = work_root.resolve()
    selection = _read_selection(root, selection_id)
    _require_current(root, selection, expected_selection_sha256)
    if selection.status != "ready":
        raise CampaignError("campaign selection is not ready", code=selection.reason_code)
    if not force:
        cached = _matching_attempt(database, root, selection)
        if cached is not None:
            return cached
    _clean_partials(root)
    attempt_id = str(uuid4())
    created = datetime.now(UTC)
    limit = _MAX_BYTES if max_bytes is None else max_bytes
    rules = constraints or MediaConstraints()
    requests: list[CampaignAcquisitionRequest] = []
    results: list[CampaignAcquisitionResult] = []
    with _lock(root):
        for choice in selection.sources:
            request = _request(
                selection,
                choice.source_id,
                choice.source_sha256,
                operator_id,
                created,
                limit,
                rules,
                database,
                expected_size_bytes,
            )
            requests.append(request)
            if cancel_event is not None and cancel_event.is_set():
                results.append(_unsuccessful(request, attempt_id, "cancelled", created))
                continue
            results.append(
                _acquire_one(
                    database,
                    root,
                    attempt_id,
                    selection,
                    request,
                    force=force,
                    promotion_hook=promotion_hook,
                )
            )
        attempt = _attempt(root, attempt_id, selection, operator_id, created, requests, results)
        attempt = _write_attempt(root, attempt)
    return attempt


def resume_acquisition(
    database: Database,
    work_root: Path,
    acquisition_id: str,
    *,
    operator_id: str,
    expected_selection_sha256: str | None = None,
    promotion_hook: Callable[[str], None] | None = None,
) -> CampaignAcquisitionAttempt:
    """Retry sources that are not a verified success. Successful siblings stay in place."""
    root = work_root.resolve()
    current = _read_attempt(root, acquisition_id)
    selection = _read_selection(root, current.selection_id)
    _require_current(root, selection, expected_selection_sha256)
    _clean_partials(root)
    by_source = {item.source_id: item for item in current.results}
    results: list[CampaignAcquisitionResult] = []
    changed = False
    with _lock(root):
        for request in current.requests:
            existing = by_source.get(request.source_id)
            if existing is not None and existing.status == "succeeded" and _result_current(root, existing):
                results.append(existing)
                continue
            changed = True
            results.append(
                _acquire_one(
                    database,
                    root,
                    current.acquisition_id,
                    selection,
                    request,
                    force=True,
                    promotion_hook=promotion_hook,
                )
            )
        if not changed:
            return current
        updated = _attempt(
            root,
            current.acquisition_id,
            selection,
            operator_id,
            current.created_at,
            list(current.requests),
            results,
        )
        updated = _write_attempt(root, updated, replace=True)
    return updated


def cancel_acquisition(work_root: Path, acquisition_id: str) -> CampaignAcquisitionAttempt:
    """Mark incomplete sources cancelled and remove staging. Succeeded files stay."""
    root = work_root.resolve()
    current = _read_attempt(root, acquisition_id)
    _clean_partials(root)
    now = datetime.now(UTC)
    results: list[CampaignAcquisitionResult] = []
    for item in current.results:
        if item.status == "succeeded" and _result_current(root, item):
            results.append(item)
            continue
        results.append(
            item.model_copy(update={"status": "cancelled", "failure_code": "cancelled", "completed_at": now})
        )
    if any(item.status == "succeeded" for item in results):
        status, reason = "partial", "cancelled"
    else:
        status, reason = "cancelled", "cancelled"
    updated = current.model_copy(
        update={"results": results, "status": status, "reason_code": reason, "completed_at": now}
    )
    _write_attempt(root, updated, replace=True)
    return updated


def list_acquisitions(work_root: Path, campaign_id: str) -> list[str]:
    found: list[str] = []
    for attempt in _attempts(work_root.resolve()):
        if attempt.campaign_id == campaign_id:
            found.append(attempt.acquisition_id)
    return found


def show_acquisition(work_root: Path, acquisition_id: str) -> str:
    return _read_attempt(work_root.resolve(), acquisition_id).model_dump_json()


def verify_acquisition(database: Database, work_root: Path, acquisition_id: str) -> str:
    """Re-check hashes and probe facts. This does not write or promote."""
    del database
    root = work_root.resolve()
    attempt = _read_attempt(root, acquisition_id)
    if attempt.policy_fingerprint != policy_sha256():
        raise CampaignError("campaign policy changed", code="stale_policy")
    if attempt.status != "succeeded":
        raise CampaignError("acquisition is not succeeded", code=attempt.reason_code)
    for result in attempt.results:
        _result_current(root, result, probe=True)
    return f"PASS acquisition {attempt.acquisition_id}"


def latest_successful_result(
    work_root: Path, source_id: str, source_sha256: str
) -> CampaignAcquisitionResult | None:
    """Return a succeeded result whose file still matches. This does not write."""
    root = work_root.resolve()
    for attempt in reversed(_attempts(root)):
        for result in attempt.results:
            if result.source_id != source_id or result.status != "succeeded":
                continue
            if result.source_sha256 != source_sha256:
                continue
            try:
                _result_current(root, result)
            except CampaignError:
                continue
            return result
    return None


def write_operator_binding(
    work_root: Path,
    *,
    campaign_run_id: str,
    campaign_id: str,
    selection: CampaignSelectionDocument,
    selection_sha256: str,
    produced_sources: list[dict[str, object]],
    language: str,
    narration_enabled: bool,
) -> None:
    """Record which selection and acquisitions authorized a production run."""
    root = work_root.resolve()
    bindings: list[CampaignSourceBinding] = []
    for source in produced_sources:
        source_id = str(source["source_id"])
        digest = str(source["source_sha256"])
        acquired = latest_successful_result(root, source_id, digest)
        delivery = source.get("delivery_id")
        bindings.append(
            CampaignSourceBinding(
                source_id=source_id,
                source_sha256=digest,
                status=str(source.get("status") or "blocked"),
                cache_status=str(source.get("cache_status") or "miss"),
                reason_code=str(source.get("reason_code") or "none"),
                delivery_id=None if not isinstance(delivery, str) else delivery,
                acquisition_id=None if acquired is None else acquired.acquisition_id,
            )
        )
    document = CampaignOperatorBinding(
        campaign_run_id=campaign_run_id,
        campaign_id=campaign_id,
        selection_id=selection.selection_id,
        selection_sha256=selection_sha256,
        selection_fingerprint=selection.evidence_fingerprint,
        policy_fingerprint=selection.policy_fingerprint,
        catalogue_fingerprint=selection.catalogue_fingerprint,
        language=language,
        narration_enabled=narration_enabled,
        sources=bindings,
    )
    directory = root / "campaigns" / "runs" / campaign_run_id
    target = directory / "operator.json"
    if target.is_file() and not target.is_symlink():
        try:
            current = CampaignOperatorBinding.model_validate_json(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError):
            current = None
        if current is not None and current.model_dump_json() == document.model_dump_json():
            return
    mkdir_contained(root, directory)
    partial = target.with_name("operator.json.partial")
    partial.write_text(document.model_dump_json() + "\n", encoding="utf-8")
    partial.replace(target)


def board_acquisitions(work_root: Path, campaign_id: str) -> dict[str, object]:
    rows: list[dict[str, str]] = []
    for attempt in _attempts(work_root.resolve()):
        if attempt.campaign_id != campaign_id:
            continue
        rows.append(
            {
                "acquisition_id": attempt.acquisition_id,
                "status": attempt.status,
                "reason_code": attempt.reason_code,
                "selection_id": attempt.selection_id,
            }
        )
    return {"campaign_id": campaign_id, "acquisitions": rows, "publishing": "deferred"}


def board_acquisition(work_root: Path, acquisition_id: str) -> dict[str, object]:
    attempt = _read_attempt(work_root.resolve(), acquisition_id)
    sources: list[dict[str, object]] = []
    for result in attempt.results:
        probe = None if result.probe is None else result.probe.model_dump(mode="json")
        sources.append(
            {
                "source_id": result.source_id,
                "status": result.status,
                "failure_code": result.failure_code,
                "cache_status": result.cache_status,
                "byte_size": result.byte_size,
                "source_sha256": result.source_sha256,
                "relative_path": result.relative_path,
                "job_id": result.job_id,
                "probe": probe,
            }
        )
    payload: dict[str, object] = {
        "acquisition_id": attempt.acquisition_id,
        "campaign_id": attempt.campaign_id,
        "selection_id": attempt.selection_id,
        "status": attempt.status,
        "reason_code": attempt.reason_code,
        "policy_fingerprint": attempt.policy_fingerprint,
        "publishing": "deferred",
        "sources": sources,
    }
    _reject_leak(payload)
    return payload


def board_policy(campaign_id: str) -> dict[str, object]:
    from clipforge.campaign.antoine import CAMPAIGN_ID, POLICY_ID, antoine_policy

    if campaign_id != CAMPAIGN_ID:
        raise CampaignError("campaign is not in the local catalogue", code="missing_campaign")
    policy = antoine_policy()
    payload: dict[str, object] = {
        "campaign_id": campaign_id,
        "policy_id": POLICY_ID,
        "policy_fingerprint": policy.policy_sha256,
        "rules": [
            {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "outcome": rule.outcome,
                "description": rule.description,
            }
            for rule in policy.rules
        ],
        "publishing": "deferred",
    }
    _reject_leak(payload)
    return payload


def board_envato(work_root: Path, campaign_id: str) -> dict[str, object]:
    from clipforge.campaign.operator import _envato_records

    payload: dict[str, object] = {
        "campaign_id": campaign_id,
        "envato": "discovery_only",
        "records": _envato_records(work_root, campaign_id),
        "publishing": "deferred",
    }
    _reject_leak(payload)
    return payload


def _acquire_one(
    database: Database,
    root: Path,
    attempt_id: str,
    selection: CampaignSelectionDocument,
    request: CampaignAcquisitionRequest,
    *,
    force: bool,
    promotion_hook: Callable[[str], None] | None,
) -> CampaignAcquisitionResult:
    now = datetime.now(UTC)
    rights = _rights(request.source_id)
    if rights != "allowed":
        code = "missing_evidence" if rights == "rights_unverified" else "rights_not_allowed"
        return _unsuccessful(request, attempt_id, code, now, sha=request.expected_sha256 or _ZERO)
    try:
        source, _origin = _locate(root, database, request.source_id)
        digest = sha256_file(source)
        size = source.stat().st_size
    except CampaignError as exc:
        return _unsuccessful(request, attempt_id, exc.code, now, sha=request.expected_sha256 or _ZERO)
    if request.expected_sha256 and digest != request.expected_sha256:
        return _unsuccessful(request, attempt_id, "source_changed", now, sha=digest, size=size)
    if not force:
        reusable = _reusable(root, selection, request.source_id, request.expected_sha256 or "")
        if reusable is not None:
            return reusable.model_copy(update={"cache_status": "hit", "acquisition_id": attempt_id})
    if request.expected_size_bytes is not None and size != request.expected_size_bytes:
        return _unsuccessful(request, attempt_id, "size_mismatch", now, sha=digest, size=size)
    if size > request.max_bytes:
        return _unsuccessful(request, attempt_id, "file_size_limit", now, sha=digest, size=size)
    staging = root / "campaigns" / "acquisitions" / attempt_id / "staging" / f"{request.source_id}.partial"
    final = root / "campaigns" / "acquisitions" / attempt_id / "media" / f"{request.source_id}.mp4"
    job_id = str(uuid4())
    _insert_job(database, request, job_id, digest, JobStatus.RUNNING, None)
    try:
        _copy_contained(root, source, staging)
        if sha256_file(staging) != digest:
            raise CampaignError("staged bytes changed", code="source_changed")
        facts = _inspect(root, staging, request.media_constraints)
        if promotion_hook is not None:
            promotion_hook(request.source_id)
        mkdir_contained(root, final.parent)
        os.replace(staging, final)
        relative = final.resolve().relative_to(root).as_posix()
        _write_checksum(root, attempt_id, digest, relative)
        _finish_job(database, request, job_id, digest, JobStatus.SUCCEEDED, None)
    except (CampaignError, MediaError, OSError) as exc:
        _remove_file(staging)
        if final.is_symlink() or (final.exists() and not final.is_file()):
            _remove_file(final)
        code = exc.code if isinstance(exc, CampaignError) else "corrupt_media"
        if isinstance(exc, CampaignError) and exc.code == "promotion_failed":
            _remove_file(final)
        _finish_job(database, request, job_id, digest, JobStatus.FAILED, code)
        return _unsuccessful(request, attempt_id, code, now, sha=digest, size=size, job_id=job_id)
    relative = final.resolve().relative_to(root).as_posix()
    return CampaignAcquisitionResult(
        acquisition_id=attempt_id,
        campaign_id=request.campaign_id,
        selection_id=request.selection_id,
        project_id=request.project_id,
        source_id=request.source_id,
        source_sha256=digest,
        byte_size=size,
        probe=facts,
        relative_path=relative,
        status="succeeded",
        cache_status="miss",
        job_id=job_id,
        source_fingerprint=digest,
        policy_fingerprint=request.policy_fingerprint,
        selection_fingerprint=request.selection_fingerprint,
        failure_code=None,
        created_at=now,
        completed_at=datetime.now(UTC),
    )


def _inspect(root: Path, path: Path, constraints: MediaConstraints) -> ProbeFacts:
    _contained(root, path)
    try:
        _raw, normalized = probe_file(
            path, ProcessRunner(), video_override=None, audio_override=None, log_path=None
        )
    except MediaError as exc:
        raise CampaignError("media could not be probed", code="corrupt_media") from exc
    ffmpeg = resolve_ffmpeg()
    try:
        ProcessRunner().run(
            [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"], log_path=None, check=True
        )
    except MediaError as exc:
        raise CampaignError("media could not be decoded", code="corrupt_media") from exc
    video = normalized.video_streams[0] if normalized.video_streams else None
    audio = normalized.audio_streams[0] if normalized.audio_streams else None
    if constraints.require_video and video is None:
        raise CampaignError("video stream is missing", code="missing_video")
    if constraints.require_audio and audio is None:
        raise CampaignError("audio stream is missing", code="missing_audio")
    video_codec = "" if video is None else (video.codec_name or "")
    if (
        video is not None
        and constraints.allowed_video_codecs
        and video_codec not in constraints.allowed_video_codecs
    ):
        raise CampaignError("video codec is not allowed", code="unsupported_codec")
    audio_codec = "" if audio is None else (audio.codec_name or "")
    if (
        audio is not None
        and constraints.allowed_audio_codecs
        and audio_codec not in constraints.allowed_audio_codecs
    ):
        raise CampaignError("audio codec is not allowed", code="unsupported_codec")
    width = None if video is None else video.width
    height = None if video is None else video.height
    if video is not None and (
        width is None or height is None or width < constraints.min_width or height < constraints.min_height
    ):
        raise CampaignError("video dimensions are outside the campaign constraints", code="unsupported_media")
    too_wide = (
        width is not None
        and height is not None
        and (width > constraints.max_width or height > constraints.max_height)
    )
    if video is not None and too_wide:
        raise CampaignError("video dimensions are outside the campaign constraints", code="unsupported_media")
    duration = normalized.timeline.canonical_duration_us
    if duration < constraints.min_duration_us or duration > constraints.max_duration_us:
        raise CampaignError("duration is outside the campaign constraints", code="unsupported_media")
    frame_rate = None
    if video is not None and video.avg_frame_rate is not None:
        frame_rate = f"{video.avg_frame_rate.numerator}/{video.avg_frame_rate.denominator}"
        if constraints.frame_rate_numerator is not None and (
            video.avg_frame_rate.numerator != constraints.frame_rate_numerator
            or video.avg_frame_rate.denominator != constraints.frame_rate_denominator
        ):
            raise CampaignError("frame rate is outside the campaign constraints", code="unsupported_media")
    sample_rate = None if audio is None else audio.sample_rate
    if constraints.sample_rate is not None and sample_rate != constraints.sample_rate:
        raise CampaignError("sample rate is outside the campaign constraints", code="unsupported_media")
    format_name = None if normalized.format.format_name is None else normalized.format.format_name.split(",")[0]
    return ProbeFacts(
        duration_us=duration,
        width=width,
        height=height,
        video_codec=None if video is None else video.codec_name,
        audio_codec=None if audio is None else audio.codec_name,
        frame_rate=frame_rate,
        sample_rate=sample_rate,
        format_name=format_name,
    )


def _locate(root: Path, database: Database, source_id: str) -> tuple[Path, str]:
    uri = _uri(database, source_id)
    if uri is not None:
        lowered = uri.lower()
        if lowered.startswith(("http://", "https://", "s3://", "ftp://", "ftps://")):
            raise CampaignError("remote source is not permitted", code="remote_source")
        if "\\" in uri:
            raise CampaignError("backslash path is not permitted", code="backslash")
        if ".." in uri.split("/"):
            raise CampaignError("traversal path is not permitted", code="traversal")
        if not lowered.startswith("file:"):
            raise CampaignError("remote source is not permitted", code="remote_source")
        bound = path_from_file_uri(uri)
        try:
            reject_symlink_chain(bound)
        except MediaError as exc:
            raise CampaignError("source path is a symlink", code="symlink") from exc
        try:
            ensure_within(root, bound)
        except MediaError as exc:
            incoming = root / "incoming" / f"{source_id}.mp4"
            if incoming.exists() or incoming.is_symlink():
                _contained(root, incoming)
                return incoming, "local_incoming"
            raise CampaignError("source is outside the work root", code="outside_root") from exc
        if bound.is_file():
            return bound, "local_work"
    incoming = root / "incoming" / f"{source_id}.mp4"
    if incoming.exists() or incoming.is_symlink():
        _contained(root, incoming)
        return incoming, "local_incoming"
    raise CampaignError("campaign source file is missing", code="missing_source")


def _contained(root: Path, path: Path) -> None:
    try:
        reject_symlink_chain(path)
        ensure_within(root, path)
    except MediaError as exc:
        message = str(exc).lower()
        code = "symlink" if "symlink" in message else "outside_root"
        raise CampaignError("source path is not a contained file", code=code) from exc
    if not path.is_file():
        raise CampaignError("campaign source file is missing", code="missing_source")


def _copy_contained(root: Path, source: Path, target: Path) -> None:
    _contained(root, source)
    mkdir_contained(root, target.parent)
    partial = target
    try:
        with source.open("rb") as incoming, partial.open("xb") as outgoing:
            while True:
                block = incoming.read(1024 * 1024)
                if not block:
                    break
                outgoing.write(block)
    except OSError as exc:
        _remove_file(partial)
        raise CampaignError("staged copy failed", code="promotion_failed") from exc


def _write_checksum(root: Path, attempt_id: str, digest: str, relative: str) -> None:
    path = root / "campaigns" / "acquisitions" / attempt_id / "checksums.sha256"
    mkdir_contained(root, path.parent)
    line = f"{digest}  {relative}\n"
    existing = ""
    if path.is_file() and not path.is_symlink():
        existing = path.read_text(encoding="utf-8")
    if line in existing:
        return
    path.write_text(existing + line, encoding="utf-8")


def _request(
    selection: CampaignSelectionDocument,
    source_id: str,
    expected_sha: str,
    operator_id: str,
    created: datetime,
    max_bytes: int,
    constraints: MediaConstraints,
    database: Database,
    expected_size_bytes: int | None,
) -> CampaignAcquisitionRequest:
    catalogue = {item.source_id: item for item in inventory_sources()}
    item = catalogue.get(source_id)
    display = source_id if item is None else item.display_name
    size = (
        expected_size_bytes
        if expected_size_bytes is not None
        else _manifest_size(database, source_id, expected_sha)
    )
    return CampaignAcquisitionRequest(
        campaign_id=selection.campaign_id,
        selection_id=selection.selection_id,
        project_id=selection.project_id,
        source_id=source_id,
        display_name=display,
        origin="catalogue",
        expected_sha256=expected_sha,
        expected_size_bytes=size,
        max_bytes=max_bytes,
        media_constraints=constraints,
        policy_fingerprint=selection.policy_fingerprint,
        selection_fingerprint=selection.evidence_fingerprint,
        catalogue_fingerprint=selection.catalogue_fingerprint,
        operator_id=operator_id,
        created_at=created,
    )


def _unsuccessful(
    request: CampaignAcquisitionRequest,
    attempt_id: str,
    code: str,
    created: datetime,
    *,
    sha: str | None = None,
    size: int = 0,
    job_id: str | None = None,
) -> CampaignAcquisitionResult:
    digest = sha or request.expected_sha256 or _ZERO
    return CampaignAcquisitionResult(
        acquisition_id=attempt_id,
        campaign_id=request.campaign_id,
        selection_id=request.selection_id,
        project_id=request.project_id,
        source_id=request.source_id,
        source_sha256=digest,
        byte_size=size,
        probe=None,
        relative_path=None,
        status="cancelled"
        if code == "cancelled"
        else "blocked"
        if code in {"rights_not_allowed", "missing_evidence"}
        else "failed",
        cache_status="miss",
        job_id=job_id,
        source_fingerprint=digest,
        policy_fingerprint=request.policy_fingerprint,
        selection_fingerprint=request.selection_fingerprint,
        failure_code=code,
        created_at=created,
        completed_at=datetime.now(UTC),
    )


def _attempt(
    root: Path,
    attempt_id: str,
    selection: CampaignSelectionDocument,
    operator_id: str,
    created: datetime,
    requests: list[CampaignAcquisitionRequest],
    results: list[CampaignAcquisitionResult],
) -> CampaignAcquisitionAttempt:
    states = [item.status for item in results]
    if states and all(item == "succeeded" for item in states):
        status, reason = "succeeded", "none"
    elif any(item == "succeeded" for item in states):
        status, reason = (
            "partial",
            next(item.failure_code or "partial" for item in results if item.status != "succeeded"),
        )
    elif any(item == "cancelled" for item in states):
        status, reason = "cancelled", "cancelled"
    elif any(item == "blocked" for item in states):
        status, reason = (
            "blocked",
            next(item.failure_code or "blocked" for item in results if item.failure_code),
        )
    else:
        status, reason = (
            "failed",
            next((item.failure_code or "failed" for item in results if item.failure_code), "failed"),
        )
    return CampaignAcquisitionAttempt(
        acquisition_id=attempt_id,
        campaign_id=selection.campaign_id,
        selection_id=selection.selection_id,
        project_id=selection.project_id,
        selection_sha256=_file_sha(root, selection.selection_id),
        selection_fingerprint=selection.evidence_fingerprint,
        policy_fingerprint=selection.policy_fingerprint,
        catalogue_fingerprint=selection.catalogue_fingerprint,
        operator_id=operator_id,
        created_at=created,
        completed_at=datetime.now(UTC),
        status=status,  # type: ignore[arg-type]
        reason_code=reason,
        requests=requests,
        results=results,
    )


def _insert_job(
    database: Database,
    request: CampaignAcquisitionRequest,
    job_id: str,
    digest: str,
    status: JobStatus,
    error_code: str | None,
) -> None:
    now = datetime.now(UTC)
    record = JobRecord(
        job_id=job_id,
        project_id=request.project_id,
        kind=_KIND,
        status=status,
        created_at=now,
        updated_at=now,
        error_message=None if status is not JobStatus.FAILED else (error_code or "failed"),
        payload={
            "acquisition_id": request.selection_id,
            "source_id": request.source_id,
            "source_sha256": digest,
            "selection_id": request.selection_id,
            "policy_fingerprint": request.policy_fingerprint,
        },
    )
    with database.transaction() as connection:
        insert_job(connection, record)


def _finish_job(
    database: Database,
    request: CampaignAcquisitionRequest,
    job_id: str,
    digest: str,
    status: JobStatus,
    error_code: str | None,
) -> None:
    now = datetime.now(UTC)
    with database.transaction() as connection:
        current = connection.execute("SELECT created_at FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        created = now if current is None else datetime.fromisoformat(str(current["created_at"]))
        record = JobRecord(
            job_id=job_id,
            project_id=request.project_id,
            kind=_KIND,
            status=status,
            created_at=created,
            updated_at=now,
            error_message=None if status is not JobStatus.FAILED else (error_code or "failed"),
            payload={
                "acquisition_id": job_id,
                "source_id": request.source_id,
                "source_sha256": digest,
                "selection_id": request.selection_id,
                "policy_fingerprint": request.policy_fingerprint,
            },
        )
        update_job(connection, record)


def _matching_attempt(
    database: Database, root: Path, selection: CampaignSelectionDocument
) -> CampaignAcquisitionAttempt | None:
    wanted = {item.source_id: item.source_sha256 for item in selection.sources}
    file_sha = _file_sha(root, selection.selection_id)
    for attempt in reversed(_attempts(root)):
        if attempt.selection_id != selection.selection_id or attempt.status != "succeeded":
            continue
        if attempt.selection_sha256 != file_sha or attempt.policy_fingerprint != selection.policy_fingerprint:
            continue
        if not _inputs_match(database, root, selection):
            continue
        found = {item.source_id: item for item in attempt.results}
        if set(found) != set(wanted):
            continue
        if any(
            found[key].source_sha256 != digest or found[key].status != "succeeded"
            for key, digest in wanted.items()
        ):
            continue
        try:
            for item in found.values():
                _result_current(root, item)
        except CampaignError:
            continue
        return attempt
    return None


def _inputs_match(database: Database, root: Path, selection: CampaignSelectionDocument) -> bool:
    for choice in selection.sources:
        try:
            path, _origin = _locate(root, database, choice.source_id)
        except CampaignError:
            return False
        if sha256_file(path) != choice.source_sha256:
            return False
    return True


def _reusable(
    root: Path, selection: CampaignSelectionDocument, source_id: str, source_sha256: str
) -> CampaignAcquisitionResult | None:
    for attempt in reversed(_attempts(root)):
        if attempt.policy_fingerprint != selection.policy_fingerprint:
            continue
        for result in attempt.results:
            if result.source_id != source_id or result.status != "succeeded":
                continue
            if result.source_sha256 != source_sha256:
                continue
            try:
                _result_current(root, result)
            except CampaignError:
                continue
            return result
    return None


def _result_current(root: Path, result: CampaignAcquisitionResult, *, probe: bool = False) -> bool:
    if result.status != "succeeded" or result.relative_path is None or result.probe is None:
        raise CampaignError("acquisition is not succeeded", code=result.failure_code or "failed")
    path = root / result.relative_path
    _contained(root, path)
    if path.stat().st_size != result.byte_size:
        raise CampaignError("acquired file size changed", code="size_mismatch")
    if sha256_file(path) != result.source_sha256:
        raise CampaignError("acquired file hash changed", code="source_changed")
    if probe:
        facts = _inspect(root, path, MediaConstraints())
        if facts.duration_us != result.probe.duration_us or facts.video_codec != result.probe.video_codec:
            raise CampaignError("acquired probe facts changed", code="source_changed")
    return True


def _require_current(root: Path, selection: CampaignSelectionDocument, expected: str | None) -> None:
    from clipforge.campaign.operator import catalogue_fingerprint

    if selection.catalogue_fingerprint != catalogue_fingerprint(selection.campaign_id):
        raise CampaignError("campaign catalogue changed", code="stale_catalogue")
    if selection.policy_fingerprint != policy_sha256():
        raise CampaignError("campaign policy changed", code="stale_policy")
    current = _file_sha(root, selection.selection_id)
    if expected is not None and expected != current:
        raise CampaignError(_RELOAD, code="stale_selection")


def _read_selection(root: Path, selection_id: str) -> CampaignSelectionDocument:
    if "/" in selection_id or "\\" in selection_id or ".." in selection_id:
        raise CampaignError("selection id is not safe", code="malformed_id")
    path = root / "campaigns" / "selections" / selection_id / "selection.json"
    if path.is_symlink() or not path.is_file():
        raise CampaignError("campaign selection is missing", code="missing_selection")
    try:
        return CampaignSelectionDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise CampaignError("campaign selection was rejected", code="invalid_document") from exc


def _attempts(root: Path) -> list[CampaignAcquisitionAttempt]:
    base = root / "campaigns" / "acquisitions"
    if not base.is_dir():
        return []
    found: list[CampaignAcquisitionAttempt] = []
    for path in sorted(base.glob("*/manifest.json")):
        if path.is_symlink():
            continue
        try:
            found.append(CampaignAcquisitionAttempt.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ValidationError, ValueError):
            continue
    return sorted(found, key=lambda item: (item.created_at, item.acquisition_id))


def _read_attempt(root: Path, acquisition_id: str) -> CampaignAcquisitionAttempt:
    if "/" in acquisition_id or "\\" in acquisition_id or ".." in acquisition_id:
        raise CampaignError("acquisition id is not safe", code="malformed_id")
    path = root / "campaigns" / "acquisitions" / acquisition_id / "manifest.json"
    if path.is_symlink() or not path.is_file():
        raise CampaignError("acquisition is missing", code="missing_acquisition")
    try:
        return CampaignAcquisitionAttempt.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise CampaignError("acquisition was rejected", code="invalid_document") from exc


def _write_attempt(
    root: Path, attempt: CampaignAcquisitionAttempt, *, replace: bool = False
) -> CampaignAcquisitionAttempt:
    directory = root / "campaigns" / "acquisitions" / attempt.acquisition_id
    target = directory / "manifest.json"
    if target.exists() and not replace:
        raise CampaignError("acquisition already exists", code="duplicate_acquisition")
    mkdir_contained(root, directory)
    partial = target.with_name("manifest.json.partial")
    partial.write_text(attempt.model_dump_json() + "\n", encoding="utf-8")
    partial.replace(target)
    return attempt


def _file_sha(root: Path, selection_id: str) -> str:
    path = root / "campaigns" / "selections" / selection_id / "selection.json"
    return sha256_file(path)


def _rights(source_id: str) -> str:
    for item in inventory_sources():
        if item.source_id == source_id:
            return str(item.rights_state)
    return "unknown"


def _uri(database: Database, source_id: str) -> str | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT source_asset_id FROM source_manifests WHERE original_filename = ?",
            (f"{source_id}.mp4",),
        ).fetchone()
        if row is None:
            return None
        found = connection.execute(
            "SELECT uri FROM source_assets WHERE source_asset_id = ?",
            (str(row["source_asset_id"]),),
        ).fetchone()
    if found is None:
        return None
    return str(found["uri"])


def _manifest_size(database: Database, source_id: str, expected_sha: str) -> int | None:
    with database.connect() as connection:
        row = connection.execute(
            "SELECT size_bytes, content_sha256 FROM source_manifests WHERE original_filename = ?",
            (f"{source_id}.mp4",),
        ).fetchone()
    if row is None or str(row["content_sha256"]) != expected_sha:
        return None
    return int(row["size_bytes"])


def _clean_partials(root: Path) -> None:
    base = root / "campaigns" / "acquisitions"
    if not base.is_dir():
        return
    for partial in base.glob("*/staging/*.partial"):
        try:
            ensure_within(root, partial)
        except MediaError:
            continue
        _remove_file(partial)


def _remove_file(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        with suppress(OSError):
            path.unlink()


@contextmanager
def _lock(root: Path) -> Iterator[None]:
    directory = root / "campaigns" / "acquisitions"
    mkdir_contained(root, directory)
    lock_path = directory / ".lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o644)
    except OSError as exc:
        raise CampaignError("acquisition lock could not be opened", code="symlink") from exc
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        with suppress(OSError):
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reject_leak(payload: dict[str, object]) -> None:
    import json

    text = json.dumps(payload).lower()
    if any(token in text for token in ("/home/", "/tmp/", "/users/", "file://", "bearer ", "token=")):
        raise CampaignError("campaign board payload contains a path or a secret", code="invalid_document")
