"""Treatment revisions must change the direction actually consumed by rendering."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.editorial.presets import PresetCatalog
from clipforge.errors import MediaError
from clipforge.hero.direction_service import apply_treatment_bindings
from clipforge.hero.treatment import materialize_treatment, treatment_fingerprint
from clipforge.hero.treatment_assets import (
    bind_acquired_request,
    bind_placement_to_request,
    persist_treatment_binding,
    select_treatment_request,
)
from clipforge.schemas.direction import (
    DirectionAssetPlacement,
    DirectionDocument,
    TreatmentAssetBindingDocument,
)
from clipforge.schemas.editorial import MotionPurpose, OutputInterval
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.treatment import (
    TreatmentAssetObservation,
    TreatmentAssetVerification,
    TreatmentObservationFrame,
)
from tests.test_direction import _aligned_words, _document


def pending_direction() -> DirectionDocument:
    parent = _document()
    option = materialize_treatment(
        parent.options[0].model_copy(update={"preset_id": "clean_explainer"}),
        _aligned_words(),
        PresetCatalog.load().find("clean_explainer"),
    )
    return DirectionDocument.model_validate(
        {
            **parent.model_dump(mode="json"),
            "options": [
                option.model_dump(mode="json"),
                *[item.model_dump(mode="json") for item in parent.options[1:]],
            ],
            "selected_option_id": option.option_id,
            "style_id": option.style_id,
            "preset_id": "clean_explainer",
            "direction_recipe_version": "direction-v3",
            "treatment_fingerprint": treatment_fingerprint(option),
        }
    )


def binding_for_direction(direction: DirectionDocument) -> TreatmentAssetBindingDocument:
    option = next(item for item in direction.options if item.option_id == direction.selected_option_id)
    pending = option.treatment_decisions[0].asset_requests[0]
    checked = TreatmentAssetVerification(
        provider="local",
        provider_response_sha256="a" * 64,
        selection_id="selection-1",
        acquisition_id="acquisition-1",
        license_evidence_sha256="b" * 64,
        registered_asset_id="asset-1",
        registered_asset_sha256="c" * 64,
        media_kind=pending.kind,
    )
    acquired = bind_acquired_request(
        select_treatment_request(pending, provider_response_sha256="a" * 64, selection_id="selection-1"),
        verification=checked,
    )
    placement = bind_placement_to_request(
        DirectionAssetPlacement(
            placement_id="placement-1",
            asset_id="asset-1",
            kind=pending.kind,
            interval=pending.interval,
            source_evidence_ids=pending.source_evidence_ids,
            purpose=MotionPurpose.CONCEPT,
            relevance_note="Reviewed source context",
            asset_tags=["context"],
        ),
        acquired,
    )
    observation = None
    if pending.kind == "graphic":
        now = datetime.now(UTC)
        observation = TreatmentAssetObservation(
            observation_id="observation-1",
            asset_id="asset-1",
            source_asset_id="source-1",
            media_sha256="c" * 64,
            output_interval=placement.interval,
            source_evidence_ids=placement.source_evidence_ids,
            frames=[
                TreatmentObservationFrame(
                    relative_path="editorial/treatment-observations/observation-1/frames/frame-000.jpg",
                    sha256="a" * 64,
                    timestamp_us=0,
                )
            ],
            observed_labels=["context"],
            relevance_score=0.9,
            relevance_threshold=0.85,
            reviewed_by="test",
            review_note="Decoded frame matches the requested context.",
            provenance=ArtifactProvenance(
                created_at=now,
                created_by="test",
                tool="test",
                tool_version="1",
                source_asset_ids=["source-1"],
                parent_artifact_ids=["asset-1"],
            ),
        )
        placement = placement.model_copy(
            update={"observation_id": observation.observation_id, "observation_sha256": "d" * 64}
        )
    now = datetime.now(UTC)
    return TreatmentAssetBindingDocument(
        binding_id="binding-1",
        request=acquired,
        placement=placement,
        verification=checked,
        observation=observation,
        created_at=now,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )


def test_revision_fulfills_pending_request_without_hand_editing_placement() -> None:
    parent = pending_direction()
    before = parent.model_dump_json()
    binding = binding_for_direction(parent)
    revised = apply_treatment_bindings(
        parent,
        [binding],
        parent_direction_sha256="d" * 64,
        binding_paths=[("binding-1", "editorial/treatment-bindings/binding-1.json", "e" * 64)],
    )
    assert parent.model_dump_json() == before
    assert revised.direction_id != parent.direction_id
    assert revised.direction_recipe_version == "direction-v4"
    assert revised.treatment_revision.parent_direction_id == parent.direction_id
    selected = next(item for item in revised.options if item.option_id == revised.selected_option_id)
    assert selected.asset_placements == [binding.placement]
    assert selected.treatment_decisions[0].broll.state == "use"
    assert selected.treatment_decisions[0].asset_requests[0] == binding.request
    assert all(
        item.dependency_fingerprint == treatment_fingerprint(selected) for item in selected.treatment_decisions
    )


@pytest.mark.parametrize("change", ["query_terms", "role", "source_evidence_ids"])
def test_revision_rejects_changed_request_intent(change: str) -> None:
    parent = pending_direction()
    binding = binding_for_direction(parent)
    value = ["unrelated"] if change != "role" else "unrelated"
    forged = binding.model_copy(update={"request": binding.request.model_copy(update={change: value})})
    with pytest.raises(MediaError, match="editorial intent"):
        apply_treatment_bindings(
            parent,
            [forged],
            parent_direction_sha256="d" * 64,
            binding_paths=[("binding-1", "editorial/treatment-bindings/binding-1.json", "e" * 64)],
        )


def test_binding_schema_rejects_mismatched_license_and_interval() -> None:
    binding = binding_for_direction(pending_direction())
    payload = binding.model_dump(mode="json")
    payload["placement"]["license_evidence_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="license_evidence_sha256"):
        TreatmentAssetBindingDocument.model_validate(payload)
    payload = binding.model_dump(mode="json")
    payload["placement"]["interval"]["output_end_us"] += 1
    with pytest.raises(ValidationError, match="escapes"):
        TreatmentAssetBindingDocument.model_validate(payload)


def test_binding_persistence_is_idempotent_and_confined(tmp_path: Path) -> None:
    binding = binding_for_direction(pending_direction())
    observation_path = tmp_path / "editorial" / "treatment-observations" / "observation-1" / "observation.json"
    observation_path.parent.mkdir(parents=True)
    assert binding.observation is not None
    observation_path.write_text(binding.observation.model_dump_json(), encoding="utf-8")
    kwargs = dict(
        work_root=tmp_path,
        request=binding.request,
        placement=binding.placement,
        verification=binding.verification,
        source_asset_id="source-1",
        observation_path=observation_path,
    )
    path = persist_treatment_binding(**kwargs)
    before = path.read_bytes()
    assert persist_treatment_binding(**kwargs) == path
    assert path.read_bytes() == before
    other = tmp_path / "other"
    other.mkdir()
    path.unlink()
    path.symlink_to(other / path.name)
    with pytest.raises(MediaError):
        persist_treatment_binding(**kwargs)


def test_visual_observation_requires_reviewed_numeric_relevance() -> None:
    now = datetime.now(UTC)
    provenance = ArtifactProvenance(
        created_at=now,
        created_by="reviewer",
        tool="test",
        tool_version="1",
        source_asset_ids=["source-1"],
        parent_artifact_ids=["asset-1"],
    )
    frame = TreatmentObservationFrame(
        relative_path="editorial/treatment-observations/observation-1/frames/frame-000.jpg",
        sha256="a" * 64,
        timestamp_us=0,
    )
    observation = TreatmentAssetObservation(
        observation_id="observation-1",
        asset_id="asset-1",
        source_asset_id="source-1",
        media_sha256="b" * 64,
        output_interval=OutputInterval(output_start_us=0, output_end_us=1_000_000),
        source_evidence_ids=["evidence-1"],
        frames=[frame],
        observed_labels=["context"],
        relevance_score=0.9,
        relevance_threshold=0.85,
        reviewed_by="reviewer",
        review_note="Decoded frame matches the source-grounded context.",
        provenance=provenance,
    )
    assert observation.relevance_score >= observation.relevance_threshold
    with pytest.raises(ValidationError, match="below"):
        TreatmentAssetObservation.model_validate(
            {**observation.model_dump(mode="json"), "relevance_score": 0.4}
        )
