"""Request-to-asset provenance helpers for the treatment stage.

Provider adapters remain in ``clipforge.assets``. This module only binds their
verified outputs to a treatment request and a direction placement.
"""

from __future__ import annotations

from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.schemas.direction import DirectionAssetPlacement
from clipforge.schemas.treatment import TreatmentAssetRequest


def bind_acquired_request(
    request: TreatmentAssetRequest,
    *,
    provider_response_sha256: str,
    selection_id: str,
    acquisition_id: str,
    license_evidence_sha256: str,
    registered_asset_id: str,
    registered_asset_sha256: str,
) -> TreatmentAssetRequest:
    """Return an immutable acquired request after checking all provenance ids."""
    if not all(
        (
            provider_response_sha256,
            selection_id,
            acquisition_id,
            license_evidence_sha256,
            registered_asset_id,
            registered_asset_sha256,
        )
    ):
        raise MediaError("acquired treatment assets require provider, selection, license, and asset evidence")
    try:
        payload = request.model_dump(mode="json")
        payload.update(
            {
                "status": "acquired",
                "provider_response_sha256": provider_response_sha256,
                "selection_id": selection_id,
                "acquisition_id": acquisition_id,
                "license_evidence_sha256": license_evidence_sha256,
                "registered_asset_id": registered_asset_id,
                "registered_asset_sha256": registered_asset_sha256,
            }
        )
        return TreatmentAssetRequest.model_validate(payload)
    except ValidationError as exc:
        raise MediaError(f"acquired treatment asset evidence is invalid: {exc}") from exc


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
