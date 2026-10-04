"""Copy editorial facts that are already on an artifact. Do not invent labels."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import ValidationError

from clipforge.schemas.time import TimeMapDocument

_SHA = 64


@dataclass(frozen=True, slots=True)
class ExtractedFeatures:
    """Null fields were not present. They are not zeroes."""

    duration_us: int | None = None
    candidate_rank: int | None = None
    creative_score: str | None = None
    edit_opportunity_score: str | None = None
    transcript_word_count: int | None = None
    caption_count: int | None = None
    caption_style: str | None = None
    caption_algorithm_version: str | None = None
    alignment_quality: str | None = None
    profile_id: str | None = None
    profile_sha256: str | None = None
    policy_ids: tuple[str, ...] = ()
    motion_library_version: str | None = None
    renderer_recipe: str | None = None
    reframing_strategy: str | None = None
    broll_count: int | None = None
    broll_duration_us: int | None = None
    sfx_count: int | None = None
    sfx_duration_us: int | None = None
    sfx_roles: tuple[str, ...] = ()
    sfx_gain_min_db: str | None = None
    sfx_gain_max_db: str | None = None
    typography_count: int | None = None
    diagram_count: int | None = None
    emphasis_count: int | None = None
    evidence_sha256: tuple[str, ...] = ()
    candidate_media_sha256: str | None = None
    manifest_sha256: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class _Lists:
    captions: list[object] = field(default_factory=list)
    broll: list[object] = field(default_factory=list)
    sfx: list[object] = field(default_factory=list)
    typography: list[object] = field(default_factory=list)
    diagrams: list[object] = field(default_factory=list)
    emphasis: list[object] = field(default_factory=list)
    words: list[object] = field(default_factory=list)


def extract_features(
    document: dict[str, object] | None,
    *,
    candidate_id: str | None,
) -> ExtractedFeatures:
    """Read one JSON object. A missing key stays missing."""
    if document is None:
        if candidate_id is not None:
            raise ValueError("candidate id cannot be checked because the artifact file is unavailable")
        return ExtractedFeatures()
    matched = _match_candidate(document, candidate_id)
    lists = _lists(matched if matched is not None else document)
    duration = _duration(matched if matched is not None else document)
    if duration is None:
        duration = _int_or_none(document.get("canonical_duration_us"))
    scores = matched if matched is not None else document
    broll_duration = _total_duration(lists.broll)
    sfx_duration = _total_duration(lists.sfx)
    gains = _gains(lists.sfx)
    return ExtractedFeatures(
        duration_us=duration,
        candidate_rank=_int_or_none(scores.get("rank") if isinstance(scores, dict) else None),
        creative_score=_unit_score(scores, "creative_score"),
        edit_opportunity_score=_unit_score(scores, "edit_opportunity_score"),
        transcript_word_count=_optional_count(
            lists.words, _has_any(document, matched, "words", "transcript_words")
        ),
        caption_count=_optional_count(lists.captions, _has_any(document, matched, "captions", "caption_cues")),
        caption_style=_text(scores, "caption_style"),
        caption_algorithm_version=_text(document, "caption_algorithm_version")
        or _nested_text(document, "profile", "caption_algorithm_version"),
        alignment_quality=_text(document, "alignment_quality") or _text(document, "transcript_timing_quality"),
        profile_id=_text(document, "profile_id") or _nested_text(document, "profile", "profile_id"),
        profile_sha256=_sha(document, "profile_sha256") or _sha(document, "profile_fingerprint"),
        policy_ids=_policy_ids(document),
        motion_library_version=_text(document, "motion_library_version")
        or _nested_text(document, "profile", "motion_library_version"),
        renderer_recipe=_text(document, "renderer_recipe_version")
        or _nested_text(document, "profile", "renderer_recipe_version"),
        reframing_strategy=_text(document, "reframing_strategy"),
        broll_count=_count(lists.broll) if _has_any(document, matched, "broll_events", "broll") else None,
        broll_duration_us=broll_duration,
        sfx_count=_count(lists.sfx) if _has_any(document, matched, "sfx_events", "audio_events") else None,
        sfx_duration_us=sfx_duration,
        sfx_roles=_roles(lists.sfx),
        sfx_gain_min_db=gains[0],
        sfx_gain_max_db=gains[1],
        typography_count=_count(lists.typography)
        if _has_any(document, matched, "typography_events", "typography")
        else None,
        diagram_count=_optional_count(
            lists.diagrams, _has_any(document, matched, "diagram_events", "diagrams")
        ),
        emphasis_count=_count(lists.emphasis)
        if _has_any(document, matched, "emphasis_events", "emphasis")
        else None,
        evidence_sha256=_evidence(document),
        candidate_media_sha256=_sha(scores, "media_sha256") if isinstance(scores, dict) else None,
        manifest_sha256=_sha(document, "manifest_sha256"),
    )


def _match_candidate(document: dict[str, object], candidate_id: str | None) -> dict[str, object] | None:
    if candidate_id is None:
        return None
    for key in ("candidates", "drafts"):
        rows = document.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("candidate_id") == candidate_id:
                return row
    raise ValueError(f"candidate {candidate_id} is not in this artifact")


def _lists(source: dict[str, object]) -> _Lists:
    return _Lists(
        captions=_as_list(source, "captions", "caption_cues"),
        broll=_as_list(source, "broll_events", "broll"),
        sfx=_as_list(source, "sfx_events", "audio_events"),
        typography=_as_list(source, "typography_events", "typography"),
        diagrams=_as_list(source, "diagram_events", "diagrams"),
        emphasis=_as_list(source, "emphasis_events", "emphasis"),
        words=_as_list(source, "words", "transcript_words"),
    )


def _as_list(source: dict[str, object], *keys: str) -> list[object]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            return list(value)
    return []


def _has_any(document: dict[str, object], matched: dict[str, object] | None, *keys: str) -> bool:
    sources = [document] if matched is None else [matched, document]
    return any(key in source for source in sources for key in keys)


def _count(rows: list[object]) -> int:
    return len(rows)


def _optional_count(rows: list[object], present: bool) -> int | None:
    if not present:
        return None
    return len(rows)


def _duration(source: dict[str, object]) -> int | None:
    direct = _int_or_none(source.get("duration_us"))
    if direct is not None and direct > 0:
        return direct
    mapped = source.get("time_map")
    if not isinstance(mapped, dict):
        return None
    try:
        document = TimeMapDocument.model_validate(mapped)
    except ValidationError:
        return None
    duration = document.to_time_map().total_output_duration()
    if duration <= 0:
        return None
    return duration


def _total_duration(rows: list[object]) -> int | None:
    if not rows:
        return None
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            return None
        interval = row.get("interval")
        if not isinstance(interval, dict):
            return None
        start = _int_or_none(interval.get("output_start_us"))
        end = _int_or_none(interval.get("output_end_us"))
        if start is None or end is None or end <= start:
            return None
        total += end - start
    return total


def _gains(rows: list[object]) -> tuple[str | None, str | None]:
    found: list[Decimal] = []
    for row in rows:
        if not isinstance(row, dict) or "gain_db" not in row:
            continue
        value = row.get("gain_db")
        if isinstance(value, bool) or not isinstance(value, int | float | str):
            continue
        try:
            found.append(Decimal(str(value)))
        except Exception:
            continue
    if not found:
        return None, None
    return _decimal(min(found)), _decimal(max(found))


def _roles(rows: list[object]) -> tuple[str, ...]:
    roles: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("role"), str):
            roles.append(str(row["role"]))
    return tuple(sorted(set(roles)))


def _policy_ids(document: dict[str, object]) -> tuple[str, ...]:
    rows = document.get("policies")
    if not isinstance(rows, list):
        return ()
    found: list[str] = []
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("policy_id"), str):
            found.append(str(row["policy_id"]))
    return tuple(sorted(set(found)))


def _evidence(document: dict[str, object]) -> tuple[str, ...]:
    found: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.endswith("sha256") and isinstance(item, str) and len(item) == _SHA:
                    found.append(item)
                elif isinstance(item, dict):
                    walk(item)
                elif isinstance(item, list):
                    for child in item:
                        if isinstance(child, dict):
                            walk(child)

    walk(document)
    return tuple(sorted(set(found)))


def _unit_score(source: object, key: str) -> str | None:
    if not isinstance(source, dict) or key not in source or source[key] is None:
        return None
    value = source[key]
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    if number < 0 or number > 1:
        return None
    return _decimal(number)


def _decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _text(source: object, key: str) -> str | None:
    if not isinstance(source, dict):
        return None
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _nested_text(source: dict[str, object], parent: str, key: str) -> str | None:
    value = source.get(parent)
    return _text(value, key)


def _sha(source: object, key: str) -> str | None:
    value = _text(source, key)
    if value is None or len(value) != _SHA:
        return None
    return value


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
