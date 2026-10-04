"""Local parsers for platform export files. Nothing here contacts a network."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from clipforge.analytics.service import AnalyticsError
from clipforge.paths import find_repo_root
from clipforge.schemas.analytics import (
    AnalyticsImportProfile,
    AnalyticsObservationInput,
    PerformanceMetrics,
)

_NATIVE = "clipforge-observation-v1"
_FORMULA = ("=", "+", "@")
_REQUIRED = (
    "project_id",
    "source_asset_id",
    "artifact_id",
    "artifact_kind",
    "artifact_sha256",
    "platform",
    "observed_at",
)
_INTS = (
    "views",
    "unique_viewers",
    "completion_count",
    "likes",
    "comments",
    "shares",
    "saves",
    "follows",
    "clicks",
    "paid_views",
)


def profiles_dir() -> Path:
    return find_repo_root() / "configs" / "analytics-imports"


def list_import_profiles() -> list[AnalyticsImportProfile]:
    root = profiles_dir()
    if not root.is_dir() or root.is_symlink():
        raise AnalyticsError("import profile directory is unavailable")
    found: dict[str, AnalyticsImportProfile] = {}
    for path in sorted(root.iterdir()):
        if path.name.startswith("."):
            continue
        if path.suffix != ".json" or path.is_symlink() or not path.is_file():
            raise AnalyticsError("import profile file is not a regular JSON file")
        if ".." in path.parts:
            raise AnalyticsError("import profile path is not allowed")
        profile = _read_profile(path)
        if profile.profile_id in found:
            raise AnalyticsError("duplicate import profile id")
        found[profile.profile_id] = profile
    return [found[key] for key in sorted(found)]


def load_import_profile(profile_id: str) -> AnalyticsImportProfile:
    matches = [item for item in list_import_profiles() if item.profile_id == profile_id]
    if not matches:
        raise AnalyticsError(f"unknown import profile {profile_id}")
    return matches[0]


def documents_for_profile(
    profile: AnalyticsImportProfile,
    raw: bytes,
    suffix: str,
) -> list[AnalyticsObservationInput]:
    """Parse one local file into observation documents. This does not write."""
    if profile.kind == "native":
        from clipforge.analytics.service import _parse_file

        return _parse_file(raw)
    if suffix not in profile.formats:
        raise AnalyticsError("file format is not accepted by this import profile")
    return _tabular(profile, raw, suffix)


def _read_profile(path: Path) -> AnalyticsImportProfile:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        profile = AnalyticsImportProfile.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise AnalyticsError("import profile file was rejected") from exc
    if profile.kind == "tabular":
        aliases: dict[str, str] = {}
        for canonical, names in profile.columns.items():
            if not names:
                raise AnalyticsError("import profile column list is empty")
            for name in names:
                if name in aliases:
                    raise AnalyticsError("import profile repeats a column alias")
                aliases[name] = canonical
        missing = [name for name in _REQUIRED if name not in profile.columns]
        if missing:
            raise AnalyticsError("import profile is missing a required column")
    return profile


def _tabular(profile: AnalyticsImportProfile, raw: bytes, suffix: str) -> list[AnalyticsObservationInput]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise AnalyticsError("import file is not utf-8") from exc
    if "\x00" in text:
        raise AnalyticsError("import file contains a control character")
    rows = _rows(text, suffix)
    if not rows:
        raise AnalyticsError("import file has no observations")
    alias = _alias_map(profile)
    documents: list[AnalyticsObservationInput] = []
    for index, row in enumerate(rows, start=1):
        try:
            documents.append(_one_row(profile, alias, row, index))
        except AnalyticsError:
            raise
        except (ValidationError, ValueError) as exc:
            raise AnalyticsError(f"row {index} failed validation") from exc
    return documents


def _rows(text: str, suffix: str) -> list[dict[str, str]]:
    stripped = text.strip()
    if not stripped:
        raise AnalyticsError("import file is empty")
    if suffix == "csv":
        return _csv_rows(text)
    try:
        if suffix == "jsonl":
            payload = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                payload = [payload]
    except json.JSONDecodeError as exc:
        raise AnalyticsError("import file is not valid JSON") from exc
    if not isinstance(payload, list):
        raise AnalyticsError("import JSON must be a list of rows")
    rows: list[dict[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise AnalyticsError("import row must be an object")
        rows.append({str(key): _cell(value) for key, value in item.items()})
    return rows


def _csv_rows(text: str) -> list[dict[str, str]]:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise AnalyticsError("import file is empty") from exc
    if not header or any(not name.strip() or name != name.strip() for name in header):
        raise AnalyticsError("import header is blank")
    if len(header) != len(set(header)):
        raise AnalyticsError("duplicate columns are rejected")
    rows: list[dict[str, str]] = []
    for raw in reader:
        if not any(cell.strip() for cell in raw):
            continue
        if len(raw) != len(header):
            raise AnalyticsError("import row does not match the header")
        rows.append(dict(zip(header, raw, strict=True)))
    return rows


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        raise AnalyticsError("metric booleans are rejected")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        raise AnalyticsError("metrics must be integers or decimal strings")
    if isinstance(value, str):
        return value
    raise AnalyticsError("metric value is not a string or integer")


def _alias_map(profile: AnalyticsImportProfile) -> dict[str, str]:
    found: dict[str, str] = {}
    for canonical, names in profile.columns.items():
        for name in names:
            found[name] = canonical
    return found


def _one_row(
    profile: AnalyticsImportProfile,
    alias: dict[str, str],
    row: dict[str, str],
    index: int,
) -> AnalyticsObservationInput:
    canonical: dict[str, str] = {}
    for key, value in row.items():
        target = alias.get(key)
        if target is None:
            if profile.unknown_columns == "ignore":
                continue
            raise AnalyticsError(f"row {index} has an unknown column")
        if target in canonical:
            raise AnalyticsError(f"row {index} repeats a column")
        canonical[target] = value.strip()
    for name in _REQUIRED:
        if not canonical.get(name):
            raise AnalyticsError(f"row {index} is missing {name}")
    metrics = _metrics(canonical, index)
    observed = _timestamp(canonical["observed_at"], index, "observed_at")
    published = None
    if canonical.get("published_at"):
        published = _timestamp(canonical["published_at"], index, "published_at")
    identity = _identity(profile.profile_id, canonical, metrics, observed, published)
    outcome_id = canonical.get("outcome_id") or identity[:32]
    idempotency_key = canonical.get("idempotency_key") or identity
    if bool(canonical.get("outcome_id")) != bool(canonical.get("idempotency_key")):
        raise AnalyticsError(f"row {index} must set both outcome id and idempotency key, or neither")
    window = canonical.get("measurement_window") or "unspecified"
    created_by = canonical.get("created_by") or "local-import"
    payload: dict[str, object] = {
        "outcome_id": outcome_id,
        "idempotency_key": idempotency_key,
        "project_id": canonical["project_id"],
        "source_asset_id": canonical["source_asset_id"],
        "artifact_id": canonical["artifact_id"],
        "artifact_kind": canonical["artifact_kind"],
        "artifact_sha256": canonical["artifact_sha256"],
        "platform": canonical["platform"],
        "observed_at": observed.isoformat(),
        "measurement_window": window,
        "metrics": metrics.model_dump(mode="json"),
        "created_by": created_by,
    }
    if canonical.get("platform_post_id"):
        payload["platform_post_id"] = canonical["platform_post_id"]
    if canonical.get("campaign_id"):
        payload["campaign_id"] = canonical["campaign_id"]
    if canonical.get("geography"):
        payload["geography"] = canonical["geography"]
    if published is not None:
        payload["published_at"] = published.isoformat()
    try:
        return AnalyticsObservationInput.model_validate(payload)
    except ValidationError as exc:
        raise AnalyticsError(f"row {index} failed validation: {_short(exc)}") from exc


def _metrics(canonical: dict[str, str], index: int) -> PerformanceMetrics:
    values: dict[str, object] = {}
    for name in _INTS:
        text = canonical.get(name, "")
        if text == "":
            continue
        _reject_formula(text, index)
        if not re.fullmatch(r"[0-9]+", text):
            raise AnalyticsError(f"row {index} has a negative or invalid {name}")
        values[name] = int(text)
    for name, target in (
        ("total_watch_time_seconds", "total_watch_time_us"),
        ("average_watch_time_seconds", "average_watch_time_us"),
    ):
        text = canonical.get(name, "")
        if text == "":
            continue
        values[target] = _microseconds(text, index, name)
    rate = canonical.get("completion_rate", "")
    if rate != "":
        _reject_formula(rate, index)
        values["completion_rate"] = rate
    amount = canonical.get("revenue_amount", "")
    currency = canonical.get("revenue_currency", "")
    if amount == "" and currency == "":
        pass
    elif currency not in {"", "USD"} or (amount != "" and currency != "USD"):
        raise AnalyticsError(f"row {index} uses an unsupported currency")
    elif amount == "" or currency == "":
        raise AnalyticsError(f"row {index} revenue amount and currency must both be set")
    else:
        _reject_formula(amount, index)
        values["revenue_amount"] = amount
        values["revenue_currency"] = "USD"
    try:
        return PerformanceMetrics.model_validate(values)
    except ValidationError as exc:
        raise AnalyticsError(f"row {index} failed validation: {_short(exc)}") from exc


def _microseconds(text: str, index: int, label: str) -> int:
    _reject_formula(text, index)
    try:
        seconds = Decimal(text)
    except Exception as exc:
        raise AnalyticsError(f"row {index} has an invalid {label}") from exc
    if seconds < 0:
        raise AnalyticsError(f"row {index} has a negative {label}")
    micros = seconds * Decimal(1_000_000)
    if micros != micros.to_integral_value():
        raise AnalyticsError(f"row {index} watch time must convert to whole microseconds")
    return int(micros)


def _timestamp(value: str, index: int, label: str) -> datetime:
    _reject_formula(value, index)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AnalyticsError(f"row {index} has a malformed {label}") from exc
    if parsed.tzinfo is None:
        raise AnalyticsError(f"row {index} {label} must include a timezone")
    return parsed


def _identity(
    profile_id: str,
    canonical: dict[str, str],
    metrics: PerformanceMetrics,
    observed: datetime,
    published: datetime | None,
) -> str:
    import hashlib

    body = {
        "profile_id": profile_id,
        "project_id": canonical["project_id"],
        "source_asset_id": canonical["source_asset_id"],
        "artifact_id": canonical["artifact_id"],
        "platform": canonical["platform"],
        "platform_post_id": canonical.get("platform_post_id") or None,
        "observed_at": observed.isoformat(),
        "published_at": None if published is None else published.isoformat(),
        "measurement_window": canonical.get("measurement_window") or "unspecified",
        "geography": canonical.get("geography") or None,
        "campaign_id": canonical.get("campaign_id") or None,
        "metrics": metrics.model_dump(mode="json"),
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _reject_formula(text: str, index: int) -> None:
    if text.startswith(_FORMULA):
        raise AnalyticsError(f"row {index} contains a spreadsheet formula")


def _short(exc: ValidationError) -> str:
    messages: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        messages.append(f"{location}: {error['msg']}")
    text = "; ".join(messages)[:300]
    if any(token in text for token in ("/tmp/", "/home/", "\\")):
        return "import row failed validation"
    return text or "import row failed validation"


def native_profile_id() -> str:
    return _NATIVE
