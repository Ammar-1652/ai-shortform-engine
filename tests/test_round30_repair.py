"""Round 30 repair: identity, jump cuts, cache, and final-review facts."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

from clipforge.errors import MediaError
from clipforge.hero.align_worker import install_offline_guards
from clipforge.hero.alignment import (
    FakeForcedAlignment,
    _align_with_side_python,
    _require_worker_identity,
    _stored_locale,
    build_alignment,
)
from clipforge.hero.captions import _MAX_GAP_US, hero_caption_pieces
from clipforge.hero.service import _require_fresh_alignment
from clipforge.language.model_manifest import (
    english_checkpoint_file,
    measure_english_checkpoint,
    measure_tree,
    sha256_file,
    speech_smoke_manifest,
)
from clipforge.language.providers import provider_for
from clipforge.language.registry import alignment_claim
from clipforge.media.workspace import SourceWorkspace
from clipforge.review.final_gate import final_board, language_evidence
from clipforge.schemas.candidates import CandidateEvidenceBundle
from clipforge.schemas.editorial import CandidateClip, CandidateEvidence, CandidateStatus, EvidenceKind
from clipforge.schemas.governance import ComplianceResult, ComplianceStatus, ReviewDecision
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument
from clipforge.schemas.media import TranscriptWord
from clipforge.schemas.time import TimelineSegment, TimeMapDocument
from tests.candidate_support import PROJECT_ID, SOURCE_ID, segment, transcript_document
from tests.helpers import provenance, stamp
from tests.test_round16 import _world

_SHA = "a" * 64
_ASR = "b" * 64
_TRANSCRIPT = "c" * 64
_SOURCE = "d" * 64


class _Recording(FakeForcedAlignment):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[int, int, list[str]]] = []

    def align_words(self, words, *, source_start_us: int, source_end_us: int):
        self.calls.append((source_start_us, source_end_us, [word.text.strip() for word in words]))
        return super().align_words(words, source_start_us=source_start_us, source_end_us=source_end_us)


def _map() -> TimeMapDocument:
    return TimeMapDocument(
        time_map_id="map-jump",
        segments=[
            TimelineSegment(segment_id="seg-0", source_start_us=2_000_000, source_end_us=3_000_000),
            TimelineSegment(segment_id="seg-1", source_start_us=0, source_end_us=1_000_000),
        ],
    )


def _bundle(word_ids: list[str]) -> CandidateEvidenceBundle:
    return CandidateEvidenceBundle(
        candidate_id="cand-jump",
        transcript_segment_ids=["seg-0", "seg-1"],
        transcript_word_ids=word_ids,
        transcript_excerpt="alpha beta gamma delta",
        transcript_start_us=0,
        transcript_end_us=3_000_000,
        visual_scene_ids=["scene-1"],
        source_start_us=0,
        source_end_us=3_000_000,
    )


def _candidate() -> CandidateClip:
    return CandidateClip(
        candidate_id="cand-jump",
        project_id=PROJECT_ID,
        source_asset_id=SOURCE_ID,
        status=CandidateStatus.READY_FOR_REVIEW,
        time_map=_map(),
        provenance=provenance([SOURCE_ID]),
        evidence=[
            CandidateEvidence(evidence_id="ev-t", kind=EvidenceKind.TRANSCRIPT, detail="speech"),
            CandidateEvidence(evidence_id="ev-v", kind=EvidenceKind.VISUAL, detail="frame"),
        ],
        compliance=[
            ComplianceResult(
                result_id="result-1",
                rule_id="rule-1",
                status=ComplianceStatus.PASS,
                evidence="cleared",
            )
        ],
    )


def _review() -> ReviewDecision:
    return ReviewDecision(
        review_id="review-jump",
        project_id=PROJECT_ID,
        candidate_id="cand-jump",
        subject_kind="candidate",
        decision="approved",
        reviewer_id="ada",
        created_at=stamp(),
        automated=False,
    )


def _transcript():
    """Source-ordered segments. The bundle lists words in TimeMap output order."""
    early = segment(0, 0, 1_000_000, "gamma delta")
    late = segment(1, 2_000_000, 3_000_000, "alpha beta")
    pieces = [late, early]
    document = transcript_document([early, late], 4_000_000, asr_sha256=_ASR)
    return document, pieces


class _Manifest:
    def __init__(self, digest: str) -> None:
        self.content_sha256 = digest


class _Pair:
    def __init__(self, transcript: object, transcript_sha: str, source_sha: str) -> None:
        self.transcript = transcript
        self.transcript_sha256 = transcript_sha
        self.manifest = _Manifest(source_sha)


class _Inputs:
    def __init__(self, pair: _Pair, asr: str) -> None:
        self.pair = pair
        self.asr_sha256 = asr


def _built(aligner: FakeForcedAlignment | None = None):
    transcript, pieces = _transcript()
    word_ids = [word.word_id for piece in pieces for word in piece.words]
    backend = aligner or _Recording()
    document = build_alignment(
        alignment_id="align-jump",
        transcript=transcript,
        transcript_sha256=_TRANSCRIPT,
        candidate=_candidate(),
        bundle=_bundle(word_ids),
        review=_review(),
        rough_artifact_id="rough-1",
        asr_audio_sha256=_ASR,
        backend=backend,
        created_by="tester",
        tool_version="0",
        source_sha256=_SOURCE,
    )
    inputs = _Inputs(_Pair(transcript, _TRANSCRIPT, _SOURCE), _ASR)
    return document, inputs, backend


def test_catalog_constants_are_not_speech_proof(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", raising=False)
    assert provider_for("en-US").live_status != "verified_live"
    assert provider_for("en-GB").live_status != "verified_live"
    assert provider_for("ja").live_status != "verified_live"
    assert provider_for("fr-FR").live_status != "verified_live"
    assert alignment_claim("en-US") == "alignment_not_claimed"


def test_a_manifest_string_without_audio_does_not_promote(monkeypatch: pytest.MonkeyPatch) -> None:
    path = english_checkpoint_file()
    if path is None:
        pytest.skip("english checkpoint is not installed")
    monkeypatch.delenv("CLIPFORGE_SPEECH_EVIDENCE_ROOT", raising=False)
    monkeypatch.setattr(
        "clipforge.language.model_manifest.speech_smoke_manifest",
        lambda _locale, evidence_root=None: measure_english_checkpoint(path).manifest_sha256,
    )
    assert provider_for("en-US").live_status != "verified_live"
    assert provider_for("en-GB").live_status != "verified_live"


def test_weight_tokenizer_and_revision_failures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    weight = tmp_path / "pytorch_model.bin"
    weight.write_bytes(b"weights-v1")
    token = tmp_path / "tokenizer.json"
    token.write_text("alpha", encoding="utf-8")
    first = measure_tree(tmp_path, model_id="example/model", revision="rev-a")
    assert first is not None
    token.write_text("beta", encoding="utf-8")
    second = measure_tree(tmp_path, model_id="example/model", revision="rev-a")
    assert second is not None
    assert second.checkpoint_sha256 == first.checkpoint_sha256
    assert second.manifest_sha256 != first.manifest_sha256
    weight.write_bytes(b"weights-v2")
    changed = measure_tree(tmp_path, model_id="example/model", revision="rev-a")
    assert changed is not None
    assert changed.checkpoint_sha256 != first.checkpoint_sha256
    monkeypatch.setattr(
        "clipforge.language.model_manifest.huggingface_snapshot",
        lambda *_args, **_kwargs: tmp_path,
    )
    assert provider_for("ja").live_status == "stale_alignment"
    monkeypatch.setattr(
        "clipforge.language.model_manifest.huggingface_snapshot",
        lambda *_args, **_kwargs: None,
    )
    assert provider_for("fr-FR").live_status == "model_missing"
    assert measure_tree(tmp_path / "missing", model_id="example/model", revision="none") is None


def test_worker_identity_lies_fail_closed(tmp_path: Path) -> None:
    checkpoint = tmp_path / "wav2vec2_fairseq_base_ls960_asr_ls960.pth"
    checkpoint.write_bytes(b"checkpoint-bytes")
    digest = sha256_file(checkpoint)
    base = {
        "revision": "3.4.5",
        "model": "WAV2VEC2_ASR_BASE_960H",
        "language_code": "en",
        "whisperx": "3.4.5",
        "device": "cpu",
        "checkpoint_sha256": digest,
        "manifest_sha256": measure_tree(
            tmp_path,
            model_id="WAV2VEC2_ASR_BASE_960H",
            revision="3.4.5",
        ).manifest_sha256,  # type: ignore[union-attr]
    }
    lying = dict(base)
    lying["revision"] = "published-lie"
    with pytest.raises(MediaError, match="stale_alignment"):
        _require_worker_identity(
            language_code="en",
            model_name="WAV2VEC2_ASR_BASE_960H",
            revision="3.4.5",
            model_path="",
            checkpoint_path=str(checkpoint),
            reported=lying,
        )
    mismatched = dict(base)
    mismatched["checkpoint_sha256"] = "0" * 64
    with pytest.raises(MediaError, match="stale_alignment"):
        _require_worker_identity(
            language_code="en",
            model_name="WAV2VEC2_ASR_BASE_960H",
            revision="3.4.5",
            model_path="",
            checkpoint_path=str(checkpoint),
            reported=mismatched,
        )
    old_version = dict(base)
    old_version["whisperx"] = "3.4.4"
    with pytest.raises(MediaError, match="stale_alignment"):
        _require_worker_identity(
            language_code="en",
            model_name="WAV2VEC2_ASR_BASE_960H",
            revision="3.4.5",
            model_path="",
            checkpoint_path=str(checkpoint),
            reported=old_version,
        )


def test_missing_local_weights_do_not_reach_the_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "clipforge.hero.alignment._local_identity",
        lambda _language, _model: ("", "", ""),
    )
    word = TranscriptWord(word_id="w-1", text="bonjour", start_us=0, end_us=1_000)
    with pytest.raises(MediaError, match="model_missing"):
        _align_with_side_python(
            "/tmp/does-not-need-to-exist.wav",
            [word],
            source_start_us=0,
            source_end_us=1_000_000,
            allow_model_download=False,
            language_code="fr",
            model_name="jonatasgrosman/wav2vec2-large-xlsr-53-french",
        )


def test_offline_guards_block_hub_and_huggingface_downloads() -> None:
    saved = {name: sys.modules.get(name) for name in ("torch", "torch.hub", "huggingface_hub", "nltk")}
    torch_mod = types.ModuleType("torch")
    hub = types.ModuleType("torch.hub")
    hub.download_url_to_file = lambda *_args, **_kwargs: "downloaded"  # type: ignore[attr-defined]
    torch_mod.hub = hub  # type: ignore[attr-defined]
    huggingface = types.ModuleType("huggingface_hub")
    huggingface.hf_hub_download = lambda *_args, **_kwargs: "downloaded"  # type: ignore[attr-defined]
    huggingface.snapshot_download = lambda *_args, **_kwargs: "downloaded"  # type: ignore[attr-defined]
    nltk_mod = types.ModuleType("nltk")
    nltk_mod.download = lambda *_args, **_kwargs: True  # type: ignore[attr-defined]
    sys.modules["torch"] = torch_mod
    sys.modules["torch.hub"] = hub
    sys.modules["huggingface_hub"] = huggingface
    sys.modules["nltk"] = nltk_mod
    try:
        install_offline_guards()
        with pytest.raises(RuntimeError, match=r"torch\.hub download is blocked"):
            hub.download_url_to_file("https://example.invalid/weight")
        with pytest.raises(RuntimeError, match="Hugging Face download is blocked"):
            huggingface.hf_hub_download("example/model", "pytorch_model.bin")
        with pytest.raises(RuntimeError, match="nltk download is blocked"):
            nltk_mod.download("punkt")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def test_jump_cut_aligns_each_segment_on_its_own_source_interval() -> None:
    aligner = _Recording()
    document, _inputs, backend = _built(aligner)
    assert backend is aligner
    assert [call[:2] for call in aligner.calls] == [(2_000_000, 3_000_000), (0, 1_000_000)]
    assert [word.text.strip() for word in document.words] == ["alpha", "beta", "gamma", "delta"]
    assert [word.segment_index for word in document.words] == [0, 0, 1, 1]
    assert document.words[2].source_start_us < document.words[0].source_start_us
    assert document.words[0].output_end_us <= document.words[1].output_start_us
    assert document.words[1].output_end_us <= document.words[2].output_start_us
    assert document.words[1].source_end_us == 3_000_000
    assert document.words[2].source_start_us == 0
    assert document.locale == "en-US"


def test_boundary_duplicate_skipped_and_wrong_segment_fail() -> None:
    transcript, pieces = _transcript()
    word_ids = [word.word_id for piece in pieces for word in piece.words]
    outside = (
        pieces[0].words[0].model_copy(update={"word_id": "w-gap", "start_us": 1_500_000, "end_us": 1_600_000})
    )
    transcript.segments[0].words.append(outside)
    with pytest.raises(MediaError, match="outside the candidate TimeMap"):
        build_alignment(
            alignment_id="align-gap",
            transcript=transcript,
            transcript_sha256=_TRANSCRIPT,
            candidate=_candidate(),
            bundle=_bundle([*word_ids, "w-gap"]),
            review=_review(),
            rough_artifact_id="rough-1",
            asr_audio_sha256=_ASR,
            backend=FakeForcedAlignment(),
            created_by="tester",
            tool_version="0",
            source_sha256=_SOURCE,
        )

    class _Wrong(FakeForcedAlignment):
        def align_words(self, words, *, source_start_us: int, source_end_us: int):
            if source_start_us == 0:
                return [(2_100_000, 2_400_000) for _word in words]
            return super().align_words(words, source_start_us=source_start_us, source_end_us=source_end_us)

    with pytest.raises(MediaError, match="outside its TimeMap segment"):
        _built(_Wrong())

    class _Duplicate(FakeForcedAlignment):
        def align_words(self, words, *, source_start_us: int, source_end_us: int):
            del source_end_us
            return [(source_start_us + 1, source_start_us + 2) for _word in words]

    with pytest.raises((MediaError, ValidationError)):
        _built(_Duplicate())

    class _Endpoint(FakeForcedAlignment):
        def align_words(self, words, *, source_start_us: int, source_end_us: int):
            del source_start_us
            return [(source_end_us, source_end_us + 1) for _word in words]

    with pytest.raises(MediaError, match="outside its TimeMap segment"):
        _built(_Endpoint())


def test_caption_gap_above_the_cadence_splits_the_cue() -> None:
    first = AlignedWord(
        word_id="w-a",
        candidate_id="cand-1",
        text="alpha",
        source_start_us=0,
        source_end_us=100_000,
        output_start_us=0,
        output_end_us=100_000,
        output_start_frame=0,
        output_end_frame_exclusive=3,
        segment_index=0,
    )
    second = first.model_copy(
        update={
            "word_id": "w-b",
            "text": "beta",
            "source_start_us": 100_000 + _MAX_GAP_US,
            "source_end_us": 200_000 + _MAX_GAP_US,
            "output_start_us": 100_000 + _MAX_GAP_US,
            "output_end_us": 200_000 + _MAX_GAP_US,
            "output_start_frame": 40,
            "output_end_frame_exclusive": 46,
        }
    )
    assert len(hero_caption_pieces([first, second])) == 1
    later = second.model_copy(
        update={
            "source_start_us": second.source_start_us + 1,
            "source_end_us": second.source_end_us + 1,
            "output_start_us": second.output_start_us + 1,
            "output_end_us": second.output_end_us + 1,
        }
    )
    assert len(hero_caption_pieces([first, later])) == 2


def test_aliases_store_one_locale_and_cache_rejects_each_identity_change() -> None:
    assert _stored_locale(_locale_backend("ja-JP", "ja")) == "ja"
    assert _stored_locale(_locale_backend("ja", "ja")) == "ja"
    assert _stored_locale(_locale_backend("fr", "fr")) == "fr-FR"
    document, inputs, aligner = _built()
    _require_fresh_alignment(document, inputs, _candidate(), _review(), "rough-1", aligner)
    mutations = {
        "binding_sha256": "",
        "locale": "",
        "model_revision": "9.9.9",
        "checkpoint_sha256": _SHA,
        "manifest_sha256": _SHA,
    }
    for field, value in mutations.items():
        changed = document.model_copy(update={field: value})
        with pytest.raises(MediaError):
            _require_fresh_alignment(changed, inputs, _candidate(), _review(), "rough-1", aligner)
    production = document.model_copy(
        update={
            "model_name": "WAV2VEC2_ASR_BASE_960H",
            "model_revision": "",
            "checkpoint_sha256": "",
            "manifest_sha256": "",
            "whisperx_version": "",
        }
    )
    with pytest.raises(MediaError, match="incomplete"):
        _require_fresh_alignment(production, inputs, _candidate(), _review(), "rough-1", None)
    for field, value in (
        ("transcript_sha256", _SHA),
        ("asr_audio_sha256", _SHA),
        ("time_map_sha256", _SHA),
    ):
        changed = document.model_copy(update={field: value})
        with pytest.raises(MediaError):
            _require_fresh_alignment(changed, inputs, _candidate(), _review(), "rough-1", aligner)
    moved = _Inputs(_Pair(inputs.pair.transcript, _TRANSCRIPT, _SHA), _ASR)
    with pytest.raises(MediaError):
        _require_fresh_alignment(document, moved, _candidate(), _review(), "rough-1", aligner)


def _locale_backend(locale: str, language: str) -> FakeForcedAlignment:
    backend = FakeForcedAlignment()
    backend.locale = locale  # type: ignore[attr-defined]
    backend.language_code = language  # type: ignore[attr-defined]
    return backend


def _facts(tmp_path: Path, document: ForcedAlignmentDocument, **extra: object) -> object:
    workspace = SourceWorkspace(tmp_path, PROJECT_ID, SOURCE_ID)
    path = workspace.hero_alignment_file(document.candidate_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document.model_dump_json(), encoding="utf-8")

    class _Facts:
        pass

    facts = _Facts()
    facts.workspace = workspace  # type: ignore[attr-defined]
    facts.candidate_id = document.candidate_id  # type: ignore[attr-defined]
    facts.narration_sha256 = None  # type: ignore[attr-defined]
    facts.narration_provider_id = None  # type: ignore[attr-defined]
    facts.narration_requested = False  # type: ignore[attr-defined]
    for key, value in extra.items():
        setattr(facts, key, value)
    return facts


def test_final_review_reads_the_bound_locale_and_narration(tmp_path: Path) -> None:
    document, _inputs, _aligner = _built()
    french = document.model_copy(update={"locale": "fr-FR", "normalized_language": "fr"})
    card = language_evidence(_facts(tmp_path / "fr", french))
    assert card["requested_locale"] == "fr-FR"
    assert card["normalized_language"] == "fr"
    assert card["requested_locale"] != "en-US"
    japanese = document.model_copy(update={"locale": "ja", "normalized_language": "ja"})
    assert language_evidence(_facts(tmp_path / "ja", japanese))["requested_locale"] == "ja"
    english = language_evidence(_facts(tmp_path / "en", document))
    assert english["requested_locale"] == "en-US"
    assert english["narration_status"] == "narration_not_requested"
    requested = language_evidence(_facts(tmp_path / "ask", document, narration_requested=True))
    assert requested["narration_status"] == "missing"
    recorded = language_evidence(
        _facts(
            tmp_path / "voice",
            document,
            narration_sha256=_SHA,
            narration_provider_id="voicestudio",
            narration_engine_id="kittentts",
            narration_model_id="KittenML/kitten-tts-mini-0.8",
            narration_model_revision="c02725660cea441db4c383af69f1f26f5cd00947",
            narration_voice_id="expr-voice-2-f",
            narration_model_license="allowed",
        )
    )
    assert recorded["narration_status"] == "recorded"
    assert recorded["narration_voice"] == "expr-voice-2-f"
    assert recorded["narration_license"] == "allowed"
    stale_voice = language_evidence(_facts(tmp_path / "stale-voice", document, narration_sha256=_SHA))
    assert stale_voice["narration_status"] == "stale_narration"
    broken = _facts(tmp_path / "broken", document)
    path = broken.workspace.hero_alignment_file(document.candidate_id)  # type: ignore[attr-defined]
    path.write_text("{", encoding="utf-8")
    assert language_evidence(broken)["alignment_status"] == "stale_alignment"
    changed = document.model_copy(
        update={
            "binding_sha256": "ab" * 32,
            "locale": "fr-FR",
            "normalized_language": "fr",
        }
    )
    other = language_evidence(_facts(tmp_path / "other", changed))
    assert other["requested_locale"] == "fr-FR"
    assert other["alignment_status"] == "stale_alignment"
    assert evidence_sha(card) != evidence_sha(other)


def evidence_sha(card: dict[str, str]) -> str:
    from clipforge.review.final_gate import evidence_sha256

    return evidence_sha256(card)


def test_rejected_and_changes_requested_boards_keep_language_facts(tmp_path: Path) -> None:
    world = _world(tmp_path)
    approved = final_board(world.database, world.work, "source-1", "cand-1")
    assert approved["effective_decision"] == "approved"
    assert approved["requested_locale"] == "missing"
    assert approved["alignment_status"] == "stale_alignment"
    assert "alignment_manifest" in approved
    assert "narration_status" in approved
    from clipforge.review.final_gate import capture_final_decision

    capture_final_decision(
        world.database,
        world.work,
        "source-1",
        "cand-1",
        decision="rejected",
        reviewer_id="ada",
        notes="no",
    )
    rejected = final_board(world.database, world.work, "source-1", "cand-1")
    assert rejected["effective_decision"] == "rejected"
    assert "final_approval_rejected" in rejected["blockers"]
    changes_world = _world(tmp_path / "changes")
    capture_final_decision(
        changes_world.database,
        changes_world.work,
        "source-1",
        "cand-1",
        decision="changes_requested",
        reviewer_id="ada",
        notes="again",
    )
    changes = final_board(changes_world.database, changes_world.work, "source-1", "cand-1")
    assert changes["effective_decision"] == "changes_requested"
    assert "final_approval_changes_requested" in changes["blockers"]


def test_review_page_does_not_invent_english_or_html() -> None:
    root = Path(__file__).parents[1]
    script = (root / "src/clipforge/review/static/final-review.js").read_text(encoding="utf-8")
    page = (root / "src/clipforge/review/static/final-review.html").read_text(encoding="utf-8")
    hero = (root / "apps/renderer/src/hero/HeroDraft.tsx").read_text(encoding="utf-8")
    advanced = (root / "apps/renderer/src/hero/AdvancedHeroDraft.tsx").read_text(encoding="utf-8")
    assert "controls" in page
    assert "autoplay = false" in script
    assert 'payload.requested_locale || "en-US"' not in script
    assert "innerHTML" not in script
    assert "CaptionPlate" in hero
    assert "CaptionPlate" in advanced
    assert '.join(" ")' not in advanced


def test_stored_speech_record_is_not_a_tone() -> None:
    for locale in ("en-US", "fr-FR", "ja"):
        smoked = speech_smoke_manifest(locale)
        if not smoked:
            assert provider_for(locale).live_status != "verified_live"
    evidence = Path(__file__).parents[1] / "src/clipforge/language/speech_evidence.json"
    if not evidence.is_file():
        return
    import json

    document = json.loads(evidence.read_text(encoding="utf-8"))
    assert document["schema_version"] == "1.0.0"
    for row in document["records"]:
        assert row["audio_class"] in {"recorded_speech", "tts_speech"}
        assert row["token_count"] >= 3
        assert row["audio_filename"]
        assert ".." not in row["audio_filename"]
