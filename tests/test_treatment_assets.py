from __future__ import annotations

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.treatment_assets import (
    bind_acquired_request,
    bind_placement_to_request,
    select_treatment_request,
)
from clipforge.schemas.direction import DirectionAssetPlacement
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.treatment import TreatmentAssetRequest, TreatmentAssetVerification


def _request() -> TreatmentAssetRequest:
    return TreatmentAssetRequest(
        request_id="request-1",
        beat_id="beat-1",
        kind="graphic",
        role="context",
        query_terms=["context", "example"],
        provider_classes=["local", "envato"],
        interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
        source_evidence_ids=["evidence-1"],
    )


def test_acquired_request_and_placement_share_provenance() -> None:
    request = bind_acquired_request(
        select_treatment_request(_request(), provider_response_sha256="a" * 64, selection_id="selection-1"),
        verification=TreatmentAssetVerification(
            provider="envato",
            provider_response_sha256="a" * 64,
            selection_id="selection-1",
            acquisition_id="acquisition-1",
            license_evidence_sha256="b" * 64,
            registered_asset_id="asset-1",
            registered_asset_sha256="c" * 64,
            media_kind="graphic",
        ),
    )
    placement = bind_placement_to_request(
        DirectionAssetPlacement(
            placement_id="placement-1",
            asset_id="asset-1",
            kind="graphic",
            interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
            source_evidence_ids=["evidence-1"],
            purpose=MotionPurpose.CONCEPT,
            relevance_note="context",
            asset_tags=["context"],
        ),
        request,
    )
    assert placement.request_id == request.request_id
    assert placement.asset_status == "acquired"
    assert placement.license_evidence_sha256 == "b" * 64


def test_acquisition_requires_a_prior_selection() -> None:
    verification = TreatmentAssetVerification(
        provider="envato",
        provider_response_sha256="a" * 64,
        selection_id="selection-1",
        acquisition_id="acquisition-1",
        license_evidence_sha256="b" * 64,
        registered_asset_id="asset-1",
        registered_asset_sha256="c" * 64,
        media_kind="graphic",
    )
    with pytest.raises(MediaError, match="must be selected"):
        bind_acquired_request(_request(), verification=verification)


def test_unacquired_request_cannot_bind() -> None:
    placement = DirectionAssetPlacement(
        placement_id="placement-1",
        asset_id="asset-1",
        kind="graphic",
        interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
        source_evidence_ids=["evidence-1"],
        purpose=MotionPurpose.CONCEPT,
        relevance_note="context",
    )
    with pytest.raises(MediaError, match="not acquired"):
        bind_placement_to_request(placement, _request())


def test_acquisition_binding_rejects_unhashed_provider_evidence() -> None:
    with pytest.raises(ValidationError, match="provider_response_sha256"):
        TreatmentAssetVerification(
            provider="envato",
            provider_response_sha256="provider-response",
            selection_id="selection-1",
            acquisition_id="acquisition-1",
            license_evidence_sha256="b" * 64,
            registered_asset_id="asset-1",
            registered_asset_sha256="c" * 64,
            media_kind="graphic",
        )
