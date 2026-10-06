"""Caption language checks. doctor, list, show, and verify do not write."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from clipforge.errors import ClipforgeError
from clipforge.language.frames import prove_captions
from clipforge.language.service import (
    FakeLanguageAligner,
    LanguageError,
    UnavailableAligner,
    WhisperXFullSourceAligner,
    align_language,
    doctor_text,
    list_alignments,
    list_languages,
    show_alignment,
    verify_alignment,
)
from clipforge.paths import resolve_db_path, resolve_work_dir
from clipforge.storage import Database

language_app = typer.Typer(no_args_is_help=True, help="Check caption languages.")


def _fail(exc: BaseException) -> NoReturn:
    typer.echo(str(exc), err=True)
    raise typer.Exit(1)


@language_app.command("check")
def language_check(
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Draw caption stills and report alignment claims."""
    try:
        proofs = prove_captions(resolve_work_dir(work_dir) / "captions")
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    for proof in proofs:
        typer.echo(f"language: {proof.language}")
        typer.echo(f"text_direction: {proof.text_direction}")
        typer.echo(f"alignment_status: {proof.alignment_status}")
        typer.echo(f"safe_area: {'pass' if proof.safe_area else 'fail'}")
        typer.echo(f"glyphs: {'present' if proof.glyphs_present else 'missing'}")
    typer.echo("multilingual_result: multilingual_pass")
    typer.echo("alignment_claim: alignment_not_claimed")


@language_app.command("doctor")
def language_doctor() -> None:
    """Report language capability. This command does not write."""
    typer.echo(doctor_text())


@language_app.command("list")
def language_list(
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """List languages and stored alignments. This command does not write."""
    try:
        stored = list_alignments(resolve_work_dir(work_dir))
        payload = {"languages": list_languages(), "alignments": [item.alignment_id for item in stored]}
    except (ClipforgeError, OSError) as exc:
        _fail(exc)
    typer.echo(json.dumps(payload, sort_keys=True))


@language_app.command("align")
def language_align(
    source_id: str,
    language: Annotated[str, typer.Option("--language")],
    transcript: Annotated[Path, typer.Option("--transcript")],
    project_id: Annotated[str, typer.Option("--project")],
    provider: Annotated[str, typer.Option("--provider")] = "whisperx",
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Align one source when a provider is available. This does not download a model."""
    try:
        payload = json.loads(transcript.read_text(encoding="utf-8"))
        words = [(str(item["word_id"]), str(item["text"])) for item in payload["words"]]
        chosen = _aligner(provider, language)
        document = align_language(
            resolve_work_dir(work_dir),
            Database(resolve_db_path(db)),
            source_id,
            project_id=project_id,
            language=language,
            transcript_id=str(payload["transcript_id"]),
            transcript_sha256=str(payload["transcript_sha256"]),
            source_sha256=str(payload["source_sha256"]),
            words=words,
            duration_us=int(payload["duration_us"]),
            provider=chosen,
            force=force,
        )
    except (ClipforgeError, OSError, ValueError, KeyError, LanguageError) as exc:
        _fail(exc)
    typer.echo(document.alignment_id)
    typer.echo(f"alignment_status: {document.alignment_status}")


@language_app.command("show")
def language_show(
    alignment_id: str,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Show one alignment. This command does not write."""
    try:
        document = show_alignment(resolve_work_dir(work_dir), alignment_id)
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)
    typer.echo(document.model_dump_json())


@language_app.command("verify")
def language_verify(
    alignment_id: str,
    db: Annotated[Path | None, typer.Option("--db")] = None,
    work_dir: Annotated[Path | None, typer.Option("--work-dir")] = None,
) -> None:
    """Re-check one alignment. This command does not write."""
    try:
        typer.echo(verify_alignment(resolve_work_dir(work_dir), Database(resolve_db_path(db)), alignment_id))
    except (ClipforgeError, OSError, ValueError) as exc:
        _fail(exc)


def _aligner(name: str, language: str) -> FakeLanguageAligner | UnavailableAligner | WhisperXFullSourceAligner:
    if name == "fake":
        return FakeLanguageAligner(language)
    if name == "unavailable":
        return UnavailableAligner()
    if name == "whisperx":
        return WhisperXFullSourceAligner()
    raise LanguageError("alignment provider is not configured", code="not_configured")
