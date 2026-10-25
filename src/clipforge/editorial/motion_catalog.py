"""Validate and select local, provenance-bound Remotion motion recipes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from clipforge.editorial.knowledge import canonical_digest
from clipforge.errors import ClipforgeError
from clipforge.paths import find_repo_root
from clipforge.schemas.motion_catalog import MotionCatalogDocument, MotionRecipe

MOTION_CATALOG_PATH = Path("configs/editorial/motion-recipes.json")

# These ids are the only production components currently present in the
# renderer. Adding another id requires a renderer component and browser tests.
RENDERER_COMPONENT_IDS = frozenset(
    {
        "caption-emphasis-v1",
        "context-line-v1",
        "hook-card-v1",
        "punch-card-v1",
        "concat_blur_dissolve_v1",
        "concat_push_v1",
        "motion-graphic-v1",
    }
)

# Local references are intentionally explicit.  A recipe cannot silently
# depend on a changed component while keeping the old catalog evidence.
REFERENCE_SOURCE_PATHS: dict[str, tuple[Path, ...]] = {
    # The native reference covers every component named by the catalog, not
    # just the transition helper.
    "motion-ref-native": (
        Path("apps/renderer/src/hero/AdvancedHeroDraft.tsx"),
        Path("apps/renderer/src/hero/ConcatMotion.tsx"),
        Path("apps/renderer/src/hero/motion.ts"),
        Path("apps/renderer/src/hero/motionRecipeRegistry.ts"),
        Path("apps/renderer/src/hero/MotionGraphic.tsx"),
    ),
    "motion-ref-iart-guidance": (Path("docs/third_party/motion-skills.lock.json"),),
}


class MotionCatalogError(ClipforgeError):
    """Motion catalog input is unsafe, stale, or unsupported."""


def _load_payload(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise MotionCatalogError(f"motion catalog must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MotionCatalogError(f"motion catalog could not be read: {path}") from exc
    if not isinstance(payload, dict):
        raise MotionCatalogError("motion catalog root must be an object")
    allowed = {"schema_version", "references", "recipes"}
    unknown = set(payload) - allowed
    if unknown:
        raise MotionCatalogError(f"motion catalog contains unknown keys: {sorted(unknown)}")
    recipes = payload.get("recipes", [])
    if not isinstance(recipes, list):
        raise MotionCatalogError("motion catalog recipes must be a list")
    for index, item in enumerate(recipes):
        if not isinstance(item, dict) or not item.get("recipe_sha256"):
            raise MotionCatalogError(f"motion recipe at index {index} is missing recipe_sha256")
    return payload


@dataclass(frozen=True, slots=True)
class MotionCatalog:
    document: MotionCatalogDocument
    path: Path

    @classmethod
    def load(cls, path: Path | None = None) -> MotionCatalog:
        target = path or (find_repo_root() / MOTION_CATALOG_PATH)
        if target.is_symlink() or not target.is_file():
            raise MotionCatalogError(f"motion catalog must be a regular file: {target}")
        target = target.absolute()
        try:
            document = MotionCatalogDocument.model_validate(_load_payload(target))
        except ValidationError as exc:
            raise MotionCatalogError(f"motion catalog is invalid: {target}") from exc
        catalog = cls(document=document, path=target)
        catalog.verify()
        return catalog

    def verify(self) -> None:
        references = {item.reference_id: item for item in self.document.references}
        root = find_repo_root().absolute()
        for reference in self.document.references:
            source_paths = REFERENCE_SOURCE_PATHS.get(reference.reference_id)
            if source_paths is None:
                # Remote/reference-only records are pinned by their captured
                # hash and provenance; they are never fetched during render.
                continue
            digester = hashlib.sha256()
            for source_path in source_paths:
                path = root / source_path
                cursor = root
                for component in source_path.parts:
                    cursor = cursor / component
                    if cursor.is_symlink():
                        raise MotionCatalogError(
                            f"motion reference contains a symlink: {reference.reference_id}"
                        )
                if not path.is_file():
                    raise MotionCatalogError(f"motion reference file is missing: {reference.reference_id}")
                digester.update(source_path.as_posix().encode("utf-8"))
                digester.update(b"\0")
                digester.update(path.read_bytes())
                digester.update(b"\0")
            actual = digester.hexdigest()
            if actual != reference.content_sha256:
                raise MotionCatalogError(f"motion reference bytes are stale: {reference.reference_id}")
        for recipe in self.document.recipes:
            if recipe.component_id not in RENDERER_COMPONENT_IDS:
                raise MotionCatalogError(
                    f"recipe {recipe.recipe_id} names an unavailable Remotion component {recipe.component_id}"
                )
            if recipe.fallback_component_id not in RENDERER_COMPONENT_IDS:
                raise MotionCatalogError(
                    f"recipe {recipe.recipe_id} names an unavailable fallback component "
                    f"{recipe.fallback_component_id}"
                )
            reference = references[recipe.reference_id]
            if recipe.state == "approved" and reference.permission != "reuse_allowed":
                raise MotionCatalogError(
                    f"approved recipe {recipe.recipe_id} requires a reuse-cleared reference"
                )
            expected = canonical_digest(recipe.model_dump(mode="json"), exclude="recipe_sha256")
            if expected != recipe.recipe_sha256:
                raise MotionCatalogError(f"recipe {recipe.recipe_id} has a stale recipe hash")

    def find(self, recipe_id: str) -> MotionRecipe:
        for recipe in self.document.recipes:
            if recipe.recipe_id == recipe_id:
                return recipe
        raise MotionCatalogError(f"motion recipe not found: {recipe_id}")

    def fingerprint(self) -> str:
        return canonical_digest(self.document)

    def approved(self, *, language: str | None = None, profile_id: str | None = None) -> list[MotionRecipe]:
        selected = []
        for recipe in self.document.recipes:
            if recipe.state != "approved":
                continue
            if language and recipe.compatible_languages and language not in recipe.compatible_languages:
                continue
            if profile_id and recipe.compatible_profiles and profile_id not in recipe.compatible_profiles:
                continue
            selected.append(recipe)
        return sorted(selected, key=lambda item: item.recipe_id)

    def select_for_tags(
        self,
        tags: set[str],
        *,
        language: str | None = None,
        profile_id: str | None = None,
        limit: int = 8,
    ) -> list[MotionRecipe]:
        matches: list[tuple[int, MotionRecipe]] = []
        for recipe in self.approved(language=language, profile_id=profile_id):
            haystack = " ".join(recipe.scene_intents).casefold()
            score = sum(2 for tag in tags if tag.casefold() in haystack)
            score += 1 if recipe.readability_risk == "low" else 0
            matches.append((score, recipe))
        return [recipe for _, recipe in sorted(matches, key=lambda row: (-row[0], row[1].recipe_id))[:limit]]


def default_motion_catalog_path() -> Path:
    return find_repo_root() / MOTION_CATALOG_PATH
