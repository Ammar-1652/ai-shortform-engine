"""Hero drafts for approved candidates. The fake aligner and encoder do not start a browser."""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
from datetime import timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.errors import MediaError, StorageError
from clipforge.hero.alignment import FakeForcedAlignment, build_alignment
from clipforge.hero.backend import FakeHeroRenderBackend
from clipforge.hero.captions import hero_caption_cues
from clipforge.hero.constants import KIND_HERO, MOTION_LIBRARY_VERSION
from clipforge.hero.motion import hero_motion_events
from clipforge.hero.service import align_hero_candidate, plan_hero_candidate, render_hero_drafts
from clipforge.hero.show import load_current_hero
from clipforge.hero.verify import verify_hero
from clipforge.media.hashing import sha256_file
from clipforge.preview.backend import FakeRoughRenderBackend
from clipforge.review.service import DecisionContext, record_decision, record_hero_decision, review_board
from clipforge.schemas.hero import AlignedWord
from clipforge.schemas.jobs import JobRecord, JobStatus
from clipforge.storage import find_artifact, get_job, insert_job, insert_review, list_jobs
from clipforge.transcription.io import publish_json as real_publish_json
from tests.candidate_support import PROJECT_ID, SOURCE_ID, STAMP, segment
from tests.preview_support import PreviewFixture, mine, ready_stack, render, short_profile

pytestmark = pytest.mark.hero
runner = CliRunner()


class CountingAligner(FakeForcedAlignment):
    calls: int = 0

    def align_words(self, words, *, source_start_us: int, source_end_us: int):
        self.calls += 1
        return super().align_words(words, source_start_us=source_start_us, source_end_us=source_end_us)


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "0")


def test_root_help_hides_hero_subcommands() -> None:
    top = runner.invoke(app, ["--help"])
    assert top.exit_code == 0
    assert "hero" in top.stdout
    for absent in ("publish", "transcribe", "render"):
        assert absent not in top.stdout


def test_only_the_current_approval_is_rendered(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path)
    preview_before = _tree(fixture.workspace.preview_root())
    aligner = CountingAligner()
    backend = FakeHeroRenderBackend()
    result = _hero(fixture, backend, aligner)
    assert result.status == "rendered"
    assert result.cache_hit is False
    assert result.rendered_count == 1
    assert result.job_id is not None
    assert aligner.calls == 1
    assert backend.calls == 1
    reasons = dict(result.excluded)
    assert reasons[ids[1]] == "rejected"
    assert reasons[ids[2]] == "changes_requested"
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    assert current.document.drafts[0].candidate_id == ids[0]
    assert current.document.profile.profile_id == "hero-draft-v1"
    assert current.document.profile.width == 1080
    assert current.document.motion_library_version == MOTION_LIBRARY_VERSION
    alignment_path = current.manifest_path.parent / "candidates" / ids[0] / "alignment.json"
    alignment = alignment_path.read_text(encoding="utf-8")
    assert "説明" in alignment
    assert "$12.50" in alignment
    assert " today." in alignment
    assert '"alignment_quality": "forced"' in alignment
    plan = (current.manifest_path.parent / "candidates" / ids[0] / "plan.json").read_text(encoding="utf-8")
    assert '"stage": "hero"' in plan
    assert "opening-fade-v1" in plan
    assert "caption-emphasis-v1" in plan
    assert _tree(fixture.workspace.preview_root()) == preview_before
    again = _hero(fixture, backend, aligner)
    assert again.cache_hit is True
    assert again.status == "cache_hit"
    assert backend.calls == 1
    assert aligner.calls == 1
    report = verify_hero(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "PASS"


def test_no_approval_is_a_noop(tmp_path: Path) -> None:
    fixture, _ids = _reviewed(tmp_path, decisions=("rejected", "rejected", "changes_requested"))
    backend = FakeHeroRenderBackend()
    result = _hero(fixture, backend, CountingAligner())
    assert result.status == "noop"
    assert result.job_id is None
    assert result.hero_set_id is None
    assert backend.calls == 0
    assert _hero_jobs(fixture) == []
    with fixture.database.connect() as connection:
        assert find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO) is None


def test_newer_decision_replaces_an_older_approval(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    with fixture.database.connect() as connection:
        reviews = list_jobs(connection, PROJECT_ID)
        del reviews
        from clipforge.storage import list_reviews

        stored = list_reviews(connection, PROJECT_ID)
    newest = stored[0].model_copy(
        update={
            "review_id": "review-newer",
            "decision": "rejected",
            "created_at": stored[0].created_at + timedelta(seconds=1),
        }
    )
    with fixture.database.transaction() as connection:
        insert_review(connection, newest)
    result = _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    assert result.status == "noop"
    assert dict(result.excluded)[ids[0]] == "rejected"
    assert board["artifact_id"]


def test_align_and_plan_keep_forced_text(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    aligner = CountingAligner()
    document = align_hero_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        work_root=fixture.work,
        alignment_backend=aligner,
    )
    assert document.words[0].text.startswith("Point")
    assert any("説明" in word.text for word in document.words)
    assert all(word.alignment_quality == "forced" for word in document.words)
    assert all(word.output_end_frame_exclusive > word.output_start_frame for word in document.words)
    plan = plan_hero_candidate(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        candidate_id=ids[0],
        work_root=fixture.work,
    )
    assert plan.edit_plan.stage == "hero"
    assert plan.edit_plan.broll_events == []
    assert plan.edit_plan.audio_events == []
    cues = hero_caption_cues(document.words)
    assert any("説明" in cue.text for cue in cues)
    first = hero_motion_events(
        candidate_id=ids[0],
        duration_us=plan.edit_plan.time_map.to_time_map().total_output_duration(),
        words=document.words,
    )
    second = hero_motion_events(
        candidate_id=ids[0],
        duration_us=plan.edit_plan.time_map.to_time_map().total_output_duration(),
        words=document.words,
    )
    assert [event.event_id for event in first] == [event.event_id for event in second]
    shown = runner.invoke(app, _show_args(fixture, ids[0]))
    assert shown.exit_code != 0
    rendered = _hero(fixture, FakeHeroRenderBackend(), aligner)
    assert rendered.rendered_count == 1
    assert aligner.calls == 1
    shown = runner.invoke(app, _show_args(fixture, ids[0]))
    assert shown.exit_code == 0
    assert "stage: hero" in shown.stdout
    assert "alignment_quality: forced" in shown.stdout
    listed = runner.invoke(
        app,
        ["hero", "list", SOURCE_ID, "--db", str(fixture.database.path), "--work-dir", str(fixture.work)],
    )
    assert listed.exit_code == 0
    assert ids[0] in listed.stdout


def test_unapproved_align_is_refused(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("changes_requested",))
    with pytest.raises(MediaError, match="needs correction"):
        align_hero_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=ids[0],
            work_root=fixture.work,
            alignment_backend=CountingAligner(),
        )


def test_plan_refuses_a_missing_alignment(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    with pytest.raises(MediaError, match="forced alignment"):
        plan_hero_candidate(
            database=fixture.database,
            source_asset_id=SOURCE_ID,
            candidate_id=ids[0],
            work_root=fixture.work,
        )


def test_partial_alignment_output_fails(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    from clipforge.preview.inputs import load_preview_inputs
    from clipforge.preview.service import default_profile
    from clipforge.review.service import require_current_preview

    inputs = load_preview_inputs(
        fixture.database,
        SOURCE_ID,
        fixture.work,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=False,
    )
    current = require_current_preview(fixture.database, SOURCE_ID, fixture.work)
    candidate = next(item for item in inputs.candidate_document.candidates if item.candidate_id == ids[0])
    bundle = next(item for item in inputs.candidate_document.evidence_bundles if item.candidate_id == ids[0])
    from clipforge.storage import list_reviews

    with fixture.database.connect() as connection:
        review = list_reviews(connection, PROJECT_ID)[0]

    class Short(FakeForcedAlignment):
        def align_words(self, words, *, source_start_us: int, source_end_us: int):
            bounds = super().align_words(words, source_start_us=source_start_us, source_end_us=source_end_us)
            return bounds[:-1]

    with pytest.raises(MediaError, match="one interval"):
        build_alignment(
            alignment_id="align-short",
            transcript=inputs.pair.transcript,
            transcript_sha256=inputs.pair.transcript_sha256,
            candidate=candidate,
            bundle=bundle,
            review=review,
            rough_artifact_id=current.artifact_id,
            asr_audio_sha256=inputs.asr_sha256,
            backend=Short(),
            created_by="tester",
            tool_version="0",
        )


def test_renderer_manifest_and_database_failures_keep_the_previous_set(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    first = _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    assert first.hero_set_id is not None
    with fixture.database.connect() as connection:
        original = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO)
    assert original is not None
    rough = _preview_hashes(fixture)

    class Boom(FakeHeroRenderBackend):
        def render_batch(self, batch_path, *, log_path):
            raise MediaError("encoder failed")

    with pytest.raises(MediaError, match="encoder failed"):
        _hero(fixture, Boom(), CountingAligner(), force=True)
    with fixture.database.connect() as connection:
        assert find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO).artifact_id == original.artifact_id
        failed = [job for job in list_jobs(connection, PROJECT_ID) if job.kind == "hero_draft_render"]
    assert any(job.status is JobStatus.FAILED for job in failed)
    assert _preview_hashes(fixture) == rough

    def fail_manifest(final: Path, model, root: Path, partial: Path):
        if final.name == "manifest.json":
            raise MediaError("manifest write failed")
        return real_publish_json(final, model, root, partial)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("clipforge.hero.service.publish_json", fail_manifest)
    try:
        with pytest.raises(MediaError, match="manifest write failed"):
            _hero(fixture, FakeHeroRenderBackend(), CountingAligner(), force=True)
    finally:
        monkeypatch.undo()
    with fixture.database.connect() as connection:
        assert find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO).artifact_id == original.artifact_id

    def fail_sidecar(final: Path, model, root: Path, partial: Path):
        if final.name == "hero-draft.recipe.json":
            raise OSError("sidecar write failed")
        return real_publish_json(final, model, root, partial)

    monkeypatch.setattr("clipforge.hero.service.publish_json", fail_sidecar)
    try:
        with pytest.raises(MediaError, match="sidecar"):
            _hero(fixture, FakeHeroRenderBackend(), CountingAligner(), force=True)
    finally:
        monkeypatch.undo()
    with fixture.database.connect() as connection:
        assert find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO).artifact_id == original.artifact_id

    def fail_insert(*args, **kwargs):
        raise StorageError("database write failed")

    monkeypatch.setattr("clipforge.hero.service.insert_artifact", fail_insert)
    try:
        with pytest.raises(StorageError, match="database write failed"):
            _hero(fixture, FakeHeroRenderBackend(), CountingAligner(), force=True)
    finally:
        monkeypatch.undo()
    with fixture.database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO)
    assert row is not None and row.artifact_id == original.artifact_id
    kept = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    assert kept.document.hero_set_id == first.hero_set_id
    assert ids[0]


def test_cancellation_marks_the_job_cancelled(tmp_path: Path) -> None:
    fixture, _ids = _reviewed(tmp_path, count=1, decisions=("approved",))

    class Cancel(FakeHeroRenderBackend):
        def render_batch(self, batch_path, *, log_path):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _hero(fixture, Cancel(), CountingAligner())
    with fixture.database.connect() as connection:
        jobs = [job for job in list_jobs(connection, PROJECT_ID) if job.kind == "hero_draft_render"]
        assert jobs[-1].status is JobStatus.CANCELLED
        assert find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO) is None


def test_corrupt_mp4_is_a_cache_miss(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    aligner = CountingAligner()
    backend = FakeHeroRenderBackend()
    _hero(fixture, backend, aligner)
    current = load_current_hero(fixture.database, SOURCE_ID, fixture.work)
    video = current.manifest_path.parent / "candidates" / ids[0] / "hero.mp4"
    video.write_bytes(b"not-an-mp4")
    again = _hero(fixture, backend, aligner)
    assert again.cache_hit is False
    assert backend.calls == 2
    checked = verify_hero(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert checked.status == "PASS"


def test_verify_is_read_only(tmp_path: Path) -> None:
    fixture, _ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    before = _tree(fixture.work)
    report = verify_hero(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "PASS"
    assert _tree(fixture.work) == before
    doctor = runner.invoke(app, ["hero", "doctor", "--work-dir", str(fixture.work)])
    assert doctor.exit_code == 0
    assert "motion-library-v1" in doctor.stdout
    assert "offline" in doctor.stdout


def test_old_rough_artifact_does_not_authorize_a_new_preview(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    first = _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    render(fixture, FakeRoughRenderBackend(), force=True)
    result = _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    assert result.status == "noop"
    assert "no decision" in dict(result.excluded)[ids[0]]
    with fixture.database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO)
    assert row is not None
    assert first.hero_set_id is not None
    report = verify_hero(database=fixture.database, source_asset_id=SOURCE_ID, work_root=fixture.work)
    assert report.status == "FAIL"


def test_hero_review_is_append_only_and_stale_writes_fail(tmp_path: Path) -> None:
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    hero = board["hero"]
    assert isinstance(hero, dict)
    assert hero["stage"] == "hero"
    draft = hero["drafts"][0]
    assert draft["alignment_quality"] == "forced"
    assert "説明" not in str(draft["preview_url"])
    context = DecisionContext(
        source_asset_id=SOURCE_ID,
        project_id=PROJECT_ID,
        artifact_id=str(hero["artifact_id"]),
        preview_set_id=str(hero["hero_set_id"]),
        manifest_sha256=str(hero["manifest_sha256"]),
        candidate_id=ids[0],
        subject_kind="hero",
        hero_set_id=str(hero["hero_set_id"]),
    )
    saved = record_hero_decision(
        database=fixture.database,
        work_root=fixture.work,
        context=context,
        decision="approved",
        reviewer_id="ada",
        notes="hero draft looks restrained",
    )
    assert saved.subject_kind == "hero"
    assert saved.automated is False
    stale = DecisionContext(
        source_asset_id=SOURCE_ID,
        project_id=PROJECT_ID,
        artifact_id="other-artifact",
        preview_set_id=str(hero["hero_set_id"]),
        manifest_sha256=str(hero["manifest_sha256"]),
        candidate_id=ids[0],
        subject_kind="hero",
        hero_set_id=str(hero["hero_set_id"]),
    )
    with pytest.raises(MediaError, match="reload before saving"):
        record_hero_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=stale,
            decision="approved",
            reviewer_id="ada",
            notes="",
        )


def test_force_preserves_the_previous_run(tmp_path: Path) -> None:
    fixture, _ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    first = _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    assert first.manifest_path is not None
    first_manifest = first.manifest_path.read_bytes()
    second = _hero(fixture, FakeHeroRenderBackend(), CountingAligner(), force=True)
    assert second.hero_set_id != first.hero_set_id
    assert first.manifest_path.read_bytes() == first_manifest
    with fixture.database.connect() as connection:
        row = find_artifact(connection, PROJECT_ID, SOURCE_ID, KIND_HERO)
    assert row is not None and row.job_id == second.job_id


def test_busy_hero_lock_fails_before_a_job(tmp_path: Path) -> None:
    fixture, _ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    lock = fixture.workspace.hero_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_exclusive, args=(str(lock), ready, release))
    holder.start()
    ready.wait(5)
    try:
        with pytest.raises(MediaError, match="Hero draft"):
            _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    finally:
        release.set()
        holder.join(5)
    assert _hero_jobs(fixture) == []


def test_symlink_fails_before_a_job(tmp_path: Path) -> None:
    fixture, _ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    outside = tmp_path / "escape"
    outside.mkdir()
    hero_root = fixture.workspace.hero_root()
    hero_root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MediaError, match="symlink"):
        _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    assert _hero_jobs(fixture) == []
    assert list(outside.iterdir()) == []


def test_stale_running_job_fails_only_while_the_lock_is_held(tmp_path: Path) -> None:
    fixture, _ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    stale = JobRecord(
        job_id="job-stale-hero",
        project_id=PROJECT_ID,
        kind="hero_draft_render",
        status=JobStatus.RUNNING,
        created_at=STAMP,
        updated_at=STAMP,
        payload={"source_asset_id": SOURCE_ID},
    )
    with fixture.database.transaction() as connection:
        insert_job(connection, stale)
    lock = fixture.workspace.hero_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    holder = context.Process(target=_hold_exclusive, args=(str(lock), ready, release))
    holder.start()
    ready.wait(5)
    try:
        with pytest.raises(MediaError, match="Hero draft"):
            _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
        with fixture.database.connect() as connection:
            assert get_job(connection, stale.job_id).status is JobStatus.RUNNING
    finally:
        release.set()
        holder.join(5)
    _hero(fixture, FakeHeroRenderBackend(), CountingAligner())
    with fixture.database.connect() as connection:
        assert get_job(connection, stale.job_id).status is JobStatus.FAILED


def test_caption_overlap_fails_closed() -> None:
    words = [
        _word("a", 0, 100, 0, 500, 0, 10),
        _word("b.", 2_000_000, 2_100_000, 100, 400, 3, 12),
    ]
    with pytest.raises(MediaError, match="overlap"):
        hero_caption_cues(words)


def test_cli_align_does_not_fall_back_when_whisperx_is_missing(tmp_path: Path) -> None:
    if importlib.util.find_spec("whisperx") is not None:
        pytest.skip("WhisperX is installed, so the missing-package failure is not the local path")
    fixture, ids = _reviewed(tmp_path, count=1, decisions=("approved",))
    result = runner.invoke(
        app,
        [
            "hero",
            "align",
            SOURCE_ID,
            ids[0],
            "--db",
            str(fixture.database.path),
            "--work-dir",
            str(fixture.work),
        ],
    )
    assert result.exit_code != 0
    assert "WhisperX" in result.stderr
    assert "provisional" in result.stderr
    assert _hero_jobs(fixture) == []


def _reviewed(
    tmp_path: Path,
    *,
    count: int = 3,
    decisions: tuple[str, ...] = ("approved", "rejected", "changes_requested"),
) -> tuple[PreviewFixture, list[str]]:
    texts = (
        "Point 0 説明 costs $12.50 today.",
        "Point 1 stays rejected after review.",
        "Point 2 needs another correction pass.",
    )
    pieces = []
    for index in range(count):
        start = index * 4_000_000
        pieces.append(segment(index, start, start + 1_200_000, texts[index]))
    duration = pieces[-1].end_us + 1_000_000
    fixture = ready_stack(tmp_path, segments=pieces, duration_us=duration)
    mined = mine(fixture, profile=short_profile(max_candidates=max(count, 1)))
    assert mined.selected_count == count
    render(fixture, FakeRoughRenderBackend())
    board = review_board(fixture.database, SOURCE_ID, fixture.work)
    cards = board["candidates"]
    assert isinstance(cards, list)
    ordered = _decision_order(fixture, cards, decisions)
    ids: list[str] = []
    for candidate_id, decision in ordered:
        ids.append(candidate_id)
        record_decision(
            database=fixture.database,
            work_root=fixture.work,
            context=DecisionContext(
                source_asset_id=str(board["source_asset_id"]),
                project_id=str(board["project_id"]),
                artifact_id=str(board["artifact_id"]),
                preview_set_id=str(board["preview_set_id"]),
                manifest_sha256=str(board["manifest_sha256"]),
                candidate_id=candidate_id,
            ),
            decision=decision,
            reviewer_id="ada",
            notes="",
        )
    return fixture, ids


def _decision_order(
    fixture: PreviewFixture,
    cards: list[object],
    decisions: tuple[str, ...],
) -> list[tuple[str, str]]:
    if len(cards) == 1 or "approved" not in decisions:
        pairs: list[tuple[str, str]] = []
        for card, decision in zip(cards, decisions, strict=True):
            assert isinstance(card, dict)
            pairs.append((str(card["candidate_id"]), decision))
        return pairs
    from clipforge.preview.inputs import load_preview_inputs
    from clipforge.preview.service import default_profile

    inputs = load_preview_inputs(
        fixture.database,
        SOURCE_ID,
        fixture.work,
        profile_fingerprint=default_profile().fingerprint(),
        create_workspace=False,
    )
    words = {word.word_id: word.text for piece in inputs.pair.transcript.segments for word in piece.words}
    text_by_id: dict[str, str] = {}
    for bundle in inputs.candidate_document.evidence_bundles:
        text_by_id[bundle.candidate_id] = "".join(words[word_id] for word_id in bundle.transcript_word_ids)
    chosen: list[tuple[str, str]] = []
    for card in cards:
        assert isinstance(card, dict)
        candidate_id = str(card["candidate_id"])
        text = text_by_id[candidate_id]
        if "説明" in text:
            decision = "approved"
        elif "rejected" in text:
            decision = "rejected"
        else:
            decision = "changes_requested"
        chosen.append((candidate_id, decision))
    rank = {"approved": 0, "rejected": 1, "changes_requested": 2}
    chosen.sort(key=lambda item: rank[item[1]])
    return chosen


def _show_args(fixture: PreviewFixture, candidate_id: str) -> list[str]:
    return [
        "hero",
        "show",
        SOURCE_ID,
        candidate_id,
        "--db",
        str(fixture.database.path),
        "--work-dir",
        str(fixture.work),
    ]


def _hero(
    fixture: PreviewFixture,
    backend: FakeHeroRenderBackend,
    aligner: CountingAligner,
    force: bool = False,
):
    return render_hero_drafts(
        database=fixture.database,
        source_asset_id=SOURCE_ID,
        work_root=fixture.work,
        force=force,
        backend=backend,
        alignment_backend=aligner,
    )


def _hero_jobs(fixture: PreviewFixture) -> list[JobRecord]:
    with fixture.database.connect() as connection:
        return [job for job in list_jobs(connection, PROJECT_ID) if job.kind == "hero_draft_render"]


def _preview_hashes(fixture: PreviewFixture) -> dict[str, str]:
    return _tree(fixture.workspace.preview_root())


def _tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    found: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            found[str(path.relative_to(root))] = sha256_file(path)
    return found


def _word(
    text: str,
    source_start: int,
    source_end: int,
    output_start: int,
    output_end: int,
    frame_start: int,
    frame_end: int,
) -> AlignedWord:
    return AlignedWord(
        word_id=f"w-{source_start}",
        candidate_id="cand-1",
        text=text,
        source_start_us=source_start,
        source_end_us=source_end,
        output_start_us=output_start,
        output_end_us=output_end,
        output_start_frame=frame_start,
        output_end_frame_exclusive=frame_end,
    )


def _hold_exclusive(path: str, ready: object, release: object) -> None:
    import fcntl

    descriptor = os.open(path, os.O_RDWR)
    fcntl.flock(descriptor, fcntl.LOCK_EX)
    ready.set()  # type: ignore[attr-defined]
    release.wait(30)  # type: ignore[attr-defined]
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)
