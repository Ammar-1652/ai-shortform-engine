"""Validated narrative preset catalog for the Codex direction layer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from clipforge.editorial.knowledge import canonical_digest
from clipforge.editorial.motion_catalog import MotionCatalog
from clipforge.errors import ClipforgeError
from clipforge.paths import find_repo_root
from clipforge.schemas.editorial_preset import EditorialPresetCatalog, PresetDefinition

PRESET_PATH = Path("configs/editorial/presets.json")


class PresetCatalogError(ClipforgeError):
    pass


@dataclass(frozen=True, slots=True)
class PresetCatalog:
    document: EditorialPresetCatalog
    path: Path

    @classmethod
    def load(cls, path: Path | None = None) -> PresetCatalog:
        target = (path or (find_repo_root() / PRESET_PATH)).absolute()
        if target.is_symlink() or not target.is_file():
            raise PresetCatalogError(f"preset catalog must be a regular file: {target}")
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
            document = EditorialPresetCatalog.model_validate(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise PresetCatalogError(f"preset catalog is invalid: {target}") from exc
        catalog = cls(document=document, path=target)
        catalog.verify()
        return catalog

    def verify(self) -> None:
        motion = MotionCatalog.load()
        approved = {recipe.recipe_id for recipe in motion.approved()}
        for preset in self.document.presets:
            expected = canonical_digest(preset.model_dump(mode="json"), exclude="preset_sha256")
            if expected != preset.preset_sha256:
                raise PresetCatalogError(f"preset hash is stale: {preset.preset_id}")
            missing = sorted(set(preset.motion_recipe_ids) - approved)
            if missing:
                raise PresetCatalogError(f"preset {preset.preset_id} references unavailable recipes: {missing}")

    def find(self, preset_id: str) -> PresetDefinition:
        for preset in self.document.presets:
            if preset.preset_id == preset_id:
                return preset
        raise PresetCatalogError(f"preset not found: {preset_id}")

    def fingerprint(self) -> str:
        return canonical_digest(self.document)
