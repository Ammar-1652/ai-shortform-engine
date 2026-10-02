"""Atomic UTF-8 JSON inside the work root."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import atomic_replace, ensure_within


def dump_json(model: BaseModel) -> str:
    """Stable UTF-8 JSON. Non-English transcript text is not escaped."""
    payload = model.model_dump(mode="json")
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def publish_json(final: Path, model: BaseModel, root: Path, partial: Path) -> tuple[str, int]:
    """Validate containment, write the partial, hash it, and rename it into place."""
    text = dump_json(model)
    ensure_within(root, final)
    ensure_within(root, partial)
    partial.write_text(text, encoding="utf-8")
    digest = sha256_file(partial)
    size = partial.stat().st_size
    atomic_replace(partial, final, root)
    return digest, size


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")
