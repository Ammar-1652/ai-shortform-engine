"""Validate and remap a source-grounded Advanced Hero editorial arc."""

from __future__ import annotations

import uuid
from pathlib import Path

from clipforge.errors import MediaError
from clipforge.hero.alignment import alignment_binding_sha256
from clipforge.media.hashing import sha256_file
from clipforge.preview.timing import frame_at_or_after
from clipforge.schemas.arc import EditorialArcDocument
from clipforge.schemas.direction import (
    DirectionAssetPlacement,
    DirectionDocument,
    DirectionEvidence,
    DirectionMotionGraphic,
    DirectionOption,
)
from clipforge.schemas.editorial import OutputInterval
from clipforge.schemas.hero import AlignedWord, ForcedAlignmentDocument, HeroPlanDocument
from clipforge.schemas.time import TimeMapDocument, digest_time_map
from clipforge.timeline import FrameRate

_NAMESPACE = uuid.UUID("2d1c8f3f-3c53-4b7a-a01f-7c3a9d45c1e2")


def load_editorial_arc(path: Path) -> tuple[EditorialArcDocument, str]:
    """Load an immutable operator arc and return its file digest."""
    if path.is_symlink() or not path.is_file():
        raise MediaError("editorial arc file must be a regular, non-symlink JSON file")
    try:
        document = EditorialArcDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise MediaError(f"invalid editorial arc file: {exc}") from exc
    # Like every other persisted Clipforge contract, the binding is the bytes
    # that were actually reviewed.  Canonicalization happens when the service
    # publishes the immutable work-root copy; whitespace changes to that copy
    # must still invalidate a plan rather than being silently accepted.
    return document, sha256_file(path)


def validate_editorial_arc(
    arc: EditorialArcDocument,
    *,
    source_sha256: str,
    hero_plan: HeroPlanDocument,
    hero_plan_sha256: str,
    alignment: ForcedAlignmentDocument,
    alignment_sha256: str,
) -> None:
    """Bind an arc to the current Hero evidence and complete forced words."""
    if arc.source_sha256 != source_sha256:
        raise MediaError("editorial arc is stale against the current source")
    if arc.hero_plan_sha256 != hero_plan_sha256:
        raise MediaError("editorial arc is stale against the current Hero plan")
    if arc.alignment_sha256 != alignment_sha256:
        raise MediaError("editorial arc is stale against the current alignment")
    if (arc.project_id, arc.source_asset_id, arc.candidate_id) != (
        alignment.project_id,
        alignment.source_asset_id,
        alignment.candidate_id,
    ):
        raise MediaError("editorial arc identity differs from its alignment")
    for mapped_segment in arc.time_map.segments:
        if not any(
            parent.source_start_us <= mapped_segment.source_start_us
            and mapped_segment.source_end_us <= parent.source_end_us
            for parent in hero_plan.edit_plan.time_map.segments
        ):
            raise MediaError("editorial arc segment lies outside the approved Hero range")
    by_id = {word.word_id: word for word in alignment.words}
    positions = {word.word_id: index for index, word in enumerate(alignment.words)}
    punctuation = frozenset(".?!:\u3002\uff1f\uff01")
    for arc_segment in arc.segments:
        if arc_segment.claim_closure != "complete":
            raise MediaError(
                f"editorial arc {arc_segment.segment_id} requires claim-closure review before rendering"
            )
        covered = [
            word.word_id
            for word in alignment.words
            if arc_segment.source_start_us <= word.source_start_us
            and word.source_end_us <= arc_segment.source_end_us
        ]
        if covered != arc_segment.word_ids:
            raise MediaError("editorial arc must declare every forced word in its kept range")
        for boundary in (arc_segment.source_start_us, arc_segment.source_end_us):
            if any(word.source_start_us < boundary < word.source_end_us for word in alignment.words):
                raise MediaError("editorial arc cut falls inside a forced word")
        indexes = [positions.get(word_id, -1) for word_id in arc_segment.word_ids]
        if any(index < 0 for index in indexes):
            raise MediaError("editorial arc names an unknown forced word")
        if indexes != list(range(min(indexes), max(indexes) + 1)):
            raise MediaError("editorial arc words must be contiguous in the approved transcript")
        last_word = alignment.words[indexes[-1]]
        if not arc_segment.continuation and not last_word.text.rstrip().endswith(tuple(punctuation)):
            raise MediaError(
                "editorial arc beat must end at source punctuation or be explicitly marked continuation"
            )
        first_index = indexes[0]
        if first_index > 0:
            previous = alignment.words[first_index - 1]
            first = alignment.words[first_index]
            gap_us = first.source_start_us - previous.source_end_us
            if (
                gap_us < 100_000
                and not previous.text.rstrip().endswith(tuple(punctuation))
                and not arc_segment.continuation
            ):
                raise MediaError(
                    "editorial arc segment starts inside a sentence; keep its setup or "
                    "choose a sentence boundary"
                )
        for word_id in arc_segment.word_ids:
            word = by_id[word_id]
            if not (
                arc_segment.source_start_us <= word.source_start_us
                and word.source_end_us <= arc_segment.source_end_us
            ):
                raise MediaError("editorial arc segment does not contain its declared forced words")


def remap_alignment(
    alignment: ForcedAlignmentDocument,
    arc: EditorialArcDocument,
    *,
    source_sha256: str,
) -> ForcedAlignmentDocument:
    """Re-map retained forced words onto the arc's ordered output clock."""
    by_id = {word.word_id: word for word in alignment.words}
    time_map = arc.time_map.to_time_map()
    frame_count = time_map.output_frame_count(FrameRate(30, 1))
    words: list[AlignedWord] = []
    for segment_index, arc_segment in enumerate(arc.segments):
        for word_id in arc_segment.word_ids:
            original = by_id[word_id]
            output_start = time_map.source_to_output(original.source_start_us)
            output_end = time_map.source_to_output(original.source_end_us)
            start_frame = frame_at_or_after(output_start, frame_count)
            end_frame = frame_at_or_after(output_end, frame_count)
            if start_frame >= end_frame:
                end_frame = min(frame_count, start_frame + 1)
            if start_frame >= frame_count or end_frame <= start_frame:
                raise MediaError(f"editorial arc word {word_id} has no output frame")
            words.append(
                original.model_copy(
                    update={
                        "output_start_us": output_start,
                        "output_end_us": output_end,
                        "output_start_frame": start_frame,
                        "output_end_frame_exclusive": end_frame,
                        "segment_index": segment_index,
                    }
                )
            )
    provider = "fake" if alignment.model_name == "fake-forced-align-v1" else "whisperx"
    binding = alignment_binding_sha256(
        alignment_recipe=alignment.alignment_recipe,
        asr_audio_sha256=alignment.asr_audio_sha256,
        candidate_id=alignment.candidate_id,
        checkpoint_sha256=alignment.checkpoint_sha256,
        locale=alignment.locale,
        manifest_sha256=alignment.manifest_sha256,
        model_id=alignment.model_name,
        model_revision=alignment.model_revision,
        normalized_language=alignment.normalized_language,
        provider_name=provider,
        provider_version=alignment.whisperx_version,
        source_asset_id=alignment.source_asset_id,
        source_sha256=source_sha256,
        time_map_sha256=digest_time_map(arc.time_map),
        transcript_language=alignment.normalized_language,
        transcript_sha256=alignment.transcript_sha256,
    )
    return ForcedAlignmentDocument.model_validate(
        {
            **alignment.model_dump(mode="json"),
            "alignment_id": str(uuid.uuid5(_NAMESPACE, f"{alignment.alignment_id}|{arc.arc_id}")),
            "time_map_sha256": digest_time_map(arc.time_map),
            "words": [word.model_dump(mode="json") for word in words],
            "binding_sha256": binding,
        }
    )


def remap_direction_intervals(
    direction: DirectionDocument,
    source_alignment: ForcedAlignmentDocument,
    output_alignment: ForcedAlignmentDocument,
    source_time_map: TimeMapDocument,
    output_time_map: TimeMapDocument,
) -> DirectionDocument:
    """Move reviewed direction intervals onto a recut output clock.

    Direction evidence remains bound to the original word ids.  Only its
    derived output intervals move, so a cut/reorder cannot leave a title,
    graphic, B-roll, or SFX cue behind at the old timestamp.
    """
    source_words = {word.word_id: word for word in source_alignment.words}
    output_words = {word.word_id: word for word in output_alignment.words}
    option_updates: list[DirectionOption] = []
    for option in direction.options:
        if option.option_id != direction.selected_option_id:
            # Alternatives are historical proposals, not rendered choices.
            # A removed word in an unselected option must not block a recut.
            option_updates.append(option)
            continue
        evidence_by_id = {item.evidence_id: item for item in option.evidence}

        beats = []
        for beat in option.beats:
            interval = _direction_interval(evidence_by_id, beat.evidence_ids, source_words, output_words)
            if beat.output_start_us is not None and beat.output_end_us is not None:
                interval = remap_output_interval(
                    OutputInterval(
                        output_start_us=beat.output_start_us,
                        output_end_us=beat.output_end_us,
                    ),
                    source_time_map,
                    output_time_map,
                )
            beats.append(
                beat.model_copy(
                    update={
                        "output_start_us": interval.output_start_us,
                        "output_end_us": interval.output_end_us,
                    }
                )
            )
        placements: list[DirectionAssetPlacement] = []
        for placement in option.asset_placements:
            placements.append(
                placement.model_copy(
                    update={
                        "interval": remap_output_interval(placement.interval, source_time_map, output_time_map)
                    }
                )
            )
        graphics: list[DirectionMotionGraphic] = []
        for graphic in option.motion_graphics:
            graphics.append(
                graphic.model_copy(
                    update={
                        "interval": remap_output_interval(graphic.interval, source_time_map, output_time_map)
                    }
                )
            )
        context_line = option.context_line
        if context_line is not None:
            # The upper context label intentionally spans the complete new
            # program. It is not a source-timed caption, so remapping it
            # through a jump-cut interval would either fail at a discontinuity
            # or leave the line stale after a recut.
            context_line = context_line.model_copy(
                update={
                    "interval": OutputInterval(
                        output_start_us=0,
                        output_end_us=output_time_map.to_time_map().total_output_duration(),
                    )
                }
            )
        option_updates.append(
            DirectionOption.model_validate(
                {
                    **option.model_dump(mode="json"),
                    "beats": beats,
                    "asset_placements": placements,
                    "motion_graphics": graphics,
                    "context_line": None if context_line is None else context_line.model_dump(mode="json"),
                    "source_native_text": [
                        item.model_copy(
                            update={
                                "interval": remap_output_interval(
                                    item.interval, source_time_map, output_time_map
                                )
                            }
                        ).model_dump(mode="json")
                        for item in option.source_native_text
                    ],
                }
            )
        )
    return DirectionDocument.model_validate({**direction.model_dump(mode="json"), "options": option_updates})


def remap_output_interval(
    interval: OutputInterval,
    source_time_map: TimeMapDocument,
    output_time_map: TimeMapDocument,
) -> OutputInterval:
    """Preserve a reviewed effect's duration and offsets through retained footage.

    A cue crossing a source discontinuity or deleted/reordered range is not
    stretched, split, or guessed. The operator must explicitly retime it.
    """
    parent_map = source_time_map.to_time_map()
    target_map = output_time_map.to_time_map()
    parent = next(
        (
            segment
            for segment in parent_map.segments
            if segment.output_start_us <= interval.output_start_us
            and interval.output_end_us <= segment.output_end_us
        ),
        None,
    )
    if parent is None:
        raise MediaError("direction interval crosses a source cut; provide explicit recut timing")
    source_start = parent_map.output_to_source(interval.output_start_us)
    source_end = (
        parent.source_end_us
        if interval.output_end_us == parent.output_end_us
        else parent_map.output_to_source(interval.output_end_us)
    )
    if not any(
        segment.source_start_us <= source_start and source_end <= segment.source_end_us
        for segment in target_map.segments
    ):
        raise MediaError("direction interval crosses removed footage; provide explicit recut timing")
    return OutputInterval(
        output_start_us=target_map.source_to_output(source_start),
        output_end_us=target_map.source_to_output(source_end),
    )


def _direction_interval(
    evidence_by_id: dict[str, DirectionEvidence],
    evidence_ids: list[str],
    source_words: dict[str, AlignedWord],
    output_words: dict[str, AlignedWord],
) -> OutputInterval:
    word_ids = [
        word_id for evidence_id in evidence_ids for word_id in evidence_by_id[evidence_id].source_word_ids
    ]
    if not word_ids or any(word_id not in source_words for word_id in word_ids):
        raise MediaError("direction evidence names a word absent from the approved alignment")
    if any(word_id not in output_words for word_id in word_ids):
        raise MediaError("direction evidence names a word absent from the editorial arc")
    words = [output_words[word_id] for word_id in word_ids]
    return OutputInterval(
        output_start_us=min(word.output_start_us for word in words),
        output_end_us=max(word.output_end_us for word in words),
    )
