# ADR 0112: Codex subtitle review and source-supported emotion annotations

- Status: Accepted
- Date: 2026-10-27

## Context

Forced alignment gives reliable timing after the selected clip is aligned. It
does not prove that an ASR phrase is grammatical, that it means the right thing
in context, or that a sensitive quotation is written correctly. The previous
caption evidence path treated the absence of a reviewed speech inventory as a
generic blocker, while the operator role already assigns editorial judgment to
Codex.

## Decision

Codex is the subtitle reviewer for candidate and Advanced Hero work. For every
retained speech interval Codex must review:

1. grammatical meaning;
2. meaning in the actual source context;
3. source wording, punctuation, and numbers;
4. sensitive text such as Quran, quotations, names, and factual claims against
   a reliable source when needed;
5. clear source-supported emotions, which may receive an allowlisted emoji
   annotation beside the words.

The typed `TarteelSpeechReview` contract remains backward compatible and accepts
`campaign="generic"` for this Codex workflow. Generic reviews are stored under
`editorial/speech-reviews/<source>/<candidate>/speech-review.json` and are
validated with `clipforge editorial captions review`. The record binds source,
ASR, transcript, alignment, and selected TimeMap facts. Emojis are supplemental
caption metadata and cannot replace spoken words. Online verification is used
only for the evidence lookup and its URL or hashed local snapshot is recorded;
rendering remains offline.

This review can make decoded caption evidence complete for QA. It never creates
human playback approval, final delivery approval, or external publication.

## Consequences

- Generic campaigns can use the same source-bound speech evidence gate as
  Tarteel without putting generic files in the Tarteel campaign directory.
- Codex must inspect and correct captions before planning a clean Advanced Hero
  render; a missing or stale review remains `insufficient_evidence`.
- Sensitive text has an auditable verification trail. A source URL alone is not
  a claim that the source is authoritative; the review note identifies why it
  was selected.
- Existing Tarteel sidecars and old artifacts remain readable and immutable.
- Human final review remains the only publication approval.
