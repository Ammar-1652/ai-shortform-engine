"""Load, verify, and retrieve the local editorial knowledge library.

The library is local and deterministic. It supplies Codex with bounded,
source-linked guidance; it never executes upstream instructions or chooses a
render without a typed direction plan.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.media.workspace import atomic_replace, ensure_within
from clipforge.paths import find_repo_root, resolve_work_dir
from clipforge.schemas.editorial_knowledge import (
    ContextFact,
    DecisionAlternative,
    DirectionContextBundle,
    EditorialDecisionTrace,
    EditorialFeedback,
    EditorialGuidanceCard,
    EditorialStyleCard,
    KnowledgeConflict,
    KnowledgeEvaluationCase,
    KnowledgeLibraryDocument,
    KnowledgeRelease,
    KnowledgeSource,
    NarrativePattern,
    ReferenceObservation,
)

LIBRARY_PATH = Path("configs/editorial/knowledge/library.json")


class KnowledgeError(ClipforgeError):
    """Knowledge input is missing, stale, unsafe, or inconsistent."""


_ADMISSION_TYPES: dict[str, tuple[str, type[Any], str]] = {
    "source": ("sources", KnowledgeSource, "source_id"),
    "observation": ("observations", ReferenceObservation, "observation_id"),
    "evaluation": ("evaluations", KnowledgeEvaluationCase, "evaluation_id"),
    "guidance": ("guidance_cards", EditorialGuidanceCard, "card_id"),
    "pattern": ("narrative_patterns", NarrativePattern, "pattern_id"),
    "style": ("style_cards", EditorialStyleCard, "style_card_id"),
}


def _admission_payload(model: Any) -> dict[str, Any]:
    """Return a record payload with its persisted content digest checked."""
    if not hasattr(model, "model_dump"):
        raise KnowledgeError("knowledge admission requires a typed record")
    field = "content_sha256"
    payload = cast(dict[str, Any], model.model_dump(mode="json"))
    captured = payload.get(field)
    if not isinstance(captured, str) or len(captured) != 64:
        raise KnowledgeError("knowledge admission requires a persisted content_sha256")
    if isinstance(model, KnowledgeSource):
        return payload
    if canonical_digest(model, exclude=field) != captured:
        raise KnowledgeError("knowledge admission record digest is stale")
    return payload


def admit_record_to_library(
    *,
    config: Path,
    record_type: str,
    record_path: Path,
    release_id: str,
    created_by: Literal["codex_operator", "system_enforcer", "human_reviewer"] = "codex_operator",
) -> KnowledgeRelease:
    """Append one evaluated record and create a new active knowledge release.

    The previous release remains in the file as ``retired``.  No render or
    human approval is created by admission; contexts must explicitly select
    the new release and therefore receive a new dependency identity.
    """
    try:
        collection, model_type, id_field = _ADMISSION_TYPES[record_type]
    except KeyError as exc:
        raise KnowledgeError(f"unsupported admission record type: {record_type}") from exc
    target = config.absolute()
    if target.is_symlink() or not target.is_file():
        raise KnowledgeError(f"knowledge library must be a regular file: {target}")
    record_file = record_path.absolute()
    if record_file.is_symlink() or not record_file.is_file():
        raise KnowledgeError("knowledge admission record must be a regular file")
    try:
        record = model_type.model_validate_json(record_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        raise KnowledgeError(f"knowledge admission record is invalid: {exc}") from exc
    state = getattr(record, "state", None)
    if state is not None and state not in {"evaluated", "active"}:
        raise KnowledgeError("knowledge admission requires an evaluated or active record")
    payload = json.loads(target.read_text(encoding="utf-8"))
    library = KnowledgeLibrary.load(target)
    records = library.by_id()
    record_id = str(getattr(record, id_field))
    if record_id in records:
        raise KnowledgeError(f"knowledge record id already exists: {record_id}")
    payload.setdefault(collection, []).append(_admission_payload(record))
    current = library.active_release()
    release_payload = current.model_dump(mode="json")
    release_payload.update(
        {
            "release_id": release_id,
            "state": "active",
            "created_at": datetime.now(UTC).isoformat(),
            "created_by": created_by,
            "conflict_ids": [],
            "manifest_sha256": "0" * 64,
        }
    )
    previous = [item for item in payload.get("releases", []) if item.get("release_id") == current.release_id]
    if not previous:
        raise KnowledgeError("active knowledge release is missing from the library payload")
    previous[0]["state"] = "retired"
    previous_model = KnowledgeRelease.model_validate({**previous[0], "manifest_sha256": "0" * 64})
    previous[0]["manifest_sha256"] = canonical_digest(previous_model, exclude="manifest_sha256")
    ids = {
        "sources": set(release_payload.get("source_ids", [])),
        "observations": set(release_payload.get("observation_ids", [])),
        "guidance_cards": set(release_payload.get("guidance_card_ids", [])),
        "narrative_patterns": set(release_payload.get("narrative_pattern_ids", [])),
        "style_cards": set(release_payload.get("style_card_ids", [])),
        "evaluations": set(release_payload.get("evaluation_ids", [])),
    }
    id_bucket = {
        "sources": "source_ids",
        "observations": "observation_ids",
        "evaluations": "evaluation_ids",
        "guidance_cards": "guidance_card_ids",
        "narrative_patterns": "narrative_pattern_ids",
        "style_cards": "style_card_ids",
    }[collection]
    ids[collection].add(record_id)
    for key, values in ids.items():
        release_payload[
            id_bucket
            if key == collection
            else {
                "sources": "source_ids",
                "observations": "observation_ids",
                "evaluations": "evaluation_ids",
                "guidance_cards": "guidance_card_ids",
                "narrative_patterns": "narrative_pattern_ids",
                "style_cards": "style_card_ids",
            }[key]
        ] = sorted(values)
    release = KnowledgeRelease.model_validate(release_payload)
    release = release.model_copy(
        update={"manifest_sha256": canonical_digest(release, exclude="manifest_sha256")}
    )
    payload.setdefault("releases", []).append(release.model_dump(mode="json"))
    prepared = _prepare_payload(payload)
    KnowledgeLibraryDocument.model_validate(prepared)
    temporary = target.with_name(f".{target.name}.admit.{os.getpid()}.partial")
    temporary.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    KnowledgeLibrary.load(target)
    return release


def resolve_conflict_in_library(
    *,
    config: Path,
    conflict_id: str,
    winning_record_id: str,
    resolution_note: str,
    resolved_by: Literal["system_enforcer", "codex_operator", "human_reviewer"],
    release_id: str,
) -> KnowledgeRelease:
    """Resolve one conflict and publish a new active release atomically."""
    target = config.absolute()
    library = KnowledgeLibrary.load(target)
    conflict = library.find(conflict_id)
    if not isinstance(conflict, KnowledgeConflict):
        raise KnowledgeError(f"record is not a knowledge conflict: {conflict_id}")
    if winning_record_id not in conflict.record_ids:
        raise KnowledgeError("conflict winner must be one of the conflict records")
    payload = json.loads(target.read_text(encoding="utf-8"))
    for item in payload.get("conflicts", []):
        if item.get("conflict_id") == conflict_id:
            item.update(
                {
                    "status": "resolved",
                    "winning_record_id": winning_record_id,
                    "resolution_note": resolution_note,
                    "resolved_by": resolved_by,
                }
            )
    current = library.active_release()
    for item in payload.get("releases", []):
        if item.get("release_id") == current.release_id:
            item["state"] = "retired"
            previous = KnowledgeRelease.model_validate(item)
            item["manifest_sha256"] = canonical_digest(previous, exclude="manifest_sha256")
    release_payload = current.model_dump(mode="json")
    release_payload.update(
        {
            "release_id": release_id,
            "state": "active",
            "conflict_ids": [],
            "created_at": datetime.now(UTC).isoformat(),
            "created_by": resolved_by,
            "manifest_sha256": "0" * 64,
        }
    )
    release = KnowledgeRelease.model_validate(release_payload)
    release = release.model_copy(
        update={"manifest_sha256": canonical_digest(release, exclude="manifest_sha256")}
    )
    payload.setdefault("releases", []).append(release.model_dump(mode="json"))
    prepared = _prepare_payload(payload)
    KnowledgeLibraryDocument.model_validate(prepared)
    temporary = target.with_name(f".{target.name}.resolve.{os.getpid()}.partial")
    temporary.write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    KnowledgeLibrary.load(target)
    return release


def write_knowledge_proposal(
    record: Any,
    *,
    record_type: str,
    work_root: Path | None = None,
    filename_prefix: str | None = None,
) -> Path:
    """Persist a typed, unadmitted record under the ignored work root."""
    if record_type not in _ADMISSION_TYPES:
        raise KnowledgeError(f"unsupported knowledge proposal type: {record_type}")
    payload = _admission_payload(record)
    root = resolve_work_dir(work_root).absolute()
    directory = root / "editorial" / "proposals"
    ensure_within(root, directory)
    if directory.is_symlink():
        raise KnowledgeError("knowledge proposal directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    identifier = next(
        value for key, value in payload.items() if key.endswith("_id") and key != "schema_version"
    )
    final = directory / f"{filename_prefix or record_type}-{identifier}.json"
    ensure_within(root, final)
    if final.exists() or final.is_symlink():
        raise KnowledgeError("knowledge proposal ids are append-only")
    temporary = final.with_name(f".{final.name}.partial")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    atomic_replace(temporary, final, root)
    return final


def canonical_digest(payload: Any, *, exclude: str | None = None) -> str:
    """Digest JSON values with stable key ordering and UTF-8 text."""
    value = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    if exclude is not None and isinstance(value, dict):
        value = {key: item for key, item in value.items() if key != exclude}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _fill_digest(item: dict[str, Any], field: str) -> dict[str, Any]:
    payload = dict(item)
    if not payload.get(field):
        payload[field] = canonical_digest(payload, exclude=field)
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise KnowledgeError(f"knowledge library must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KnowledgeError(f"knowledge library could not be read: {path}") from exc
    if not isinstance(payload, dict):
        raise KnowledgeError("knowledge library root must be an object")
    return payload


def _verify_local_source_bytes(source: KnowledgeSource, *, repo_root: Path) -> None:
    """Verify the bytes behind a local knowledge source.

    Knowledge records are allowed to point at external pages or repositories,
    but a source admitted into the local release must never silently keep using
    a changed local file.  Relative local locators are therefore resolved
    beneath the repository root, rejected when they escape or are symlinks,
    and compared with the captured content digest.  External locators are
    verified by their pinned provenance and are not fetched during production.
    """
    locator = source.locator.strip()
    if (
        not locator
        or locator.startswith(("/", "\\"))
        or "\\" in locator
        or "://" in locator
        or locator.startswith("file:")
        or any(part == ".." for part in locator.split("/"))
    ):
        return
    # Check the lexical path and each existing component before resolving it.
    # Resolving first would turn a symlink into its target and make a forbidden
    # linked source appear to be an ordinary repository file.
    root = repo_root.absolute()
    path = root / locator
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise KnowledgeError(f"knowledge source escapes repository root: {source.source_id}") from exc
    cursor = root
    for component in Path(locator).parts:
        cursor = cursor / component
        if cursor.is_symlink():
            raise KnowledgeError(f"knowledge source contains a symlink: {source.source_id}: {locator}")
    if not path.is_file():
        raise KnowledgeError(f"knowledge source file is missing or unsafe: {source.source_id}: {locator}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if source.content_sha256 is None:
        raise KnowledgeError(f"knowledge source has no captured content hash: {source.source_id}")
    if actual != source.content_sha256:
        raise KnowledgeError(f"knowledge source bytes are stale: {source.source_id}")


def _prepare_payload(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "sources",
        "observations",
        "evaluations",
        "guidance_cards",
        "narrative_patterns",
        "style_cards",
        "conflicts",
        "releases",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise KnowledgeError(f"knowledge library contains unknown keys: {sorted(unknown)}")
    prepared = dict(payload)
    for key in allowed - {"schema_version"}:
        prepared.setdefault(key, [])
    for key, digest_field in (
        ("observations", "content_sha256"),
        ("evaluations", "content_sha256"),
        ("guidance_cards", "content_sha256"),
        ("narrative_patterns", "content_sha256"),
        ("style_cards", "content_sha256"),
        ("releases", "manifest_sha256"),
    ):
        values = prepared.get(key)
        if not isinstance(values, list):
            raise KnowledgeError(f"knowledge library field {key} must be a list")
        missing = [
            index
            for index, item in enumerate(values)
            if not isinstance(item, dict) or not item.get(digest_field)
        ]
        if missing:
            raise KnowledgeError(
                f"knowledge {key} records must persist {digest_field}; missing indices: {missing}"
            )
        prepared[key] = values
    return prepared


@dataclass(frozen=True, slots=True)
class KnowledgeLibrary:
    """Validated in-memory library plus cross-reference checks."""

    document: KnowledgeLibraryDocument
    path: Path

    @classmethod
    def load(cls, path: Path | None = None) -> KnowledgeLibrary:
        root = find_repo_root()
        target = path or (root / LIBRARY_PATH)
        if target.is_symlink() or not target.is_file():
            raise KnowledgeError(f"knowledge library must be a regular file: {target}")
        target = target.absolute()
        document = KnowledgeLibraryDocument.model_validate(_prepare_payload(_load_json(target)))
        library = cls(document=document, path=target)
        library.verify()
        return library

    def all_records(self) -> list[Any]:
        return [
            *self.document.sources,
            *self.document.observations,
            *self.document.evaluations,
            *self.document.guidance_cards,
            *self.document.narrative_patterns,
            *self.document.style_cards,
            *self.document.conflicts,
            *self.document.releases,
        ]

    def _records_with_id_field(self) -> Iterable[tuple[Any, str]]:
        groups: tuple[tuple[list[Any], str], ...] = (
            (self.document.sources, "source_id"),
            (self.document.observations, "observation_id"),
            (self.document.evaluations, "evaluation_id"),
            (self.document.guidance_cards, "card_id"),
            (self.document.narrative_patterns, "pattern_id"),
            (self.document.style_cards, "style_card_id"),
            (self.document.conflicts, "conflict_id"),
            (self.document.releases, "release_id"),
        )
        for items, field in groups:
            for item in items:
                yield item, field

    def by_id(self) -> dict[str, Any]:
        return {getattr(item, field): item for item, field in self._records_with_id_field()}

    def find(self, record_id: str) -> Any:
        try:
            return self.by_id()[record_id]
        except KeyError as exc:
            raise KnowledgeError(f"knowledge record not found: {record_id}") from exc

    def active_release(self, release_id: str | None = None) -> KnowledgeRelease:
        releases = self.document.releases
        if release_id is not None:
            matches = [item for item in releases if item.release_id == release_id]
            if not matches:
                raise KnowledgeError(f"knowledge release not found: {release_id}")
            release = matches[0]
            if release.state != "active":
                raise KnowledgeError(f"knowledge release is not active: {release_id}")
            return release
        active = [item for item in releases if item.state == "active"]
        if len(active) != 1:
            raise KnowledgeError("knowledge library must have exactly one active release")
        return active[0]

    def verify(self) -> None:
        records = self.by_id()
        repo_root = find_repo_root().resolve()
        for item in self.all_records():
            for field_name in (
                "source_ids",
                "observation_ids",
                "evaluation_ids",
                "guidance_card_ids",
                "narrative_pattern_ids",
                "style_card_ids",
                "motion_recipe_ids",
                "conflict_ids",
            ):
                values = getattr(item, field_name, None)
                if values is None:
                    continue
                for value in values:
                    if value not in records:
                        raise KnowledgeError(f"{type(item).__name__} references missing record {value}")
        for source in self.document.sources:
            _verify_local_source_bytes(source, repo_root=repo_root)
        # Content digests are immutable record identities.  The loader may
        # fill legacy omitted digests for compatibility, but admitted records
        # in the checked-in release must carry and verify their digest.
        for item, field in self._records_with_id_field():
            # KnowledgeSource.content_sha256 is the hash of its pinned local
            # bytes (or the externally captured source), verified above; it is
            # intentionally not the record-payload digest used by cards.
            if isinstance(item, KnowledgeSource):
                continue
            digest_field = "manifest_sha256" if isinstance(item, KnowledgeRelease) else "content_sha256"
            captured = getattr(item, digest_field, None)
            if not captured:
                raise KnowledgeError(f"knowledge record is missing {digest_field}: {getattr(item, field)}")
            expected = canonical_digest(item, exclude=digest_field)
            if captured != expected:
                raise KnowledgeError(f"knowledge record hash is stale: {getattr(item, field)}")
        for card in self.document.guidance_cards:
            if card.state == "active" and card.authority == "upstream_guidance":
                for source_id in card.source_ids:
                    source = records[source_id]
                    if not isinstance(source, KnowledgeSource):
                        raise KnowledgeError(f"guidance source is not a KnowledgeSource: {source_id}")
                    if source.permission not in {"analysis_allowed", "reuse_allowed"}:
                        raise KnowledgeError(f"active guidance source is not cleared for analysis: {source_id}")
        for release in self.document.releases:
            if release.state == "active" and release.conflict_ids:
                raise KnowledgeError(f"active release contains unresolved conflicts: {release.release_id}")

    def matching_guidance(
        self,
        *,
        language: str,
        platform: str,
        campaign_id: str | None,
        profile_id: str | None,
        tags: set[str],
        limit: int = 12,
    ) -> list[EditorialGuidanceCard]:
        matches: list[tuple[int, EditorialGuidanceCard]] = []
        for card in self.document.guidance_cards:
            if card.state != "active" or not _scope_matches(
                card.scope,
                language=language,
                platform=platform,
                campaign_id=campaign_id,
                profile_id=profile_id,
            ):
                continue
            haystack = " ".join(
                [card.title, card.intent, *card.triggers, *card.coordination, *card.avoid_when]
            ).casefold()
            score = sum(2 for tag in tags if tag.casefold() in haystack)
            score += 1 if card.implementation in {"supported", "guidance_only"} else 0
            matches.append((score, card))
        return [item for _, item in sorted(matches, key=lambda row: (-row[0], row[1].card_id))[:limit]]

    def matching_patterns(
        self,
        *,
        language: str,
        platform: str,
        campaign_id: str | None,
        profile_id: str | None,
        tags: set[str],
        limit: int = 6,
    ) -> list[NarrativePattern]:
        matches: list[tuple[int, NarrativePattern]] = []
        for pattern in self.document.narrative_patterns:
            if pattern.state != "active" or not _scope_matches(
                pattern.scope,
                language=language,
                platform=platform,
                campaign_id=campaign_id,
                profile_id=profile_id,
            ):
                continue
            haystack = " ".join(
                [
                    pattern.name,
                    pattern.hook_shape,
                    pattern.body_shape,
                    pattern.payoff_shape,
                    *pattern.required_source_facts,
                ]
            ).casefold()
            score = sum(2 for tag in tags if tag.casefold() in haystack)
            matches.append((score, pattern))
        return [item for _, item in sorted(matches, key=lambda row: (-row[0], row[1].pattern_id))[:limit]]

    def matching_styles(
        self,
        *,
        language: str,
        platform: str,
        campaign_id: str | None,
        profile_id: str | None,
        tags: set[str],
        limit: int = 4,
    ) -> list[EditorialStyleCard]:
        matches: list[tuple[int, EditorialStyleCard]] = []
        for style in self.document.style_cards:
            if style.state != "active" or not _scope_matches(
                style.scope,
                language=language,
                platform=platform,
                campaign_id=campaign_id,
                profile_id=profile_id,
            ):
                continue
            haystack = " ".join(
                [
                    style.name,
                    *style.visual_identity,
                    *style.pacing_rules,
                    *style.audio_rules,
                    *style.ending_rules,
                ]
            ).casefold()
            score = sum(2 for tag in tags if tag.casefold() in haystack)
            score += {"high": 2, "medium": 1, "low": 0}[style.confidence]
            matches.append((score, style))
        return [item for _, item in sorted(matches, key=lambda row: (-row[0], row[1].style_card_id))[:limit]]

    def build_context(
        self,
        *,
        project_id: str,
        source_asset_id: str,
        candidate_id: str,
        source_sha256: str,
        language: str,
        platform: str,
        facts: list[ContextFact],
        tags: set[str],
        provenance: Any,
        campaign_id: str | None = None,
        profile_id: str | None = None,
        transcript_sha256: str | None = None,
        alignment_sha256: str | None = None,
        visual_analysis_sha256: str | None = None,
        release_id: str | None = None,
        unknowns: list[str] | None = None,
        capability_ids: list[str] | None = None,
    ) -> DirectionContextBundle:
        release = self.active_release(release_id)
        guidance = self.matching_guidance(
            language=language,
            platform=platform,
            campaign_id=campaign_id,
            profile_id=profile_id,
            tags=tags,
        )
        patterns = self.matching_patterns(
            language=language,
            platform=platform,
            campaign_id=campaign_id,
            profile_id=profile_id,
            tags=tags,
        )
        styles = self.matching_styles(
            language=language,
            platform=platform,
            campaign_id=campaign_id,
            profile_id=profile_id,
            tags=tags,
        )
        from clipforge.editorial.motion_catalog import MotionCatalog

        motion_catalog = MotionCatalog.load()
        motion_ids = [
            recipe.recipe_id
            for recipe in motion_catalog.select_for_tags(
                tags,
                language=language,
                profile_id=profile_id,
            )
        ]
        payload: dict[str, Any] = {
            "context_id": f"ctx-{candidate_id}-{release.release_id}",
            "schema_version": "1.0.0",
            "project_id": project_id,
            "campaign_id": campaign_id,
            "source_asset_id": source_asset_id,
            "candidate_id": candidate_id,
            "language": language,
            "platform": platform,
            "profile_id": profile_id,
            "knowledge_release_id": release.release_id,
            "source_sha256": source_sha256,
            "transcript_sha256": transcript_sha256,
            "alignment_sha256": alignment_sha256,
            "visual_analysis_sha256": visual_analysis_sha256,
            "facts": [fact.model_dump(mode="json") for fact in facts],
            "guidance_card_ids": [card.card_id for card in guidance],
            "narrative_pattern_ids": [pattern.pattern_id for pattern in patterns],
            "style_card_ids": [style.style_card_id for style in styles],
            "motion_recipe_ids": motion_ids,
            "motion_catalog_sha256": motion_catalog.fingerprint(),
            "excluded_record_ids": list(release.conflict_ids),
            "unknowns": unknowns or [],
            "capability_ids": capability_ids or [],
            "context_sha256": "0" * 64,
            "provenance": provenance.model_dump(mode="json"),
            "created_at": datetime.now(UTC).isoformat(),
        }
        bundle = DirectionContextBundle.model_validate(payload)
        return bundle.model_copy(
            update={
                "context_sha256": canonical_digest(
                    bundle.model_dump(mode="json"),
                    exclude="context_sha256",
                )
            }
        )


def _scope_matches(
    scope: Any,
    *,
    language: str,
    platform: str,
    campaign_id: str | None,
    profile_id: str | None,
) -> bool:
    return (
        (not scope.languages or language in scope.languages)
        and (not scope.platforms or platform in scope.platforms)
        and (not scope.campaign_ids or campaign_id in scope.campaign_ids)
        and (not scope.profile_ids or profile_id in scope.profile_ids)
    )


def default_library_path() -> Path:
    return find_repo_root() / LIBRARY_PATH


def write_context(bundle: DirectionContextBundle, *, work_root: Path | None = None) -> tuple[Path, str]:
    root = resolve_work_dir(work_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = root / "editorial" / "contexts"
    ensure_within(root, directory)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise KnowledgeError("editorial context directory cannot be a symlink")
    final = directory / f"{bundle.context_id}.json"
    ensure_within(root, final)
    temporary = final.with_name(f".{final.name}.partial")
    payload = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    atomic_replace(temporary, final, root)
    return final, digest


def load_context(path: Path) -> tuple[DirectionContextBundle, str]:
    if path.is_symlink() or not path.is_file():
        raise KnowledgeError(f"context file must be a regular file: {path}")
    try:
        bundle = DirectionContextBundle.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise KnowledgeError(f"context file is invalid: {path}") from exc
    actual = canonical_digest(bundle.model_dump(mode="json"), exclude="context_sha256")
    if actual != bundle.context_sha256:
        raise KnowledgeError("context hash is stale")
    return bundle, actual


def write_feedback(feedback: EditorialFeedback, *, work_root: Path | None = None) -> Path:
    root = resolve_work_dir(work_root).resolve()
    directory = root / "editorial" / "feedback"
    ensure_within(root, directory)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise KnowledgeError("editorial feedback directory cannot be a symlink")
    final = directory / f"{feedback.feedback_id}.json"
    ensure_within(root, final)
    if final.exists():
        raise KnowledgeError("feedback ids are append-only; use a new feedback_id")
    temporary = final.with_name(f".{final.name}.partial")
    temporary.write_text(
        json.dumps(feedback.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    atomic_replace(temporary, final, root)
    return final


def build_decision_trace(
    context: DirectionContextBundle,
    *,
    reasons: list[str],
    selected_guidance_ids: list[str] | None = None,
    selected_pattern_ids: list[str] | None = None,
    selected_style_card_ids: list[str] | None = None,
    selected_motion_recipe_ids: list[str] | None = None,
    rejected: list[DecisionAlternative] | None = None,
    source_evidence_ids: list[str] | None = None,
    deviations: list[str] | None = None,
    operator_role: str = "codex_operator",
) -> EditorialDecisionTrace:
    allowed = (
        set(context.guidance_card_ids)
        | set(context.narrative_pattern_ids)
        | set(context.style_card_ids)
        | set(context.motion_recipe_ids)
    )
    selected = [
        *(selected_guidance_ids or []),
        *(selected_pattern_ids or []),
        *(selected_style_card_ids or []),
        *(selected_motion_recipe_ids or []),
    ]
    unknown = sorted(set(selected) - allowed)
    if unknown:
        raise KnowledgeError(f"decision trace selects records outside the context: {unknown}")
    return EditorialDecisionTrace(
        trace_id=f"trace-{context.context_id}",
        context_id=context.context_id,
        selected_guidance_ids=selected_guidance_ids or [],
        selected_pattern_ids=selected_pattern_ids or [],
        selected_style_card_ids=selected_style_card_ids or [],
        selected_motion_recipe_ids=selected_motion_recipe_ids or [],
        rejected=rejected or [],
        source_evidence_ids=source_evidence_ids or [],
        reasons=reasons,
        deviations=deviations or [],
        context_sha256=context.context_sha256,
        operator_role=cast(Literal["codex_operator", "human_reviewer"], operator_role),
        created_at=datetime.now(UTC),
    )


def write_decision_trace(trace: EditorialDecisionTrace, *, work_root: Path | None = None) -> tuple[Path, str]:
    root = resolve_work_dir(work_root).resolve()
    directory = root / "editorial" / "traces"
    ensure_within(root, directory)
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise KnowledgeError("editorial trace directory cannot be a symlink")
    final = directory / f"{trace.trace_id}.json"
    if final.exists():
        raise KnowledgeError("decision trace ids are immutable; use a new context")
    temporary = final.with_name(f".{final.name}.partial")
    temporary.write_text(
        json.dumps(trace.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    atomic_replace(temporary, final, root)
    return final, digest
