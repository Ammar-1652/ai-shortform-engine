"""Bind browser work to the service's validated input and staged media bytes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from clipforge import __version__
from clipforge.errors import MediaError
from clipforge.hero.advanced_assets import confine_work_path
from clipforge.hero.render_checkpoint import renderer_dependency_files
from clipforge.media.hashing import sha256_file
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import AdvancedHeroRenderInput, advanced_fingerprint
from clipforge.schemas.provenance import ArtifactProvenance
from clipforge.schemas.render_checkpoint import AdvancedRenderAuthorization, RenderAuthorizationItem
from clipforge.transcription.io import publish_json


def authorize_render_candidate(
    *,
    workspace: SourceWorkspace,
    root: Path,
    run_dir: Path,
    render_input: AdvancedHeroRenderInput,
    output: Path,
    dependency_sha256: str,
    job_id: str,
    parent_artifact_id: str,
    actor: str,
) -> AdvancedRenderAuthorization:
    """Issue a worker receipt after producer validation and paired staging.

    This is an integrity boundary, not a sandbox against the local owner. A
    receipt does not approve a draft or replace database/rights verification.
    """
    batch_path = _safe(root, run_dir / "batch-input.json")
    try:
        batch = json.loads(batch_path.read_text(encoding="utf-8"))
        matches = [
            item for item in batch["items"] if item["input"]["candidate_id"] == render_input.candidate_id
        ]
        if len(matches) != 1:
            raise ValueError("candidate has no unique canonical batch item")
        canonical = matches[0]
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise MediaError("service batch input is missing or invalid before render authorization") from exc
    input_digest = advanced_fingerprint(render_input.model_dump(mode="json"))
    if (
        canonical["input"] != render_input.model_dump(mode="json")
        or canonical["input_sha256"] != input_digest
        or canonical["outputPath"] != str(output)
    ):
        raise MediaError("service render authorization does not match its canonical batch")
    names = {render_input.base_video_name, render_input.speech_name, *render_input.asset_names.values()}
    if (
        render_input.campaign_overlay is not None
        and render_input.campaign_overlay.cta_render_mode != "alpha_video_v1"
    ):
        raise MediaError("new authorized campaign renders require the official alpha video")
    staged_hashes = {}
    for name in sorted(names):
        path = _safe(root, run_dir / "staging" / name)
        if not path.is_file() or path.stat().st_size == 0:
            raise MediaError(f"service render staged input is missing or empty: {name}")
        staged_hashes[name] = sha256_file(path)
    _safe(root, output)
    dependencies = renderer_dependency_files()
    if advanced_fingerprint(dependencies) != dependency_sha256:
        raise MediaError("render authorization renderer dependencies changed since planning")
    now = datetime.now(UTC)
    document = AdvancedRenderAuthorization(
        authorization_id=str(uuid.uuid4()),
        advanced_set_id=render_input.advanced_set_id,
        source_asset_id=workspace.source_asset_id,
        source_sha256=render_input.source_sha256,
        batch_sha256=sha256_file(batch_path),
        renderer_dependency_sha256=dependency_sha256,
        renderer_dependency_files=dependencies,
        items=[
            RenderAuthorizationItem(
                candidate_id=render_input.candidate_id,
                input_sha256=input_digest,
                output_relative_path=output.relative_to(run_dir).as_posix(),
                staged_sha256=staged_hashes,
            )
        ],
        created_at=now,
        provenance=ArtifactProvenance(
            created_at=now,
            created_by=actor,
            tool="clipforge-advanced-authorization",
            tool_version=__version__,
            source_asset_ids=[workspace.source_asset_id],
            parent_artifact_ids=[parent_artifact_id],
            job_id=job_id,
            inputs_sha256=input_digest,
        ),
    )
    destination = _safe(root, run_dir / "authorization.json")
    publish_json(destination, document, root, workspace.partial_for(destination))
    # Keep a durable receipt per candidate. The run-level receipt remains the
    # worker's current authorization, while earlier candidates retain their
    # own immutable audit record when a multi-candidate run advances.
    candidate_destination = _safe(
        root,
        run_dir / "candidates" / render_input.candidate_id / "authorization.json",
    )
    candidate_destination.parent.mkdir(parents=True, exist_ok=True)
    publish_json(candidate_destination, document, root, workspace.partial_for(candidate_destination))
    return document


def _safe(root: Path, path: Path) -> Path:
    return confine_work_path(root, path.relative_to(root).as_posix(), label="render authorization")
