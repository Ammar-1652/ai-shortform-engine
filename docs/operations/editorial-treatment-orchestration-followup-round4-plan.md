# Editorial treatment orchestration follow-up round 4

**Audit date:** 2026-10-27  
**Audited head:** `cda133d7ece81760bd6e9736c7fc8777f61e86fa`  
**Branch:** `round-36-editorial-knowledge-engine`  
**PR:** [#38](https://github.com/Ammar-1652/ai-shortform-engine/pull/38)  
**Base:** `origin/main` `989bf5d6ec27878d46505dc09becedfc848cd749`  
**Status:** `REVIEW OPEN — R3 NOT COMPLETE`

This is an audit and repair plan. It does not change the approval model and it
does not turn a draft render into a final delivery.

## Audit conclusion

The R3 code slice is substantially present and the exact audited head passed
local validation (`964 passed, 2 skipped, 18 deselected`, 18 browser tests, 64
renderer tests, schema/Ruff/mypy/renderer checks, and doctor). The existing
provider-backed Advanced Hero packet is real and its treatment/audio evidence
is hash-bound. The separate Codex-reviewed draft is also real and visibly
renders the `🤩` annotation.

The execution is not complete because the plan’s strongest acceptance criteria
are still open, and because the audit found code contracts that cannot yet
represent all of the promised behavior. The old round-3 ledger also records
`4e372db` as its reviewed head even though the current branch is `cda133d`; the
ledger must not be treated as exact-head evidence until corrected.

## What landed correctly

| area | audit result | evidence |
|---|---|---|
| Direction revision and provider binding | Partially landed and exercised | `revise-direction`, immutable direction artifacts, provider/license/byte checks, and revision tests exist; the real packet consumed the revised direction. |
| Visual asset observations | Partially landed | `TreatmentAssetObservation` sidecars decode and hash selected media spans and are loaded into the treatment evidence bundle. |
| Audio evidence | Partially landed | Aligned-word overlap, decoded RMS comparison, ducking, loudness, and true peak are recorded for the real packet. |
| Treatment evidence bundle | Landed for the exercised path | Bundle is persisted and loaded by QA/delivery preflight with direction/treatment hashes. |
| Shared policy ownership | Landed for the exercised path | CLI, Advanced planning, QA, and delivery preflight call the shared evaluator; multiplicity-aware event ownership is tested. |
| Codex generic speech review | Landed as a draft-only path | `editorial captions review` stores a generic, hash-bound speech inventory; Advanced render input carries its digest and the draft caption evidence is complete. |
| Emoji rendering | Landed for the exercised path | `CaptionPlate` renders the allowlisted emoji and the decoded frame shows `🤩` beside the caption. |
| Deterministic TimeMap mapping | Landed for the emoji path | Unit coverage proves source-clock emotion annotations map through a jump cut into output-clock captions. |

## Remaining blockers and repair plan

### R4-1 — Complete the required real proof and external gates

**Observed problem:** R3-6 uses the authorized Jingle Jared/Rebel Audio
campaign source. The plan explicitly requires a separate authorized generic
non-campaign source for the generic provider proof. The campaign source’s
eligibility is `unknown`, so the packet remains draft-only. The current PR’s
self-hosted CI check is queued because the repository has zero registered
`clipforge-local` runners. No human audio/muted playback receipt or local
delivery package exists for the new Codex-reviewed draft.

**Repair steps:**

1. In an ignored work root, ingest one authorized non-campaign source with a
   persisted `campaign_provided` or provider rights record and verified bytes.
2. Acquire one relevant visual asset and one SFX through the existing provider
   boundaries. Preserve response, selection, acquisition, license, registered
   byte, and observation hashes.
3. Create a Codex speech review for every retained interval, including any
   corrections and sensitive-text verification records required by R4-2/R4-3.
4. Run direction revision, Advanced planning, pilot, Remotion render, decoded
   viewer evidence, QA, final-review verification, and local delivery.
5. Register a self-hosted runner with `self-hosted`, `linux`, `x64`, and
   `clipforge` labels, then rerun CI on the exact head. A queued job is never
   a pass.
6. Record MP4, decoded frames, contact sheets, audio measurements, provider
   receipts, rights evidence, QA, final-review, delivery, and cache facts.

**Acceptance:** the generic path has a non-campaign source, a verified package,
complete Codex speech evidence, a human playback receipt, local delivery, and
green CI on the exact reviewed commit.

### R4-2 — Add an explicit generic caption-correction contract

**Observed problem:** `TarteelSpeechInterval.observed_text` is the only text
field in the generic review. `validate_speech_captions()` compares it to the
forced ASR words, so a Codex correction that fixes a misheard word, punctuation,
number, or contextual phrase fails as a mismatch. There is no explicit binding
between original ASR text, corrected display text, and the source word ids.
The operator documentation promises corrections that the generic contract
cannot represent.

**Root cause:** the historical Tarteel speech inventory was reused for generic
review without adding the correction model that already exists for ordinary
Arabic corrections.

**Repair steps:**

1. Add a versioned `SpeechCaptionCorrection` record with source word ids,
   original ASR text, corrected display text, locale, source window, evidence
   kind, reviewer, and review note. Keep `TarteelSpeechReview` backward
   compatible.
2. Add `corrections` to the review document and require every correction to
   reference existing forced words, stay inside one retained TimeMap segment,
   and preserve the source meaning.
3. Build corrected caption events from the correction record before
   `validate_speech_captions()`. Validate punctuation and whitespace without
   requiring corrected display text to equal raw ASR tokens.
4. Hash the correction set into `speech_review_sha256` or a separate
   `caption_corrections_sha256`, render input, caption evidence, QA, final
   review, and cache identity.
5. Reject unknown word ids, corrections crossing cuts, empty display text,
   HTML, newline injection, and a correction whose evidence does not cover its
   source window.

**Regression tests:** corrected English, French, and Arabic word; punctuation
correction; number correction; unknown word; correction across a jump cut;
changed correction hash; stale render input; and exact corrected caption frame
proof through the production Advanced composition.

**Acceptance:** Codex can repair an ASR phrase without mutating raw alignment,
and the rendered caption is provably the reviewed display text with exact word
and TimeMap provenance.

### R4-3 — Make sensitive-text verification real and span-bound

**Observed problem:** `SpeechVerification` accepts any `http://` or `https://`
prefix, including an empty/invalid host, and accepts any 64-character hash
without proving that a local snapshot exists. A verification is not bound to a
speech interval, source word ids, canonical text, or a specific Quran/quotation
span. `verifications` is optional for every generic review, so a Codex review
can pass with no verification record for a no-error subject.

**Repair steps:**

1. Replace prefix checks with URL parsing that requires an HTTP(S) scheme,
   hostname, and safe evidence URL; reject credentials, fragments used as
   hidden data, and unsafe schemes.
2. Add `subject_span_ids` or exact source-word ids and the expected verified
   text to `SpeechVerification`.
3. For local snapshots, require a confined relative path and verify the file’s
   actual SHA-256 before accepting the review. Do not treat an unbound hash as
   evidence.
4. Add a deterministic Codex review classification for Quran, quotations,
   names, numbers, and factual claims. If a retained interval is classified as
   one of these subjects, require at least one matching verification record.
5. Keep official Quran canonical snapshots on the existing Tarteel path; do
   not weaken that stronger canonical match gate.

**Regression tests:** empty-host URL, credentialed URL, missing snapshot,
changed snapshot bytes, verification bound to another interval, sensitive span
without verification, valid URL plus exact span, and valid hashed snapshot.

**Acceptance:** no sensitive text reaches clean production without a
verifiable, span-bound source record; render remains offline after evidence is
captured.

### R4-4 — Require Codex speech review for new clean production

**Observed problem:** generic Advanced planning can proceed with
`speech_review=None`; it produces `speech_coverage_status=insufficient_evidence`
and can still create a draft/render input. The system documentation now says
Codex is the subtitle reviewer, but the production gate only requires speech
review for Tarteel or when a generic review happens to exist.

**Repair steps:**

1. Add an explicit profile/policy field for `codex_speech_review_required`,
   defaulting to true for every new non-legacy clean production direction.
2. Fail Advanced planning/preflight before Remotion when the required generic
   review is absent or stale. Preserve old `legacy-v1` artifact readability.
3. Keep `insufficient_evidence` available for exploratory rough drafts, but
   mark those artifacts `draft_only` and prevent final review/delivery.
4. Expose the exact blocker in CLI, QA, and final-review payloads.

**Regression tests:** generic clean plan without review blocks; generic legacy
plan remains readable; stale review blocks; Codex review allows planning;
final/delivery remain blocked for draft-only output.

**Acceptance:** a new clean generic render cannot be presented as reviewable
caption-complete output without a Codex speech review.

### R4-5 — Preserve Arabic shaping while retaining emotion/word evidence

**Observed problem:** `CaptionPlate` renders Arabic as whole lines only when
`wordStatuses` is undefined. Advanced Hero passes `wordStatuses={item.words}`,
so Arabic lines can be split on spaces into independently styled spans. That
can break joining, marks, punctuation placement, and the exact shaping rule
specified by the motion skill.

**Repair steps:**

1. Treat Arabic and uncertain RTL segmentation as whole shaped runs even when
   word status metadata exists.
2. Represent active-word emphasis as a line/run-level overlay or a shaped-range
   strategy that does not split Arabic grapheme joining.
3. Keep emoji outside the shaped Arabic run with explicit direction and
   spacing.
4. Add browser fixtures for Arabic with active status, Quran Uthmani marks,
   punctuation, emoji, and a short cue.
5. Decode and visually inspect Arabic frames; do not use OCR alone as proof.

**Acceptance:** Arabic glyphs remain joined and readable while the system still
records word timing and displays supported emotion annotations.

### R4-6 — Preserve disjoint speech windows and silence evidence

**Observed problem:** `_build_treatment_audio_mix()` unions all aligned-word
intersections into one `speech_overlap_windows` interval per SFX cue. A cue
spanning two separated speech regions therefore creates a false continuous
window, and `silence_windows` is always empty. The renderer ducks over the
union, and the decoded measurement cannot prove the silent gap was preserved.

**Repair steps:**

1. Change the typed mix contract to store a list of disjoint overlap windows
   per cue, with source/output clock and exact word ids.
2. Store complementary silence windows where an SFX cue spans a reviewed gap.
3. Make Remotion duck only the exact overlap windows and leave silence/source
   audio untouched between them.
4. Measure every overlap and silence window after encode; require all expected
   windows to be present in the measurement sidecar.
5. Keep legacy v1 receipts readable with an explicit compatibility version;
   new clean plans use the disjoint-window contract.

**Regression tests:** one speech window, two separated windows, SFX in silence,
jump-cut speech, narration overlap, changed mix policy, and decoded audio
measurement with one row per exact window.

**Acceptance:** the plan, renderer, and decoded evidence agree on every speech
and silence interval; no ducking is applied across a gap.

### R4-7 — Complete output-space visual collision and relevance evidence

**Observed problem:** treatment planning creates fixed rectangles for the
platform safe area, caption lane, and source text. Face geometry is measured,
but logo, CTA, active subject, and selected B-roll regions are not decoded and
measured in final output coordinates. B-roll relevance still depends on
reviewed tags/notes; an observation sidecar does not automatically prove that
the selected asset is semantically related to the spoken beat.

**Repair steps:**

1. Add typed output-space observations for source-native text, logo, CTA,
   active subject, captions, platform rails, and every selected B-roll layer.
2. Transform all regions after the actual crop/reframe and camera envelope.
3. Require decoded representative frames for selected visual assets and record
   labels, timestamps, analyzer version, confidence, and evidence source.
4. Calculate a numeric relevance result from the decoded observation plus
   source-grounded evidence. Tags may assist discovery but cannot be the only
   proof.
5. Re-run collision checks after camera travel, frame layout, and caption
   placement; emit stable omission reasons before render input.

**Regression tests:** matching tags but unrelated frames; changed observation
bytes; source text/logo/CTA overlap; active-face collision; B-roll crop after
portrait transform; and camera envelope maximum travel.

**Acceptance:** every visual layer that reaches render input has measured final
coordinates and source-grounded relevance evidence.

### R4-8 — Bound browser retries and resume at a renderable checkpoint

**Observed problem:** the post-change real draft rerender produced a checkpoint,
then Chrome repeatedly crashed around frames 599/600. The run was stopped and
marked failed, which is correct, but the browser subprocess did not reach a
successful bounded completion. The current Remotion script has browser setup
timeouts and Remotion retries, but no explicit end-to-end render deadline or
operator-visible per-candidate frame checkpoint that can resume the same
candidate without redoing an unbounded browser attempt.

**Repair steps:**

1. Add a bounded per-candidate render deadline and a maximum retry count at the
   Python/Node boundary.
2. Persist the last completed frame/chunk, renderer dependency hash, batch input
   hash, and browser attempt number before each retry.
3. On resume, render only the missing frame range/chunk and stitch it through
   the existing deterministic path; never mark a partial MP4 complete.
4. Terminate the browser/process group on timeout or cancellation and record
   the exact failure reason.
5. Add a deterministic browser-crash fixture that fails frame N, resumes, and
   proves the final MP4 hash, duration, audio, and evidence are complete.

**Acceptance:** a repeated browser crash becomes a bounded failed checkpoint
that can resume missing work, never hangs indefinitely, and never claims
success from a partial file.

### R4-9 — Make evidence publication append-only and update the ledger

**Observed problem:** the Codex captions CLI writes to one fixed
`editorial/speech-reviews/<source>/<candidate>/speech-review.json` path with
`publish_json`, so a later review can replace the bytes in place. The existing
plan describes append-only evidence, but this sidecar path is mutable. The
round-3 plan also has a stale reviewed-head field and does not distinguish the
completed generic draft from the failed post-change rerender in its main ledger.

**Repair steps:**

1. Write each speech review to an immutable review-id path and append a small
   current-pointer record, or persist it through the append-only review store.
2. Make the current pointer hash-bound and reject reuse of an older approval for
   a changed review.
3. Preserve every superseded review for audit and stale-artifact invalidation.
4. Update the round-3 ledger’s exact head to `cda133d7...` or explicitly mark
   the historical row as superseded by this round-4 audit.
5. Add tests for two reviews, current-pointer changes, stale render input, and
   recovery after interrupted review publication.

**Acceptance:** no subtitle review, correction, or sensitive-text record is
silently overwritten; every render names the exact immutable review artifact.

## Required verification sequence

1. Run targeted tests for each R4 item, including a failing case.
2. Regenerate schemas and run `clipforge schema check` after contract changes.
3. Run `./scripts/validate.sh` on the exact implementation head.
4. Execute the real generic non-campaign provider proof, including a complete
   Codex review and a human playback receipt.
5. Inspect decoded Arabic/RTL, corrected-caption, emoji, cut-boundary, visual
   collision, and disjoint-audio frames/windows.
6. Run cache/stale checks after changing source, review, correction,
   verification, observation, mix, font, and renderer dependencies.
7. Run `final verify`, `qa verify`, `qa gate`, `delivery verify`, and cache
   status/show commands against the same evidence bundle.
8. Confirm no Chrome, Node, ffmpeg, or worker process remains.
9. Update the evidence ledger with exact hashes and external statuses.
10. Stop at the draft PR for independent code and human visual/audio review.

## Exit criteria

Round 4 is not complete until R4-1 through R4-9 have either passed their
acceptance criteria or are explicitly marked as external blockers with the
required operator input. The system may not claim caption-complete production,
final approval, delivery, or CI success from the current R3 packet alone.
