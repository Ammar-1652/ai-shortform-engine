"""Exercise the worker's real pre-browser gate with altered service inputs."""

from __future__ import annotations

import json
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

from clipforge.errors import MediaError
from clipforge.hero.render_authorization import authorize_render_candidate
from clipforge.hero.render_checkpoint import renderer_dependency_sha256
from clipforge.media.workspace import SourceWorkspace
from clipforge.schemas.advanced import AdvancedHeroRenderInput, advanced_fingerprint

_HASH = sha256(b"authorization-test-source").hexdigest()
_SCRIPT = Path(__file__).resolve().parents[1] / "apps/renderer/scripts/render-authorization.mjs"


def _run_gate(batch: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "node",
            "--input-type=module",
            "--eval",
            'import {readFileSync} from "node:fs"; '
            "const {validateRenderAuthorization} = await import(process.argv[1]); "
            'validateRenderAuthorization(process.argv[2], JSON.parse(readFileSync(process.argv[2], "utf8")));',
            _SCRIPT.as_uri(),
            str(batch),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


@pytest.fixture
def authorized(tmp_path: Path) -> tuple[Path, SourceWorkspace, AdvancedHeroRenderInput]:
    workspace = SourceWorkspace(tmp_path, "project-test", "source-test")
    run = tmp_path / "service-run"
    (run / "staging").mkdir(parents=True)
    (run / "staging/analysis.mp4").write_bytes(b"source picture fixture")
    (run / "staging/asr.flac").write_bytes(b"source speech fixture")
    render_input = AdvancedHeroRenderInput(
        candidate_id="candidate-test",
        advanced_set_id="set-test",
        duration_in_frames=125,
        reframing_strategy="contain",
        reframing_config_sha256=_HASH,
        profile_fingerprint=_HASH,
        alignment_sha256=_HASH,
        hero_plan_sha256=_HASH,
        advanced_plan_sha256=_HASH,
        source_sha256=_HASH,
    )
    output = run / "candidates/candidate-test/advanced.mp4"
    payload = {
        "items": [
            {
                "outputPath": str(output),
                "h264Crf": 18,
                "input_sha256": advanced_fingerprint(render_input.model_dump(mode="json")),
                "input": render_input.model_dump(mode="json"),
            }
        ]
    }
    (run / "batch-input.json").write_text(json.dumps(payload), encoding="utf-8")
    (run / "batch.json").write_text(json.dumps(payload), encoding="utf-8")
    authorize_render_candidate(
        workspace=workspace,
        root=tmp_path,
        run_dir=run,
        render_input=render_input,
        output=output,
        dependency_sha256=renderer_dependency_sha256(),
        job_id="job-test",
        parent_artifact_id="hero-test",
        actor="test",
    )
    return run, workspace, render_input


def test_service_batch_and_checkpoint_units_are_authorized(
    authorized: tuple[Path, SourceWorkspace, AdvancedHeroRenderInput],
) -> None:
    run, _workspace, _input = authorized
    assert (run / "candidates/candidate-test/authorization.json").is_file()
    batch = run / "batch.json"
    result = _run_gate(batch)
    assert result.returncode == 0, result.stderr
    payload = json.loads(batch.read_text())
    for mode, frames, name in (
        ("video", [0, 119], "video-000000.partial.mp4"),
        ("video", [120, 124], "video-000001.partial.mp4"),
        ("audio", [0, 124], "audio.partial.wav"),
    ):
        payload["items"][0].update(
            renderMode=mode,
            frameRange=frames,
            outputPath=str(run / "candidates/candidate-test/checkpoints" / name),
        )
        batch.write_text(json.dumps(payload))
        result = _run_gate(batch)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        "input",
        "digest",
        "canonical",
        "staged",
        "output",
        "range",
        "missing",
        "symlink",
        "copy",
        "copy_chunk",
        "dependency",
        "duplicate_canonical",
    ],
)
def test_worker_rejects_stale_or_copied_service_work(
    authorized: tuple[Path, SourceWorkspace, AdvancedHeroRenderInput],
    mutation: str,
) -> None:
    run, _workspace, _input = authorized
    batch = run / "batch.json"
    payload = json.loads(batch.read_text())
    if mutation == "input":
        # Keep the declared digest: checking only the declared string would accept this.
        payload["items"][0]["input"]["source_gain_db"] = -12
    elif mutation == "digest":
        payload["items"][0]["input_sha256"] = sha256(b"other").hexdigest()
    elif mutation == "canonical":
        (run / "batch-input.json").write_text("{}")
    elif mutation == "staged":
        (run / "staging/asr.flac").write_bytes(b"different audio")
    elif mutation == "output":
        payload["items"][0]["outputPath"] = str(run / "unreviewed.mp4")
    elif mutation == "range":
        payload["items"][0].update(renderMode="video", frameRange=[1, 119])
    elif mutation == "missing":
        (run / "authorization.json").rename(run / "preserved-authorization.json")
    elif mutation == "symlink":
        path = run / "staging/asr.flac"
        path.rename(run / "speech-copy.flac")
        path.symlink_to(run / "speech-copy.flac")
    elif mutation == "dependency":
        receipt = run / "authorization.json"
        document = json.loads(receipt.read_text(encoding="utf-8"))
        document["renderer_dependency_sha256"] = _HASH
        receipt.write_text(json.dumps(document), encoding="utf-8")
    elif mutation == "duplicate_canonical":
        canonical = run / "batch-input.json"
        document = json.loads(canonical.read_text(encoding="utf-8"))
        document["items"].append(document["items"][0])
        canonical.write_text(json.dumps(document), encoding="utf-8")
        receipt = run / "authorization.json"
        authorization = json.loads(receipt.read_text(encoding="utf-8"))
        authorization["batch_sha256"] = sha256(canonical.read_bytes()).hexdigest()
        receipt.write_text(json.dumps(authorization), encoding="utf-8")
    elif mutation in {"copy", "copy_chunk"}:
        copied = run.parent / "copied-run"
        shutil.copytree(run, copied)
        batch = copied / "batch.json"
        payload["items"][0]["outputPath"] = str(copied / "candidates/candidate-test/advanced.mp4")
        if mutation == "copy_chunk":
            payload["items"][0].update(
                renderMode="video",
                frameRange=[0, 119],
                outputPath=str(copied / "candidates/candidate-test/checkpoints/video-000000.partial.mp4"),
            )
    batch.write_text(json.dumps(payload))
    assert _run_gate(batch).returncode != 0


def test_authorization_refuses_invented_parent_input(
    authorized: tuple[Path, SourceWorkspace, AdvancedHeroRenderInput],
) -> None:
    run, workspace, render_input = authorized
    changed = render_input.model_copy(update={"alignment_sha256": sha256(b"invented").hexdigest()})
    with pytest.raises(MediaError, match="canonical batch"):
        authorize_render_candidate(
            workspace=workspace,
            root=workspace.root,
            run_dir=run,
            render_input=changed,
            output=run / "candidates/candidate-test/advanced.mp4",
            dependency_sha256=_HASH,
            job_id="job-test",
            parent_artifact_id="hero-test",
            actor="test",
        )


def test_service_refuses_ambiguous_canonical_candidate(
    authorized: tuple[Path, SourceWorkspace, AdvancedHeroRenderInput],
) -> None:
    run, workspace, render_input = authorized
    canonical = run / "batch-input.json"
    document = json.loads(canonical.read_text(encoding="utf-8"))
    document["items"].append(document["items"][0])
    canonical.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(MediaError, match="batch input is missing or invalid"):
        authorize_render_candidate(
            workspace=workspace,
            root=workspace.root,
            run_dir=run,
            render_input=render_input,
            output=run / "candidates/candidate-test/advanced.mp4",
            dependency_sha256=renderer_dependency_sha256(),
            job_id="job-test",
            parent_artifact_id="hero-test",
            actor="test",
        )


def test_second_candidate_preserves_first_staged_audio_receipt(
    authorized: tuple[Path, SourceWorkspace, AdvancedHeroRenderInput],
) -> None:
    run, workspace, first_input = authorized
    first_receipt = run / "candidates/candidate-test/authorization.json"
    original = first_receipt.read_bytes()
    second_input = first_input.model_copy(update={"candidate_id": "candidate-second"})
    second_output = run / "candidates/candidate-second/advanced.mp4"
    canonical = run / "batch-input.json"
    document = json.loads(canonical.read_text(encoding="utf-8"))
    document["items"].append(
        {
            "outputPath": str(second_output),
            "h264Crf": 18,
            "input_sha256": advanced_fingerprint(second_input.model_dump(mode="json")),
            "input": second_input.model_dump(mode="json"),
        }
    )
    canonical.write_text(json.dumps(document), encoding="utf-8")
    (run / "staging/asr.flac").write_bytes(b"second candidate speech")
    authorize_render_candidate(
        workspace=workspace,
        root=workspace.root,
        run_dir=run,
        render_input=second_input,
        output=second_output,
        dependency_sha256=renderer_dependency_sha256(),
        job_id="job-test",
        parent_artifact_id="hero-test",
        actor="test",
    )
    assert first_receipt.read_bytes() == original
    second = json.loads((run / "candidates/candidate-second/authorization.json").read_text())
    assert second["items"][0]["staged_sha256"]["asr.flac"] == sha256(b"second candidate speech").hexdigest()
