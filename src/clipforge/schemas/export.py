"""Write and compare JSON Schema files. Drift fails the check. It is not rewritten quietly."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from clipforge.errors import SchemaExportError
from clipforge.schemas.common import SCHEMA_VERSION
from clipforge.schemas.registry import CONTRACT_MODELS, schema_title


def export_schemas(directory: Path) -> list[Path]:
    """Write one schema file per contract plus ``index.json``. Returns the paths."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    titles: list[str] = []
    for model in CONTRACT_MODELS:
        title = schema_title(model)
        if title in titles:
            raise SchemaExportError(f"duplicate schema title {title}")
        titles.append(title)
        path = directory / f"{title}.schema.json"
        payload = model.model_json_schema()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    index_path = directory / "index.json"
    index = {"schema_version": SCHEMA_VERSION, "models": titles}
    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(index_path)
    return written


def assert_schemas_current(directory: Path) -> None:
    """Raise ``SchemaExportError`` when ``directory`` does not match a fresh export."""
    if not directory.is_dir():
        raise SchemaExportError(
            f"schema directory does not exist: {directory}. "
            "Run `clipforge schema export` from the repository root and commit the result."
        )
    with tempfile.TemporaryDirectory() as tmp:
        export_schemas(Path(tmp))
        expected = _read_tree(Path(tmp))
    actual = _read_tree(directory)
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if missing or extra:
        raise SchemaExportError(
            "schema files do not match the Pydantic models. "
            f"Missing: {missing or 'none'}. Unexpected: {extra or 'none'}. "
            "Run `clipforge schema export` and review the diff. Do not delete a schema to silence this."
        )
    drifted = [name for name in expected if expected[name] != actual[name]]
    if drifted:
        raise SchemaExportError(
            "schema contents drifted for: "
            + ", ".join(sorted(drifted))
            + ". Run `clipforge schema export` and commit the updated files."
        )


def _read_tree(directory: Path) -> dict[str, str]:
    files = {
        path.name: path.read_text(encoding="utf-8")
        for path in directory.iterdir()
        if path.is_file() and path.suffix == ".json"
    }
    if not files:
        raise SchemaExportError(f"no JSON schema files found in {directory}")
    return files
