"""Deterministic campaign overlay staging.

Only campaign-provided, rights-cleared files may reach this module.  The
green-screen CTA and white-background watermark are converted to alpha assets
once in the run staging directory; Remotion then composites those files as
layers instead of drawing opaque rectangles over the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import AssetCatalogEntry, load_catalog, require_asset
from clipforge.media.hashing import sha256_file
from clipforge.media.process import ProcessRunner
from clipforge.media.tools import resolve_ffmpeg
from clipforge.media.workspace import SourceWorkspace, ensure_within
from clipforge.schemas.campaign import CampaignOverlaySpec
from clipforge.storage import Database

TARTEEL_PROFILE_ID = "profile-tarteel-campaign"
TARTEEL_CTA_TAG = "cta"
TARTEEL_WATERMARK_TAG = "watermark"


@dataclass(frozen=True, slots=True)
class StagedTarteelOverlay:
    spec: CampaignOverlaySpec
    cta_source: AssetCatalogEntry
    watermark_source: AssetCatalogEntry
    cta_path: Path
    watermark_path: Path


def stage_tarteel_overlay(
    *,
    database: Database,
    workspace: SourceWorkspace,
    project_id: str,
    work_root: Path,
    staging_dir: Path,
    duration_us: int,
    cta_start_us: int | None = None,
    cta_duration_us: int = 3_600_000,
    cta_asset_id: str | None = None,
    watermark_asset_id: str | None = None,
) -> StagedTarteelOverlay:
    """Stage the reviewed Tarteel CTA and watermark with deterministic alpha."""
    if duration_us <= 0:
        raise MediaError("Tarteel overlay staging requires a positive output duration")
    if cta_duration_us <= 0:
        raise MediaError("Tarteel CTA duration must be positive")
    entries = load_catalog(workspace)
    cta = _choose(entries, TARTEEL_CTA_TAG, preferred="cta-2-green-screen", asset_id=cta_asset_id)
    watermark = _choose(entries, TARTEEL_WATERMARK_TAG, preferred="watermark-1", asset_id=watermark_asset_id)
    cta_entry, _cta_license, cta_source = require_asset(
        database,
        workspace,
        project_id=project_id,
        asset_id=cta.reference.asset_id,
        expected_kind="graphic",
        work_root=work_root,
    )
    watermark_entry, _wm_license, watermark_source = require_asset(
        database,
        workspace,
        project_id=project_id,
        asset_id=watermark.reference.asset_id,
        expected_kind="graphic",
        work_root=work_root,
    )
    staging_dir.mkdir(parents=True, exist_ok=True)
    ensure_within(work_root, staging_dir)
    cta_prefix = staging_dir / "tarteel-cta-alpha"
    watermark_path = staging_dir / "tarteel-watermark-alpha.png"
    # The official CTA is animated, but Chromium's frame extractor is not
    # reliable when a long Remotion render requests dozens of alpha PNGs at
    # once.  A reviewed, fully opaque final CTA frame is held for the declared
    # interval; the source clip hash remains bound in the overlay contract.
    frame_count = 1
    _chroma_key(cta_source, cta_prefix, frame_count, staging_dir / "tarteel-cta-key.log")
    _white_key(watermark_source, watermark_path, staging_dir / "tarteel-watermark-key.log")
    start = cta_start_us if cta_start_us is not None else max(0, duration_us - cta_duration_us - 500_000)
    end = min(duration_us, start + cta_duration_us)
    if end <= start:
        raise MediaError("Tarteel CTA interval does not fit the output")
    return StagedTarteelOverlay(
        spec=CampaignOverlaySpec(
            cta_asset_id=cta_entry.reference.asset_id,
            cta_asset_sha256=cta_entry.file_sha256,
            cta_asset_name="tarteel-cta-alpha-sequence",
            cta_start_us=start,
            cta_end_us=end,
            cta_frame_prefix=cta_prefix.name,
            cta_frame_count=frame_count,
            watermark_asset_id=watermark_entry.reference.asset_id,
            watermark_asset_sha256=watermark_entry.file_sha256,
            watermark_asset_name=watermark_path.name,
        ),
        cta_source=cta_entry,
        watermark_source=watermark_entry,
        cta_path=cta_prefix,
        watermark_path=watermark_path,
    )


def _choose(
    entries: list[AssetCatalogEntry],
    tag: str,
    *,
    preferred: str,
    asset_id: str | None = None,
) -> AssetCatalogEntry:
    candidates = [item for item in entries if tag in item.reference.content_tags]
    if asset_id is not None:
        chosen = next((item for item in candidates if item.reference.asset_id == asset_id), None)
        if chosen is None:
            raise MediaError(f"Tarteel {tag} asset {asset_id} is not in the local catalog")
        return chosen
    if not candidates:
        raise MediaError(f"Tarteel campaign has no catalogued {tag} asset")
    for item in candidates:
        if preferred in item.relative_path:
            return item
    return sorted(candidates, key=lambda item: item.relative_path)[0]


def _chroma_key(source: Path, destination_prefix: Path, frame_count: int, log_path: Path) -> None:
    ffmpeg = resolve_ffmpeg()
    base = destination_prefix.parent / f"{destination_prefix.name}-base.png"
    ProcessRunner().run(
        [
            ffmpeg,
            "-y",
            "-ss",
            "2.5",
            "-i",
            str(source),
            "-t",
            "0.1",
            "-vf",
            "colorkey=0x00b52b:0.12:0.0,format=rgba",
            "-an",
            "-frames:v",
            "1",
            "-c:v",
            "png",
            str(base),
        ],
        log_path=log_path,
        check=True,
    )
    ProcessRunner().run(
        [
            ffmpeg,
            "-y",
            "-loop",
            "1",
            "-i",
            str(base),
            "-frames:v",
            str(frame_count),
            "-c:v",
            "png",
            f"{destination_prefix}-%04d.png",
        ],
        log_path=log_path,
        check=True,
    )
    first = destination_prefix.parent / f"{destination_prefix.name}-0001.png"
    last = destination_prefix.parent / f"{destination_prefix.name}-{frame_count:04d}.png"
    if not first.is_file() or not last.is_file() or first.stat().st_size == 0 or last.stat().st_size == 0:
        raise MediaError("Tarteel CTA alpha staging produced incomplete frames")


def _white_key(source: Path, destination: Path, log_path: Path) -> None:
    ffmpeg = resolve_ffmpeg()
    ProcessRunner().run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(source),
            "-vf",
            "colorkey=0xFFFFFF:0.10:0.08,format=rgba",
            "-frames:v",
            "1",
            "-an",
            "-c:v",
            "png",
            str(destination),
        ],
        log_path=log_path,
        check=True,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise MediaError("Tarteel watermark alpha staging produced no file")


def overlay_dependencies_digest(overlay: StagedTarteelOverlay) -> str:
    """Hash the exact source and alpha bytes consumed by a render input."""
    import hashlib

    digest = hashlib.sha256()
    cta_frames = sorted(
        overlay.cta_path.parent.glob(f"{overlay.cta_path.name}-*.png"),
        key=lambda item: item.name,
    )
    for path in (*cta_frames, overlay.watermark_path):
        digest.update(path.name.encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    import json

    digest.update(
        json.dumps(overlay.spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return digest.hexdigest()
