"""Optional Openverse discovery provider with conservative rights handling."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

from clipforge.assets.local import register_local_asset
from clipforge.campaign.policy_fingerprint import campaign_blocks_outside_media, current_policy_fingerprint
from clipforge.editorial.knowledge import canonical_digest
from clipforge.errors import ClipforgeError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.media.hashing import sha256_file
from clipforge.media.probe import read_ffprobe_json
from clipforge.media.process import ProcessRunner
from clipforge.media.workspace import atomic_replace, ensure_within, mkdir_contained, reject_symlink_chain
from clipforge.paths import resolve_work_dir
from clipforge.schemas.openverse import (
    OpenverseAcquisitionManifest,
    OpenverseLicenseEvidence,
    OpenverseMediaRecord,
    OpenverseSearchRequest,
    OpenverseSearchResponse,
    OpenverseSelection,
)
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.storage import Database


class OpenverseError(ClipforgeError):
    """Openverse is unavailable or returned unsafe/malformed data."""


def openverse_live() -> bool:
    return os.environ.get("CLIPFORGE_OPENVERSE_LIVE", "").strip() == "1"


def openverse_base_url() -> str:
    return os.environ.get("CLIPFORGE_OPENVERSE_API_BASE", "https://api.openverse.org/v1").rstrip("/")


class OpenverseProvider:
    """Bounded HTTP discovery. It never downloads media bytes."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        fetch_json: Callable[[str, dict[str, str]], dict[str, Any]] | None = None,
    ) -> None:
        self.base_url = (base_url or openverse_base_url()).rstrip("/")
        self._fetch_json = fetch_json or _fetch_json

    def doctor(self) -> str:
        return "\n".join(
            [
                f"endpoint: {self.base_url}",
                f"enabled: {1 if openverse_live() else 0}",
                "connection: not_run" if not openverse_live() else "connection: opt_in",
                "media_download: separate rights-bound acquisition",
                "scraping: prohibited",
            ]
        )

    def search(self, request: OpenverseSearchRequest) -> OpenverseSearchResponse:
        if not openverse_live():
            raise OpenverseError(
                "Openverse live discovery is disabled; set CLIPFORGE_OPENVERSE_LIVE=1 for an explicit smoke."
            )
        endpoint = f"{self.base_url}/{request.media_type}s/"
        query: dict[str, str] = {
            "q": request.query,
            "page": str(request.page),
            "page_size": str(request.page_size),
        }
        if request.license_filter:
            query["license"] = ",".join(request.license_filter)
        if request.category:
            query["category"] = request.category
        if request.length:
            query["length"] = request.length
        payload = self._fetch_json(endpoint, query)
        return normalize_response(request, payload)


class FakeOpenverseProvider(OpenverseProvider):
    """Deterministic provider for tests and offline planning."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        super().__init__(fetch_json=self._fake_fetch)

    def _fake_fetch(self, _endpoint: str, _query: dict[str, str]) -> dict[str, Any]:
        return {"result_count": len(self.rows), "page_count": 1, "page": 1, "results": self.rows}

    def search_offline(self, request: OpenverseSearchRequest) -> OpenverseSearchResponse:
        payload = self._fake_fetch("", {})
        return normalize_response(request, payload)


def normalize_response(request: OpenverseSearchRequest, payload: dict[str, Any]) -> OpenverseSearchResponse:
    results = payload.get("results")
    if not isinstance(results, list):
        raise OpenverseError("Openverse response is missing a results list")
    response_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    normalized: list[OpenverseMediaRecord] = []
    for row in results[: request.page_size]:
        if not isinstance(row, dict):
            raise OpenverseError("Openverse result is not an object")
        normalized.append(_normalize_record(row, request.media_type, response_hash))
    try:
        return OpenverseSearchResponse(
            request=request,
            result_count=_nonnegative_int(payload.get("result_count"), "result_count"),
            page_count=_nonnegative_int(payload.get("page_count"), "page_count"),
            page=_positive_int(payload.get("page"), "page"),
            results=normalized,
            response_sha256=response_hash,
            warnings=[item for item in payload.get("warnings", []) if isinstance(item, str)][:16],
        )
    except ValueError as exc:
        raise OpenverseError(f"Openverse response failed validation: {exc}") from exc


def _normalize_record(
    row: dict[str, Any],
    media_type: Literal["image", "audio"],
    response_hash: str,
) -> OpenverseMediaRecord:
    media_id = _text(row.get("id"), "id")
    title = _text(row.get("title"), "title")
    landing = _https(row.get("foreign_landing_url") or row.get("detail_url"), "landing_url")
    if not media_id or not title or not landing:
        raise OpenverseError("Openverse result requires id, title, and landing URL")
    duration = row.get("duration")
    duration_us = int(duration) * 1000 if isinstance(duration, (int, float)) and duration >= 0 else None
    tags = row.get("tags")
    normalized_tags: list[str] = []
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, str) and item.strip():
                normalized_tags.append(item.strip())
            elif isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
                normalized_tags.append(item["name"].strip())
    try:
        return OpenverseMediaRecord(
            media_id=media_id,
            media_type=media_type,
            title=title,
            creator=_text(row.get("creator"), "creator"),
            creator_url=_https(row.get("creator_url"), "creator_url"),
            source_name=_text(row.get("source"), "source"),
            landing_url=landing,
            direct_download_url=_https(row.get("url"), "direct_download_url"),
            license_code=_text(row.get("license"), "license"),
            license_version=_text(row.get("license_version"), "license_version"),
            license_url=_https(row.get("license_url"), "license_url"),
            attribution=_text(row.get("attribution"), "attribution"),
            duration_us=duration_us,
            width=_positive_optional(row.get("width")),
            height=_positive_optional(row.get("height")),
            file_type=_text(row.get("filetype"), "filetype"),
            tags=normalized_tags[:64],
            source_response_sha256=response_hash,
            discovered_at=datetime.now(UTC),
        )
    except ValueError as exc:
        raise OpenverseError(f"Openverse media record failed validation: {exc}") from exc


def evaluate_license(record: OpenverseMediaRecord) -> tuple[str, str]:
    """Return policy state; Openverse metadata is never final proof."""
    code = (record.license_code or "").casefold()
    if code in {"cc0", "pdm", "publicdomain", "public-domain"}:
        if record.license_url and record.landing_url:
            return "eligible_pending_verification", "public-domain claim requires landing-page verification"
        return "blocked", "missing landing or license URL"
    if code in {"by", "cc-by"}:
        if record.license_url and record.landing_url and record.attribution:
            return "eligible_pending_verification", "CC-BY attribution requires independent verification"
        return "blocked", "CC-BY result lacks license URL, landing URL, or attribution"
    if "nc" in code:
        return "blocked", "non-commercial license is blocked for campaign output"
    if "nd" in code:
        return "blocked", "no-derivatives license is blocked for transformed media"
    if "sa" in code:
        return "blocked", "share-alike license requires explicit campaign policy review"
    return "blocked", "unknown or missing license metadata"


def load_search_response(path: Path) -> OpenverseSearchResponse:
    if path.is_symlink() or not path.is_file():
        raise OpenverseError("Openverse response must be a regular JSON file")
    try:
        return OpenverseSearchResponse.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OpenverseError(f"Openverse response is invalid: {path}") from exc


def select_media(
    response: OpenverseSearchResponse,
    *,
    media_id: str,
    policy_fingerprint: str,
    license_evidence: OpenverseLicenseEvidence | None = None,
    campaign_id: str | None = None,
    intended_role: Literal["image", "sfx", "ambience"] | None = None,
) -> OpenverseSelection:
    matches = [item for item in response.results if item.media_id == media_id]
    if not matches:
        raise OpenverseError(f"Openverse media id is not present in the response: {media_id}")
    media = matches[0]
    policy_state, reason = evaluate_license(media)
    status: Literal["pending", "allowed", "blocked"] = "pending"
    if policy_state == "blocked":
        status = "blocked"
    elif license_evidence is not None:
        if (
            license_evidence.media_id != media.media_id
            or license_evidence.captured_response_sha256 != response.response_sha256
            or license_evidence.landing_url != media.landing_url
            or license_evidence.license_url != media.license_url
            or license_evidence.license_code != media.license_code
            or license_evidence.verification_status != "verified"
        ):
            raise OpenverseError("license evidence does not match the selected Openverse response")
        status = "allowed"
        reason = "independent license evidence supplied; verify campaign policy before acquisition"
    return OpenverseSelection(
        selection_id=f"openverse-{media.media_id}-{response.response_sha256[:12]}",
        media=media,
        selected_for=media.media_type,
        policy_status=status,
        policy_reason=reason,
        license_evidence=license_evidence,
        policy_fingerprint=policy_fingerprint,
        campaign_id=campaign_id,
        intended_role=intended_role,
        created_at=datetime.now(UTC),
    )


def write_selection(selection: OpenverseSelection, *, work_root: Path | None = None) -> Path:
    root = resolve_work_dir(work_root).resolve()
    directory = root / "assets" / "openverse" / "selections"
    ensure_within(root, directory)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise OpenverseError("Openverse selection directory cannot be a symlink")
    final = directory / f"{selection.selection_id}.json"
    if final.exists():
        raise OpenverseError("Openverse selection ids are immutable; use a new response or id")
    temporary = final.with_name(f".{final.name}.partial")
    temporary.write_text(
        json.dumps(selection.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    atomic_replace(temporary, final, root)
    return final


def acquire_selection(
    selection: OpenverseSelection,
    *,
    database: Database,
    project_id: str,
    source_asset_id: str,
    work_root: Path | None = None,
    fetch_bytes: Callable[[str, int], bytes] | None = None,
    max_bytes: int = 64 * 1024 * 1024,
) -> OpenverseAcquisitionManifest:
    """Probe/decode then register cleared bytes through the existing asset boundary."""
    selection = OpenverseSelection.model_validate(selection.model_dump(mode="json"))
    if selection.policy_status != "allowed" or selection.license_evidence is None:
        raise OpenverseError("Openverse selection is not independently rights-verified")
    evidence = selection.license_evidence
    if (
        evaluate_license(selection.media)[0] == "blocked"
        or evidence.verification_status != "verified"
        or evidence.media_id != selection.media.media_id
        or evidence.captured_response_sha256 != selection.media.source_response_sha256
        or evidence.license_code != selection.media.license_code
        or evidence.license_url != selection.media.license_url
        or evidence.landing_url != selection.media.landing_url
    ):
        raise OpenverseError("Openverse rights evidence is stale or conflicting")
    campaign_id = selection.campaign_id
    if not campaign_id or current_policy_fingerprint(campaign_id) != selection.policy_fingerprint:
        raise OpenverseError("Openverse selection requires a current campaign policy binding")
    if campaign_blocks_outside_media(campaign_id):
        raise OpenverseError("campaign policy prohibits outside media")
    if (
        selection.intended_role is None
        or (selection.media.media_type == "audio" and selection.intended_role not in {"sfx", "ambience"})
        or (selection.media.media_type == "image" and selection.intended_role != "image")
    ):
        raise OpenverseError("Openverse acquisition requires an explicit image, SFX, or ambience role")
    direct = selection.media.direct_download_url
    if not direct:
        raise OpenverseError("Openverse selection has no direct media URL")
    if max_bytes <= 0:
        raise OpenverseError("Openverse acquisition byte cap must be positive")
    root = resolve_work_dir(work_root).absolute()
    reject_symlink_chain(root)
    if not evidence.captured_evidence_path or not evidence.captured_evidence_sha256:
        raise OpenverseError("Openverse acquisition requires hashed independent license capture")
    capture = confine_work_path(root, evidence.captured_evidence_path, label="license capture")
    if (
        not capture.is_file()
        or capture.stat().st_size == 0
        or sha256_file(capture) != evidence.captured_evidence_sha256
    ):
        raise OpenverseError("Openverse independent license capture changed or is missing")
    identity = canonical_digest(
        {"selection": selection.model_dump(mode="json"), "project": project_id, "source": source_asset_id}
    )
    acquisition_id = f"acquisition-{identity[:32]}"
    directory = confine_work_path(root, f"assets/openverse/acquisitions/{acquisition_id}", label="acquisition")
    manifest_path = directory / "manifest.json"
    if directory.exists():
        cached = load_acquisition(manifest_path, work_root=root)
        if (
            cached.selection_sha256 != canonical_digest(selection)
            or cached.project_id != project_id
            or cached.source_asset_id != source_asset_id
        ):
            raise OpenverseError("Openverse acquisition cache bindings changed")
        _require_registered_acquisition(cached, database=database, root=root)
        return cached
    staging = directory.with_name(f".partial-{uuid4().hex}")
    mkdir_contained(root, staging)
    promoted = False
    try:
        payload = (fetch_bytes or _fetch_bytes)(direct, max_bytes)
        if not payload or len(payload) > max_bytes:
            raise OpenverseError("Openverse media is empty or exceeded the byte cap")
        media_path = staging / "media"
        media_path.write_bytes(payload)
        _validate_acquired_media(media_path, selection.selected_for)
        if sha256_file(capture) != evidence.captured_evidence_sha256:
            raise OpenverseError("Openverse license capture changed during acquisition")
        (staging / "license-capture").write_bytes(capture.read_bytes())
        (staging / "selection.json").write_text(selection.model_dump_json(indent=2), encoding="utf-8")
        (staging / "license-evidence.json").write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
        os.rename(staging, directory)
        promoted = True
        registration = register_local_asset(
            database=database,
            work_root=root,
            project_id=project_id,
            source_asset_id=source_asset_id,
            relative_file=(directory / "media").relative_to(root).as_posix(),
            license_relative=(directory / "license-evidence.json").relative_to(root).as_posix(),
            kind="audio" if selection.selected_for == "audio" else "graphic",
            confirm_rights=True,
            rights_status="licensed",
            content_tags=sorted({selection.intended_role, *selection.media.tags}),
        )
        manifest = OpenverseAcquisitionManifest(
            acquisition_id=acquisition_id,
            project_id=project_id,
            source_asset_id=source_asset_id,
            campaign_id=campaign_id,
            selection_id=selection.selection_id,
            media_id=selection.media.media_id,
            media_type=selection.selected_for,
            relative_path=f"assets/openverse/acquisitions/{acquisition_id}/media",
            file_sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            landing_url=selection.media.landing_url,
            license_url=selection.license_evidence.license_url,
            attribution=selection.license_evidence.attribution or selection.media.attribution,
            policy_fingerprint=selection.policy_fingerprint,
            selection_response_sha256=selection.media.source_response_sha256,
            selection_sha256=canonical_digest(selection),
            evidence_sha256=sha256_file(directory / "license-evidence.json"),
            asset_id=registration.asset_id,
            license_record_id=registration.license_record_id,
            manifest_sha256="0" * 64,
            provenance=ArtifactProvenance(
                created_at=datetime.now(UTC),
                created_by="codex_operator",
                tool="clipforge-openverse-acquisition",
                tool_version="1",
                source_asset_ids=[source_asset_id],
                inputs_sha256=identity,
            ),
            acquired_at=datetime.now(UTC),
        )
        manifest = manifest.model_copy(
            update={"manifest_sha256": canonical_digest(manifest, exclude="manifest_sha256")}
        )
        manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        return load_acquisition(manifest_path, work_root=root)
    except Exception:
        # No previous acquisition is replaced. A failed registration cannot be
        # mistaken for an acquired usable file on retry.
        if promoted and not manifest_path.exists():
            shutil.rmtree(directory)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def load_acquisition(path: Path, *, work_root: Path | None = None) -> OpenverseAcquisitionManifest:
    root = resolve_work_dir(work_root).resolve()
    path = confine_work_path(root, path.absolute().relative_to(root).as_posix(), label="acquisition manifest")
    if path.is_symlink() or not path.is_file():
        raise OpenverseError("Openverse acquisition manifest must be a regular file")
    try:
        manifest = OpenverseAcquisitionManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise OpenverseError(f"Openverse acquisition manifest is invalid: {path}") from exc
    media = root / manifest.relative_path
    media = confine_work_path(root, manifest.relative_path, label="acquired media")
    if media.is_symlink() or not media.is_file():
        raise OpenverseError("Openverse acquired media is missing or unsafe")
    if (
        media.stat().st_size != manifest.size_bytes
        or hashlib.sha256(media.read_bytes()).hexdigest() != manifest.file_sha256
    ):
        raise OpenverseError("Openverse acquired media hash changed")
    if canonical_digest(manifest, exclude="manifest_sha256") != manifest.manifest_sha256:
        raise OpenverseError("Openverse acquisition manifest hash changed")
    selection = OpenverseSelection.model_validate_json(
        (path.parent / "selection.json").read_text(encoding="utf-8")
    )
    if canonical_digest(selection) != manifest.selection_sha256:
        raise OpenverseError("Openverse acquisition selection changed")
    if current_policy_fingerprint(manifest.campaign_id) != manifest.policy_fingerprint:
        raise OpenverseError("Openverse acquisition policy is stale")
    evidence_path = confine_work_path(
        root, (path.parent / "license-evidence.json").relative_to(root).as_posix(), label="acquired license"
    )
    if sha256_file(evidence_path) != manifest.evidence_sha256:
        raise OpenverseError("Openverse acquisition license evidence changed")
    evidence = selection.license_evidence
    if evidence is None or sha256_file(path.parent / "license-capture") != evidence.captured_evidence_sha256:
        raise OpenverseError("Openverse acquisition license capture changed")
    original_capture = confine_work_path(root, evidence.captured_evidence_path or "", label="license capture")
    if sha256_file(original_capture) != evidence.captured_evidence_sha256:
        raise OpenverseError("Openverse acquisition independent rights evidence is stale")
    return manifest


def _require_registered_acquisition(
    manifest: OpenverseAcquisitionManifest, *, database: Database, root: Path
) -> None:
    from clipforge.hero.advanced_assets import require_asset
    from clipforge.media.workspace import SourceWorkspace

    _entry, _rights, media = require_asset(
        database,
        SourceWorkspace(root, manifest.project_id, manifest.source_asset_id),
        project_id=manifest.project_id,
        asset_id=manifest.asset_id,
        expected_kind="audio" if manifest.media_type == "audio" else "graphic",
        work_root=root,
    )
    if sha256_file(media) != manifest.file_sha256:
        raise OpenverseError("registered Openverse media changed")


def _fetch_json(endpoint: str, query: dict[str, str]) -> dict[str, Any]:
    url = f"{endpoint}?{urlencode(query)}"
    user_agent = os.environ.get("CLIPFORGE_OPENVERSE_USER_AGENT", "clipforge/0.1")
    request = Request(
        url,
        headers={"Accept": "application/json", "User-Agent": user_agent},
        method="GET",
    )
    try:
        timeout_s = float(os.environ.get("CLIPFORGE_OPENVERSE_TIMEOUT_SECONDS", "10"))
        with urlopen(request, timeout=timeout_s) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise OpenverseError(f"Openverse request failed: {type(exc).__name__}") from exc
    if len(raw) > 8 * 1024 * 1024:
        raise OpenverseError("Openverse response exceeded the bounded response size")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise OpenverseError("Openverse response was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise OpenverseError("Openverse response must be a JSON object")
    return payload


def _fetch_bytes(url: str, max_bytes: int) -> bytes:
    if not url.startswith("https://"):
        raise OpenverseError("Openverse media URL must be HTTPS")
    timeout_s = float(os.environ.get("CLIPFORGE_OPENVERSE_TIMEOUT_SECONDS", "10"))
    request = Request(
        url, headers={"User-Agent": os.environ.get("CLIPFORGE_OPENVERSE_USER_AGENT", "clipforge/0.1")}
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            data = response.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise OpenverseError(f"Openverse media request failed: {type(exc).__name__}") from exc
    if len(data) > max_bytes:
        raise OpenverseError("Openverse media response exceeded the bounded byte size")
    return cast(bytes, data)


def _validate_acquired_media(path: Path, media_type: Literal["image", "audio"]) -> None:
    try:
        payload = read_ffprobe_json(path, ProcessRunner(), log_path=None)
    except (ClipforgeError, OSError) as exc:
        raise OpenverseError(f"acquired Openverse bytes failed media probing: {exc}") from exc
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise OpenverseError("acquired Openverse media has no stream list")
    expected = "audio" if media_type == "audio" else "video"
    if not any(isinstance(item, dict) and item.get("codec_type") == expected for item in streams):
        raise OpenverseError(f"acquired Openverse media has no {expected} stream")
    if any(isinstance(item, dict) and item.get("codec_type") != expected for item in streams):
        raise OpenverseError("acquired Openverse media contains an unexpected stream type")


def _text(value: object, _label: str) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _https(value: object, label: str) -> str | None:
    text = _text(value, label)
    if text is None:
        return None
    if not text.startswith("https://") or "@" in text or "#" in text:
        return None
    return text


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenverseError(f"Openverse {label} must be a non-negative integer")
    return value


def _positive_int(value: object, label: str) -> int:
    parsed = _nonnegative_int(value, label)
    if parsed < 1:
        raise OpenverseError(f"Openverse {label} must be positive")
    return parsed


def _positive_optional(value: object) -> int | None:
    if value is None:
        return None
    return _positive_int(value, "dimension")
