"""Knowledge-layer contracts, retrieval, hashes, and CLI boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.editorial.knowledge import (
    KnowledgeError,
    KnowledgeLibrary,
    admit_record_to_library,
    canonical_digest,
    load_context,
)
from clipforge.editorial.reference_analysis import _write_reference_evidence, propose_style_card
from clipforge.schemas.editorial_knowledge import ContextFact, ReferenceAnalysis, ReferenceMetric
from tests.helpers import provenance

runner = CliRunner()


def test_builtin_library_is_cross_reference_valid_and_selects_relevant_guidance() -> None:
    library = KnowledgeLibrary.load()
    assert library.active_release().release_id == "knowledge-release-v1"
    cards = library.matching_guidance(
        language="ar",
        platform="tiktok",
        campaign_id=None,
        profile_id=None,
        tags={"challenge", "caption", "motion"},
    )
    ids = {card.card_id for card in cards}
    assert "guidance-complete-arc-hook-v1" in ids
    assert "guidance-speech-safe-captions-v1" in ids
    assert "guidance-purposeful-motion-v1" in ids
    from clipforge.editorial.motion_catalog import MotionCatalog

    motion = MotionCatalog.load()
    assert len(motion.approved(language="ar")) >= 20
    assert "motion-concat-dissolve-v1" in {item.recipe_id for item in motion.approved(language="ar")}
    assert "motion-hook-card-v1" in {item.recipe_id for item in motion.approved(language="ar")}
    from clipforge.editorial.presets import PresetCatalog

    presets = PresetCatalog.load()
    assert {item.preset_id for item in presets.document.presets} == {
        "clean_explainer",
        "proof_comparison",
        "story_reveal",
        "transformation",
        "quote_emotion",
        "product_cta",
    }


def test_motion_catalog_detects_stale_persisted_recipe_hash(tmp_path: Path) -> None:
    import json

    from clipforge.editorial.motion_catalog import MotionCatalog, MotionCatalogError

    payload = json.loads(Path("configs/editorial/motion-recipes.json").read_text(encoding="utf-8"))
    payload["recipes"][0]["overuse_warning"] = "changed after admission"
    path = tmp_path / "motion-recipes.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        MotionCatalog.load(path)
    except MotionCatalogError as exc:
        assert "stale recipe hash" in str(exc)
    else:
        raise AssertionError("stale motion recipe hash was accepted")


def test_knowledge_admission_retires_previous_release_and_preserves_history(tmp_path: Path) -> None:
    from clipforge.schemas.editorial_knowledge import EditorialGuidanceCard

    payload = json.loads((Path("configs/editorial/knowledge/library.json")).read_text(encoding="utf-8"))
    item = dict(payload["guidance_cards"][0])
    item["card_id"] = "guidance-test-admission-v1"
    item["revision"] = int(item["revision"]) + 1
    item["content_sha256"] = "0" * 64
    model = EditorialGuidanceCard.model_validate(item)
    item["content_sha256"] = canonical_digest(model, exclude="content_sha256")
    record = tmp_path / "guidance.json"
    record.write_text(json.dumps(item), encoding="utf-8")
    library_path = tmp_path / "library.json"
    library_path.write_text(json.dumps(payload), encoding="utf-8")
    release = admit_record_to_library(
        config=library_path,
        record_type="guidance",
        record_path=record,
        release_id="knowledge-release-test",
    )
    admitted = KnowledgeLibrary.load(library_path)
    assert admitted.active_release().release_id == release.release_id
    assert admitted.find("guidance-test-admission-v1").card_id == "guidance-test-admission-v1"
    assert (
        next(item for item in admitted.document.releases if item.release_id == "knowledge-release-v1").state
        == "retired"
    )


def test_context_is_hash_bound_and_persisted_atomically(tmp_path: Path) -> None:
    library = KnowledgeLibrary.load()
    bundle = library.build_context(
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        language="ar",
        platform="tiktok",
        facts=[
            ContextFact(
                fact_id="fact-1",
                kind="source",
                text="The source contains a challenge and a visible reaction.",
                evidence_ids=["evidence-1"],
                verified=True,
            )
        ],
        tags={"challenge", "reaction"},
        provenance=provenance(["source-1"]),
    )
    from clipforge.editorial.knowledge import write_context

    path, file_digest = write_context(bundle, work_root=tmp_path)
    restored, digest = load_context(path)
    assert restored == bundle
    assert digest == bundle.context_sha256
    assert len(file_digest) == 64
    assert not list(path.parent.glob("*.partial"))


def test_context_hash_change_is_rejected(tmp_path: Path) -> None:
    library = KnowledgeLibrary.load()
    bundle = library.build_context(
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        language="en-US",
        platform="instagram",
        facts=[ContextFact(fact_id="fact-1", kind="source", text="A complete source arc.", verified=True)],
        tags={"story"},
        provenance=provenance(["source-1"]),
    )
    from clipforge.editorial.knowledge import write_context

    path, _ = write_context(bundle, work_root=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["unknowns"] = ["alignment is unavailable"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="stale"):
        load_context(path)


def test_decision_trace_rejects_records_outside_context_and_writes_hash(tmp_path: Path) -> None:
    from clipforge.editorial.knowledge import build_decision_trace, write_decision_trace

    library = KnowledgeLibrary.load()
    context = library.build_context(
        project_id="project-1",
        source_asset_id="source-1",
        candidate_id="candidate-1",
        source_sha256="a" * 64,
        language="ar",
        platform="tiktok",
        facts=[ContextFact(fact_id="fact-1", kind="source", text="A challenge is visible.", verified=True)],
        tags={"challenge"},
        provenance=provenance(["source-1"]),
    )
    with pytest.raises(KnowledgeError, match="outside the context"):
        build_decision_trace(context, reasons=["bad"], selected_guidance_ids=["unknown-card"])
    trace = build_decision_trace(
        context,
        reasons=["The style matches the challenge evidence."],
        selected_guidance_ids=["guidance-complete-arc-hook-v1"],
    )
    path, digest = write_decision_trace(trace, work_root=tmp_path)
    assert path.is_file()
    assert len(digest) == 64


def test_unknown_library_keys_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "library.json"
    path.write_text(json.dumps({"schema_version": "1.0.0", "unexpected": []}), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="unknown keys"):
        KnowledgeLibrary.load(path)


def test_local_knowledge_source_bytes_are_rehashed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import hashlib
    import shutil

    import clipforge.editorial.knowledge as knowledge_module

    source_root = Path(__file__).resolve().parents[1]
    payload = json.loads((source_root / "configs/editorial/knowledge/library.json").read_text(encoding="utf-8"))
    for source in payload["sources"]:
        relative = Path(source["locator"])
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, destination)
        source["content_sha256"] = hashlib.sha256(destination.read_bytes()).hexdigest()
    library_path = tmp_path / "library.json"
    library_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(knowledge_module, "find_repo_root", lambda: tmp_path)

    KnowledgeLibrary.load(library_path)
    target = tmp_path / payload["sources"][0]["locator"]
    target.write_text(target.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
    with pytest.raises(KnowledgeError, match="bytes are stale"):
        KnowledgeLibrary.load(library_path)


def test_local_knowledge_source_symlink_is_rejected_before_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import shutil

    import clipforge.editorial.knowledge as knowledge_module

    source_root = Path(__file__).resolve().parents[1]
    payload = json.loads((source_root / "configs/editorial/knowledge/library.json").read_text(encoding="utf-8"))
    for source in payload["sources"]:
        relative = Path(source["locator"])
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, destination)
        source["content_sha256"] = __import__("hashlib").sha256(destination.read_bytes()).hexdigest()
    target = tmp_path / payload["sources"][0]["locator"]
    replacement = tmp_path / "replacement-source.md"
    replacement.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(replacement)
    library_path = tmp_path / "library.json"
    library_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(knowledge_module, "find_repo_root", lambda: tmp_path)
    with pytest.raises(KnowledgeError, match="symlink"):
        KnowledgeLibrary.load(library_path)


def test_knowledge_record_digest_is_required_and_stale_digest_blocks(tmp_path: Path) -> None:
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "configs/editorial/knowledge/library.json").read_text()
    )
    payload["guidance_cards"][0]["content_sha256"] = "0" * 64
    path = tmp_path / "library.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(KnowledgeError, match="record hash is stale"):
        KnowledgeLibrary.load(path)


def test_active_guidance_requires_evaluation_and_supported_capability() -> None:
    from clipforge.schemas.editorial_knowledge import EditorialGuidanceCard
    from tests.helpers import stamp

    with pytest.raises(ValidationError, match="evaluation"):
        EditorialGuidanceCard(
            card_id="card-1",
            title="Card",
            authority="upstream_guidance",
            state="active",
            implementation="guidance_only",
            source_ids=["source-1"],
            intent="Intent",
            triggers=["trigger"],
            steps=["step"],
            avoid_when=["avoid"],
            limitations=["limit"],
            content_sha256="a" * 64,
            updated_at=stamp(),
        )


def test_knowledge_cli_is_available_and_context_requires_facts(tmp_path: Path) -> None:
    doctor = runner.invoke(app, ["editorial", "doctor"])
    assert doctor.exit_code == 0
    assert "PASS editorial_knowledge" in doctor.stdout
    listed = runner.invoke(app, ["editorial", "knowledge", "list", "--type", "style"])
    assert listed.exit_code == 0
    assert "style-tarteel-challenge-readable-v1" in listed.stdout
    failed = runner.invoke(
        app,
        [
            "editorial",
            "knowledge",
            "context",
            "--project-id",
            "project-1",
            "--source-asset-id",
            "source-1",
            "--candidate-id",
            "candidate-1",
            "--source-sha256",
            "a" * 64,
            "--language",
            "ar",
            "--platform",
            "tiktok",
            "--work-dir",
            str(tmp_path),
        ],
    )
    assert failed.exit_code != 0
    assert "fact" in failed.stderr.lower()


def test_direction_compare_is_read_only_and_deterministic(tmp_path: Path) -> None:
    from tests.test_direction import _document

    brief = tmp_path / "direction.json"
    brief.write_text(_document().model_dump_json(), encoding="utf-8")
    compared = runner.invoke(app, ["editorial", "direction", "compare", str(brief)])
    assert compared.exit_code == 0
    assert '"option_id": "option-b"' in compared.stdout
    before = brief.read_bytes()
    runner.invoke(app, ["editorial", "direction", "compare", str(brief)])
    assert brief.read_bytes() == before


def test_reference_metric_requires_explicit_unknown_reason() -> None:
    from pydantic import ValidationError

    from clipforge.schemas.editorial_knowledge import ReferenceMetric

    with pytest.raises(ValidationError):
        ReferenceMetric(
            name="hook_duration",
            value=None,
            method="frame_probe",
            evidence_kind="observed",
            limitation=None,
        )


def test_reference_measurements_create_inactive_style_proposal(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    analysis = ReferenceAnalysis(
        analysis_id="analysis-1",
        source_id="reference-1",
        source_locator="references/one.mp4",
        permission="analysis_allowed",
        permission_evidence="operator supplied",
        media_sha256="a" * 64,
        analyzer_version="reference-probe-v2",
        metrics=[
            ReferenceMetric(
                name="duration",
                value=1_000_000,
                unit="microseconds",
                evidence_kind="observed",
                method="ffprobe",
            ),
            ReferenceMetric(
                name="median_shot_duration",
                value=500_000,
                unit="microseconds",
                evidence_kind="observed",
                method="frame_probe",
            ),
            ReferenceMetric(
                name="cut_density",
                value=12,
                unit="cuts_per_minute",
                evidence_kind="observed",
                method="frame_probe",
            ),
        ],
        analysis_sha256="b" * 64,
        provenance=provenance(["reference-1"]),
        created_at=now,
    )
    card, path = propose_style_card(
        analysis,
        style_card_id="style-proposal-1",
        name="Observed reference cadence",
        work_root=tmp_path,
    )
    assert card.state == "proposed"
    assert card.content_sha256 != "0" * 64
    assert path.is_file()


def test_reference_evidence_writes_scene_midpoints_and_contact_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import cv2
    import numpy as np

    source = tmp_path / "reference.mp4"
    source.write_bytes(b"authorized-reference")

    class FakeRunner:
        def run(self, argv: list[str], **_kwargs: object) -> None:
            output = Path(argv[-1])
            output.parent.mkdir(parents=True, exist_ok=True)
            ok, encoded = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
            assert ok
            output.write_bytes(encoded.tobytes())

    monkeypatch.setattr("clipforge.editorial.reference_analysis.ProcessRunner", FakeRunner)
    monkeypatch.setattr("clipforge.editorial.reference_analysis.resolve_ffmpeg", lambda: "ffmpeg")
    frames, timestamps, contact = _write_reference_evidence(
        source=source,
        scenes=[(0, 1_000_000), (1_000_000, 3_000_000), (3_000_000, 4_000_000)],
        root=tmp_path,
        analysis_dir=tmp_path / "editorial" / "analyses",
        log_dir=tmp_path / "editorial" / "logs",
        analysis_id="analysis-test",
    )
    assert timestamps == [500_000, 2_000_000, 3_500_000]
    assert len(frames) == 3
    assert all(path.is_file() and path.stat().st_size > 0 for path in frames)
    assert contact.is_file() and contact.stat().st_size > 0
