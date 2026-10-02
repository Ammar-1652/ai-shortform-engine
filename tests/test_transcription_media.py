"""One real prepare plus a fake ASR backend. Proves the audio offset is not applied twice."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.main import app
from clipforge.media.ingest import ingest_source
from clipforge.media.prepare import prepare_source
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.media import Transcript
from clipforge.storage import Database, get_source_manifest
from clipforge.transcription.models import ModelIdentity
from clipforge.transcription.profile import TranscriptionRequest
from clipforge.transcription.runtime import RuntimeFacts
from clipforge.transcription.service import transcribe_source
from tests.media_factory import require_ffmpeg, synth_video
from tests.test_transcription import _segment
from tests.transcription_fakes import FakeTranscriptionBackend

pytestmark = pytest.mark.media

runner = CliRunner()


@pytest.fixture(autouse=True)
def _reserve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLIPFORGE_DISK_RESERVE_GB", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")


def test_prepared_delayed_audio_maps_model_time_without_a_second_offset(tmp_path: Path) -> None:
    require_ffmpeg()
    source = synth_video(tmp_path, "delayed.mp4", duration="2", audio_offset="0.5")
    database = Database(tmp_path / "clipforge.sqlite3")
    database.initialize()
    created = runner.invoke(app, ["project", "create", "Media", "--db", str(database.path)])
    assert created.exit_code == 0, created.stderr
    project_id = created.stdout.strip()
    evidence = tmp_path / "evidence.txt"
    evidence.write_text("campaign brief fixture")
    ingested = ingest_source(
        database=database,
        project_id=project_id,
        source=str(source),
        rights_status="campaign_provided",
        rights_evidence=str(evidence),
        rights_name="Campaign provided footage",
        confirm_rights=True,
        work_root=tmp_path / "work",
    )
    prepare_source(database=database, source_asset_id=ingested.source_asset_id, work_root=tmp_path / "work")
    with database.connect() as connection:
        manifest = get_source_manifest(connection, ingested.source_asset_id)
    offset = manifest.probe.timeline.audio_offset_us
    assert offset is not None and offset > 0
    backend = FakeTranscriptionBackend(segments=(_segment(0.5, 1.2, "later"),))
    result = transcribe_source(
        database=database,
        source_asset_id=ingested.source_asset_id,
        work_root=tmp_path / "work",
        model_root=tmp_path / "models",
        request=TranscriptionRequest(model="tiny.en", language="en", device="cpu", compute_type="int8"),
        backend=backend,
        runtime_facts=RuntimeFacts(0, ("int8",), (), "unused"),
        model_identity=ModelIdentity("tiny.en", "local_directory", "/models/tiny.en", "rev-smoke"),
        created_by="tester",
    )
    assert backend.calls == 1
    assert result.cache_hit is False
    path = SourceWorkspace(tmp_path / "work", project_id, ingested.source_asset_id).transcript_file()
    document = Transcript.model_validate_json(path.read_text(encoding="utf-8"))
    assert document.segments[0].start_us == 500_000
    assert document.segments[0].start_us != 500_000 + offset
    assert document.clock == "canonical_video_t0"
