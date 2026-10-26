"""Request-to-asset provenance helpers for the treatment stage.

Provider adapters remain in ``clipforge.assets``. This module only binds their
verified outputs to a treatment request and a direction placement.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_file_uri, confine_work_path, require_asset
from clipforge.media.clock import seconds_text_to_us, us_to_seconds_str
from clipforge.media.hashing import sha256_file
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import SourceWorkspace, atomic_replace, mkdir_contained
from clipforge.schemas.direction import DirectionAssetPlacement, TreatmentAssetBindingDocument
from clipforge.schemas.editorial import OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.treatment import (
    TreatmentAssetObservation,
    TreatmentAssetRequest,
    TreatmentAssetVerification,
    TreatmentObservationFrame,
)
from clipforge.storage import Database
from clipforge.transcription.io import publish_json


def verify_registered_treatment_asset(
    *,
    work_root: Path,
    database: Database,
    project_id: str,
    source_asset_id: str,
    provider: str,
    provider_response_sha256: str,
    selection_id: str,
    acquisition_id: str,
    license_evidence_sha256: str,
    registered_asset_id: str,
    registered_asset_sha256: str,
    media_kind: str,
) -> TreatmentAssetVerification:
    """Verify a provider/acquisition/license chain using existing asset gates."""
    if provider == "envato":
        from clipforge.assets.handoff import assert_envato_registration, show_envato_asset

        registration = show_envato_asset(work_root, registered_asset_id)
        if registration.request_id != selection_id or registration.project_id != project_id:
            raise MediaError("Envato treatment asset selection or project binding is stale")
        if acquisition_id not in {registered_asset_id, registration.producer_job_id}:
            raise MediaError("Envato treatment acquisition binding is stale")
        request_path = work_root / "campaigns" / "envato-requests" / registration.request_id / "request.json"
        request_path = confine_work_path(
            work_root, request_path.relative_to(work_root).as_posix(), label="Envato request"
        )
        if sha256_file(request_path) != provider_response_sha256:
            raise MediaError("Envato treatment provider response hash changed")
        if registration.acquisition_status != "verified" or registration.sha256 is None:
            raise MediaError("Envato treatment asset is not verified")
        checked = assert_envato_registration(
            work_root,
            database,
            registered_asset_id,
            project_id=project_id,
            file_sha256=registered_asset_sha256,
        )
        if checked.sha256 != registered_asset_sha256 or checked.media_kind not in {
            "audio",
            "video",
            "image",
            "graphic",
        }:
            raise MediaError("Envato treatment asset bytes or media kind do not match")
        if checked.media_kind == "audio" and media_kind != "audio":
            raise MediaError("Envato treatment media kind does not match the request")
        if checked.media_kind != "audio" and media_kind != "graphic":
            raise MediaError("Envato treatment media kind does not match the request")
        if not checked.license_evidence:
            raise MediaError("Envato treatment license evidence is missing")
        evidence_path = confine_work_path(work_root, checked.license_evidence, label="Envato license evidence")
        evidence_hash = sha256_file(evidence_path)
        if evidence_hash != license_evidence_sha256:
            raise MediaError("Envato treatment license evidence hash changed")
        return TreatmentAssetVerification(
            provider="envato",
            provider_response_sha256=provider_response_sha256,
            selection_id=selection_id,
            acquisition_id=acquisition_id,
            license_evidence_sha256=evidence_hash,
            registered_asset_id=registered_asset_id,
            registered_asset_sha256=checked.sha256,
            media_kind=media_kind,  # type: ignore[arg-type]
        )
    if provider == "openverse":
        from clipforge.assets.openverse import _require_registered_acquisition, load_acquisition

        manifest_path = work_root / "assets" / "openverse" / "acquisitions" / acquisition_id / "manifest.json"
        manifest = load_acquisition(manifest_path, work_root=work_root)
        if manifest.selection_id != selection_id or manifest.asset_id != registered_asset_id:
            raise MediaError("Openverse treatment acquisition binding is stale")
        if manifest.selection_response_sha256 != provider_response_sha256:
            raise MediaError("Openverse treatment provider response hash changed")
        if manifest.project_id != project_id or manifest.source_asset_id != source_asset_id:
            raise MediaError("Openverse treatment project/source binding is stale")
        _require_registered_acquisition(manifest, database=database, root=work_root)
        if manifest.file_sha256 != registered_asset_sha256:
            raise MediaError("Openverse treatment asset bytes changed")
        evidence = (
            work_root / "assets" / "openverse" / "acquisitions" / acquisition_id / "license-evidence.json"
        )
        if sha256_file(evidence) != license_evidence_sha256:
            raise MediaError("Openverse treatment license evidence changed")
        expected_kind = "audio" if manifest.media_type == "audio" else "graphic"
        if expected_kind != media_kind:
            raise MediaError("Openverse treatment media kind does not match the request")
        return TreatmentAssetVerification(
            provider="openverse",
            provider_response_sha256=provider_response_sha256,
            selection_id=selection_id,
            acquisition_id=acquisition_id,
            license_evidence_sha256=license_evidence_sha256,
            registered_asset_id=registered_asset_id,
            registered_asset_sha256=registered_asset_sha256,
            media_kind=media_kind,  # type: ignore[arg-type]
        )
    if provider == "local":
        entry, license_record, media = require_asset(
            database,
            SourceWorkspace(work_root, project_id, source_asset_id),
            project_id=project_id,
            asset_id=registered_asset_id,
            expected_kind=media_kind,
            work_root=work_root,
        )
        if sha256_file(media) != registered_asset_sha256:
            raise MediaError("local treatment asset bytes changed")
        evidence = confine_file_uri(work_root, license_record.evidence_uri or "", label="license evidence")
        if sha256_file(evidence) != license_evidence_sha256:
            raise MediaError("local treatment license evidence changed")
        if entry.file_sha256 != registered_asset_sha256:
            raise MediaError("local treatment catalog hash changed")
        return TreatmentAssetVerification(
            provider="local",
            provider_response_sha256=provider_response_sha256,
            selection_id=selection_id,
            acquisition_id=acquisition_id,
            license_evidence_sha256=license_evidence_sha256,
            registered_asset_id=registered_asset_id,
            registered_asset_sha256=registered_asset_sha256,
            media_kind=media_kind,  # type: ignore[arg-type]
        )
    raise MediaError(f"unsupported treatment asset provider: {provider}")


def observe_registered_visual_asset(
    *,
    database: Database,
    work_root: Path,
    project_id: str,
    source_asset_id: str,
    asset_id: str,
    output_interval: OutputInterval,
    source_evidence_ids: list[str],
    observed_labels: list[str],
    relevance_score: float,
    relevance_threshold: float,
    reviewed_by: str,
    review_note: str,
) -> tuple[Path, TreatmentAssetObservation]:
    """Decode representative frames for a registered visual treatment asset."""
    _entry, _license, media = require_asset(
        database,
        SourceWorkspace(work_root, project_id, source_asset_id),
        project_id=project_id,
        asset_id=asset_id,
        expected_kind="graphic",
        work_root=work_root,
    )
    media_sha = sha256_file(media)
    probe = read_ffprobe_json(media, ProcessRunner(), log_path=None)
    video = next(
        (
            item
            for item in probe.get("streams", [])
            if isinstance(item, dict) and item.get("codec_type") == "video"
        ),
        None,
    )
    if video is None:
        raise MediaError("visual treatment asset has no decodable video/image stream")
    duration_us = seconds_text_to_us(video.get("duration")) or 0
    timestamps = [0] if duration_us <= 1 else sorted({0, duration_us // 2})
    observation_id = (
        "observation-"
        + hashlib.sha256(
            json.dumps(
                [
                    asset_id,
                    media_sha,
                    output_interval.model_dump(mode="json"),
                    source_evidence_ids,
                    observed_labels,
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
    )
    root = work_root.resolve()
    directory = root / "editorial" / "treatment-observations" / observation_id / "frames"
    mkdir_contained(root, directory)
    frames: list[TreatmentObservationFrame] = []
    runner = ProcessRunner()
    for index, timestamp_us in enumerate(timestamps):
        final = directory / f"frame-{index:03d}.jpg"
        partial = directory / f".{final.stem}.{uuid.uuid4().hex}.partial.jpg"
        runner.run(
            [
                resolve_ffmpeg(),
                "-y",
                "-v",
                "error",
                "-ss",
                us_to_seconds_str(timestamp_us),
                "-i",
                str(media),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(partial),
            ],
            timeout_s=90,
            reap_group=True,
        )
        if not partial.is_file() or partial.stat().st_size <= 0:
            raise MediaError(f"could not decode treatment observation frame {index}")
        atomic_replace(partial, final, root)
        frames.append(
            TreatmentObservationFrame(
                relative_path=final.relative_to(root).as_posix(),
                sha256=sha256_file(final),
                timestamp_us=timestamp_us,
            )
        )
    observation = TreatmentAssetObservation(
        observation_id=observation_id,
        asset_id=asset_id,
        source_asset_id=source_asset_id,
        media_sha256=media_sha,
        output_interval=output_interval,
        source_evidence_ids=source_evidence_ids,
        frames=frames,
        observed_labels=observed_labels,
        relevance_score=relevance_score,
        relevance_threshold=relevance_threshold,
        reviewed_by=reviewed_by,
        review_note=review_note,
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by=reviewed_by,
            tool="clipforge treatment observe-asset",
            tool_version="1.0.0",
            source_asset_ids=[source_asset_id],
            parent_artifact_ids=[asset_id],
            inputs_sha256=media_sha,
        ),
    )
    target = directory.parent / "observation.json"
    confine_work_path(root, target.relative_to(root).as_posix(), label="treatment observation")
    publish_json(target, observation, root, directory.parent / f".observation.{uuid.uuid4().hex}.partial.json")
    return target, observation


def bind_acquired_request(
    request: TreatmentAssetRequest,
    *,
    verification: TreatmentAssetVerification,
) -> TreatmentAssetRequest:
    """Return an immutable acquired request after checking all provenance ids."""
    expected_kind = "graphic" if request.kind == "graphic" else "audio"
    if request.status != "selected":
        raise MediaError(f"treatment request must be selected before acquisition: {request.request_id}")
    if verification.provider not in request.provider_classes:
        raise MediaError("verified treatment provider was not allowed by the request")
    if (
        request.provider_response_sha256 != verification.provider_response_sha256
        or request.selection_id != verification.selection_id
    ):
        raise MediaError("verified treatment acquisition changed its selected provider evidence")
    if verification.media_kind != expected_kind:
        raise MediaError("verified treatment asset kind does not match the request")
    try:
        payload = request.model_dump(mode="json")
        payload.update(
            {
                "status": "acquired",
                "provider_response_sha256": verification.provider_response_sha256,
                "selection_id": verification.selection_id,
                "acquisition_id": verification.acquisition_id,
                "license_evidence_sha256": verification.license_evidence_sha256,
                "registered_asset_id": verification.registered_asset_id,
                "registered_asset_sha256": verification.registered_asset_sha256,
            }
        )
        return TreatmentAssetRequest.model_validate(payload)
    except ValidationError as exc:
        raise MediaError(f"acquired treatment asset evidence is invalid: {exc}") from exc


def select_treatment_request(
    request: TreatmentAssetRequest,
    *,
    provider_response_sha256: str,
    selection_id: str,
) -> TreatmentAssetRequest:
    """Record the immutable provider selection before acquisition verification."""
    if request.status != "pending":
        raise MediaError(f"treatment request is not pending: {request.request_id}")
    try:
        payload = request.model_dump(mode="json")
        payload.update(
            {
                "status": "selected",
                "provider_response_sha256": provider_response_sha256,
                "selection_id": selection_id,
            }
        )
        return TreatmentAssetRequest.model_validate(payload)
    except ValidationError as exc:
        raise MediaError(f"treatment selection evidence is invalid: {exc}") from exc


def bind_placement_to_request(
    placement: DirectionAssetPlacement,
    request: TreatmentAssetRequest,
) -> DirectionAssetPlacement:
    """Bind a selected local placement to its acquired treatment request."""
    if request.status != "acquired":
        raise MediaError(f"treatment request is not acquired: {request.request_id}")
    expected_kind = "graphic" if request.kind == "graphic" else "audio"
    if placement.kind != expected_kind:
        raise MediaError("treatment placement kind does not match its request")
    if request.registered_asset_id != placement.asset_id:
        raise MediaError("treatment placement asset does not match its acquired request")
    try:
        payload = placement.model_dump(mode="json")
        payload.update(
            {
                "request_id": request.request_id,
                "provider_response_sha256": request.provider_response_sha256,
                "selection_id": request.selection_id,
                "acquisition_id": request.acquisition_id,
                "license_evidence_sha256": request.license_evidence_sha256,
                "registered_asset_sha256": request.registered_asset_sha256,
                "asset_status": "acquired",
            }
        )
        return DirectionAssetPlacement.model_validate(payload)
    except ValidationError as exc:
        raise MediaError(f"treatment placement evidence is invalid: {exc}") from exc


def validate_placement_request_binding(
    placement: DirectionAssetPlacement,
    request: TreatmentAssetRequest,
) -> None:
    """Fail closed when an immutable placement no longer matches its request."""
    bound = bind_placement_to_request(placement, request)
    if bound != placement:
        raise MediaError(f"treatment placement provenance is stale: {placement.placement_id}")


def persist_treatment_binding(
    *,
    work_root: Path,
    request: TreatmentAssetRequest,
    placement: DirectionAssetPlacement,
    verification: TreatmentAssetVerification,
    source_asset_id: str,
    observation_path: Path | None = None,
) -> Path:
    """Persist an immutable typed binding handoff under the ignored work root."""
    observation = None
    observation_sha256 = None
    if observation_path is not None:
        try:
            observation_path = confine_work_path(
                work_root,
                observation_path.absolute().relative_to(work_root.resolve()).as_posix(),
                label="treatment observation",
            )
        except (ValueError, MediaError) as exc:
            raise MediaError("treatment observation is outside the work root") from exc
        if observation_path.is_symlink() or not observation_path.is_file():
            raise MediaError("treatment observation is missing or unsafe")
        try:
            observation = TreatmentAssetObservation.model_validate_json(
                observation_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise MediaError("treatment observation is invalid") from exc
        if observation.asset_id != placement.asset_id or placement.kind != "graphic":
            raise MediaError("treatment observation does not match the visual placement")
        if observation.media_sha256 != verification.registered_asset_sha256:
            raise MediaError("treatment observation asset bytes are stale")
        observation_sha256 = sha256_file(observation_path)
        placement = placement.model_copy(
            update={"observation_id": observation.observation_id, "observation_sha256": observation_sha256}
        )
    identity = hashlib.sha256(
        json.dumps(
            [
                request.model_dump(mode="json"),
                placement.model_dump(mode="json"),
                verification.model_dump(mode="json"),
                None if observation is None else observation.model_dump(mode="json"),
                source_asset_id,
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    binding_id = f"binding-{identity}"
    now = datetime.now(UTC)
    document = TreatmentAssetBindingDocument(
        binding_id=binding_id,
        request=request,
        placement=placement,
        verification=verification,
        observation=observation,
        created_at=now,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by="codex_operator",
            tool="clipforge treatment bind-asset",
            tool_version="1.0.0",
            source_asset_ids=[source_asset_id],
            inputs_sha256=verification.registered_asset_sha256,
        ),
    )
    directory = work_root / "editorial" / "treatment-bindings"
    mkdir_contained(work_root, directory)
    target = directory / f"{binding_id}.json"
    confine_work_path(work_root, target.relative_to(work_root).as_posix(), label="treatment binding")
    if target.is_symlink():
        raise MediaError("treatment binding target is a symlink")
    if target.exists():
        existing = TreatmentAssetBindingDocument.model_validate_json(target.read_text(encoding="utf-8"))
        if (
            existing.request != request
            or existing.placement != placement
            or existing.verification != verification
            or existing.provenance.source_asset_ids != [source_asset_id]
        ):
            raise MediaError("treatment binding id is immutable and already has different evidence")
        return target
    partial = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.partial.json")
    try:
        publish_json(target, document, work_root, partial)
    finally:
        partial.unlink(missing_ok=True)
    return target
