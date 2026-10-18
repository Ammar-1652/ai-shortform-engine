from clipforge.campaign.overlays import (
    choose_tarteel_foreground_position,
    choose_tarteel_overlay_start_us,
)
from clipforge.schemas.campaign import CampaignOverlaySpec


def test_cta_beat_prefers_a_caption_free_middle_or_latter_slot() -> None:
    start = choose_tarteel_overlay_start_us(
        50_000_000,
        3_000_000,
        [(30_000_000, 50_000_000)],
    )
    assert start == 23_000_000


def test_new_tarteel_overlay_coordinates_are_foreground_relative() -> None:
    overlay = CampaignOverlaySpec(
        cta_asset_id="cta-asset",
        cta_asset_sha256="a" * 64,
        cta_asset_name="tarteel-cta-alpha.webm",
        cta_start_us=1_000_000,
        cta_end_us=3_000_000,
        watermark_asset_id="watermark-asset",
        watermark_asset_sha256="b" * 64,
        watermark_asset_name="tarteel-watermark-alpha.png",
    )
    assert overlay.cta_position == "foreground_attention_v1"
    assert overlay.overlay_coordinate_space == "foreground_v1"
    assert overlay.watermark_position == "foreground_top_right_v1"


def test_cta_position_avoids_the_most_occupied_face_region() -> None:
    left_top = choose_tarteel_foreground_position([(0.02, 0.05, 0.55, 0.35)])
    assert left_top != (60, 180)
