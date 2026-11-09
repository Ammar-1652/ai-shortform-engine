from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from clipforge.campaign.overlays import (
    campaign_cta_bounds,
    overlay_spec_sha256,
    validate_overlay_render_geometry,
    validate_overlay_sample_files,
)
from clipforge.errors import MediaError
from clipforge.media.hashing import sha256_file
from clipforge.schemas.advanced import AdvancedHeroRenderInput, ReframingStrategy, ReframingWindow
from clipforge.schemas.campaign import (
    CampaignOverlaySpec,
    OverlayExclusionEvidence,
    OverlayExclusionRegion,
    OverlayExclusionSample,
)
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.timeline import FrameRate, frame_start_us


def _input() -> AdvancedHeroRenderInput:
    overlay = CampaignOverlaySpec(
        cta_asset_id="cta",
        cta_asset_sha256="a" * 64,
        cta_asset_name="cta.webm",
        cta_left_permille=80,
        cta_top_permille=360,
        cta_width_permille=240,
        cta_start_us=1_000_000,
        cta_end_us=3_000_000,
        watermark_asset_id="logo",
        watermark_asset_sha256="b" * 64,
        watermark_asset_name="logo.png",
    )
    return AdvancedHeroRenderInput(
        candidate_id="candidate-1",
        advanced_set_id="set-1",
        duration_in_frames=120,
        output_duration_us=4_000_000,
        renderer_recipe_version="advanced-hero-renderer-directed-v4",
        reframing_strategy="contain",
        reframing_config_sha256="a" * 64,
        profile_fingerprint="b" * 64,
        alignment_sha256="c" * 64,
        hero_plan_sha256="d" * 64,
        advanced_plan_sha256="e" * 64,
        frame_style_id="tarteel-card-sage-gold-v1",
        frame_backdrop_id="palette-solid-v1",
        frame_layout_id="platform-bleed-v1",
        campaign_overlay=overlay,
        asset_names={"cta": "cta.webm", "logo": "logo.png"},
        windows=[
            ReframingWindow(
                window_id="contain",
                strategy_id=ReframingStrategy(strategy_id="contain"),
                output_start_us=0,
                output_end_us=4_000_000,
                source_x=0,
                source_y=0,
                source_width=1280,
                source_height=720,
                frame_width=1280,
                frame_height=720,
            )
        ],
    )


def _proof(render_input: AdvancedHeroRenderInput) -> OverlayExclusionEvidence:
    overlay = render_input.campaign_overlay
    assert overlay is not None
    left, top, width, height = campaign_cta_bounds(render_input)
    samples = []
    for phase, frame in [("entrance", 30), ("hold", 60), ("exit", 89), ("maximum_extent", 75)]:
        regions = [
            OverlayExclusionRegion(kind=kind, status="absent_reviewed")
            for kind in (
                "face",
                "child_body",
                "tablet",
                "caption",
                "context_line",
                "source_logo",
                "watermark",
                "platform_rail",
            )
        ]
        samples.append(
            OverlayExclusionSample(
                sample_id=f"sample-{phase}",
                phase=phase,
                output_frame_index=frame,
                output_time_us=frame_start_us(frame, FrameRate(30, 1)),
                sample_frame_sha256="f" * 64,
                sample_frame_relative_path="review/sample.png",
                cta_left=left,
                cta_top=top,
                cta_width=width,
                cta_height=height,
                exclusions=regions,
            )
        )
    return OverlayExclusionEvidence(
        evidence_id="proof",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        time_map_sha256="b" * 64,
        transform_sha256="c" * 64,
        overlay_spec_sha256=overlay_spec_sha256(overlay),
        cta_start_us=overlay.cta_start_us,
        cta_end_us=overlay.cta_end_us,
        samples=samples,
        decision="clear",
        reviewer="test",
        reviewed_at=datetime.now(UTC),
        provenance=ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="test",
            tool="test",
            tool_version="1",
            source_asset_ids=["source-1"],
        ),
    )


def test_portrait_cta_geometry_uses_foreground_picture_and_640_by_240_asset() -> None:
    render_input = _input()
    # Subpixel y=874.88 plus height=97.2 owns pixels through ceil(972.08).
    assert campaign_cta_bounds(render_input) == (86, 874, 260, 99)
    validate_overlay_render_geometry(_proof(render_input), render_input)


def test_reviewed_small_rectangle_cannot_authorize_a_large_rendered_cta() -> None:
    render_input = _input()
    proof = _proof(render_input)
    changed = proof.model_copy(
        update={"samples": [s.model_copy(update={"cta_width": 10}) for s in proof.samples]}
    )
    with pytest.raises(MediaError, match="production geometry"):
        validate_overlay_render_geometry(changed, render_input)


def test_enter_and_exit_samples_must_own_the_first_and_last_visible_frames() -> None:
    render_input = _input()
    proof = _proof(render_input)
    changed = proof.model_copy(
        update={
            "samples": [
                s.model_copy(update={"output_frame_index": 31}) if s.phase == "entrance" else s
                for s in proof.samples
            ]
        }
    )
    with pytest.raises(MediaError, match="first CTA frame"):
        validate_overlay_render_geometry(changed, render_input)


def test_each_child_face_is_a_separate_exclusion_and_each_collision_fails() -> None:
    proof = _proof(_input())
    sample = proof.samples[0]
    regions = [region for region in sample.exclusions if region.kind != "face"]
    regions.extend(
        [
            OverlayExclusionRegion(
                kind="face", status="present", annotation_id="child-1", left=10, top=20, width=50, height=50
            ),
            OverlayExclusionRegion(
                kind="face", status="present", annotation_id="child-2", left=400, top=800, width=80, height=80
            ),
        ]
    )
    updated = OverlayExclusionSample.model_validate({**sample.model_dump(), "exclusions": regions})
    assert len(updated.exclusions) == 9
    colliding = regions[-1].model_copy(update={"left": sample.cta_left, "top": sample.cta_top})
    with pytest.raises(ValueError, match="intersects face"):
        OverlayExclusionEvidence.model_validate(
            {
                **proof.model_dump(),
                "samples": [
                    {**sample.model_dump(), "exclusions": [*regions[:-1], colliding]},
                    *proof.samples[1:],
                ],
            }
        )


def test_overlay_proof_requires_decodable_hashed_frames_and_matching_clock(tmp_path: Path) -> None:
    proof = _proof(_input())
    path = tmp_path / "review/sample.png"
    path.parent.mkdir()
    cv2.imwrite(str(path), np.zeros((1920, 1080, 3), dtype=np.uint8))
    proof = proof.model_copy(
        update={
            "samples": [s.model_copy(update={"sample_frame_sha256": sha256_file(path)}) for s in proof.samples]
        }
    )
    validate_overlay_sample_files(tmp_path, proof)
    bad_clock = proof.model_copy(
        update={
            "samples": [proof.samples[0].model_copy(update={"output_time_us": 1_000_001}), *proof.samples[1:]]
        }
    )
    with pytest.raises(MediaError, match="clock"):
        validate_overlay_sample_files(tmp_path, bad_clock)
    path.write_bytes(b"changed")
    with pytest.raises(MediaError, match="hash"):
        validate_overlay_sample_files(tmp_path, proof)
