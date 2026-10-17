from pathlib import Path
from types import SimpleNamespace

import pytest

from clipforge.policy.engine import PolicyContext, evaluate_policy
from clipforge.schemas.campaign import CampaignOverlaySpec


def _overlay() -> CampaignOverlaySpec:
    return CampaignOverlaySpec(
        cta_asset_id="cta-asset",
        cta_asset_sha256="a" * 64,
        cta_asset_name="tarteel-cta-alpha.mov",
        cta_render_mode="alpha_video_v1",
        cta_start_us=1_000_000,
        cta_end_us=3_000_000,
        watermark_asset_id="watermark-asset",
        watermark_asset_sha256="b" * 64,
        watermark_asset_name="tarteel-watermark-alpha.png",
    )


def _context(plan: object) -> PolicyContext:
    return PolicyContext(
        database=None,  # type: ignore[arg-type]
        project_id="project-1",
        source_asset_id="source-1",
        source_license=None,
        plans=(plan,),  # type: ignore[arg-type]
        work_root=Path("/tmp"),
        workspace=None,
        profile_id="profile-tarteel-campaign",
    )


def test_tarteel_policy_rejects_a_plan_without_branding() -> None:
    plan = SimpleNamespace(
        plan_id="plan-1",
        campaign_overlay=None,
        assets=[],
        windows=[],
        captions=[],
        typography=[],
        sfx=[],
        qa_requirements=["technical"],
    )
    result = evaluate_policy("policy-tarteel-delivery", _context(plan))
    assert result.status.value == "fail"
    assert "CTA and watermark" in result.evidence


def test_tarteel_policy_requires_the_exact_caption_gate_and_no_sfx() -> None:
    overlay = _overlay()
    plan = SimpleNamespace(
        plan_id="plan-1",
        campaign_overlay=overlay,
        assets=[SimpleNamespace(asset_id="cta-asset"), SimpleNamespace(asset_id="watermark-asset")],
        windows=[SimpleNamespace(output_end_us=4_000_000)],
        captions=[],
        typography=[],
        sfx=[SimpleNamespace()],
        qa_requirements=["tarteel-overlay-v1"],
    )
    result = evaluate_policy("policy-tarteel-delivery", _context(plan))
    assert result.status.value == "fail"
    assert "mandatory first-post" in result.evidence
    assert "SFX/music" in result.evidence


def test_tarteel_policy_rejects_a_static_cta_sequence() -> None:
    overlay = CampaignOverlaySpec(
        cta_asset_id="cta-asset",
        cta_asset_sha256="a" * 64,
        cta_asset_name="tarteel-cta-alpha-sequence",
        cta_render_mode="alpha_png_sequence_v1",
        cta_frame_prefix="tarteel-cta-alpha",
        cta_frame_count=1,
        cta_start_us=1_000_000,
        cta_end_us=3_000_000,
        watermark_asset_id="watermark-asset",
        watermark_asset_sha256="b" * 64,
        watermark_asset_name="tarteel-watermark-alpha.png",
    )
    plan = SimpleNamespace(
        plan_id="plan-1",
        campaign_overlay=overlay,
        assets=[SimpleNamespace(asset_id="cta-asset"), SimpleNamespace(asset_id="watermark-asset")],
        windows=[SimpleNamespace(output_end_us=4_000_000)],
        captions=[SimpleNamespace(text=overlay.first_post_caption_line)],
        typography=[],
        sfx=[],
        qa_requirements=["tarteel-overlay-v1"],
    )
    result = evaluate_policy("policy-tarteel-delivery", _context(plan))
    assert result.status.value == "fail"
    assert "animated alpha video" in result.evidence


def test_campaign_overlay_contract_requires_video_filename_for_video_mode() -> None:
    with pytest.raises(ValueError, match="transparent video staging filename"):
        CampaignOverlaySpec(
            cta_asset_id="cta-asset",
            cta_asset_sha256="a" * 64,
            cta_asset_name="cta.png",
            cta_render_mode="alpha_video_v1",
            cta_start_us=1_000_000,
            cta_end_us=3_000_000,
            watermark_asset_id="watermark-asset",
            watermark_asset_sha256="b" * 64,
            watermark_asset_name="watermark.png",
        )
