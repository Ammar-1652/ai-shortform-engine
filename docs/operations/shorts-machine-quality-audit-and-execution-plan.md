# Shorts-machine quality audit and execution plan

**Audit date:** 2026-10-15  
**Status:** BLOCKED / NOT READY; technical gates pass for a draft, but decoded-frame review found production-quality defects  
**Scope:** the current Clipforge checkout, the two authorized Antoine campaign
sources in the ignored work root, and the recent Hero/Advanced Hero artifacts.

This document records the investigation, implementation slices, and current
proof. A draft is not a campaign approval. The plan deliberately separates hard
pipeline blockers from editorial-quality improvements and optional polish.

## 1. Baseline and evidence

| Fact | Current evidence |
|---|---|
| Branch | `feature/motion-craft-production-quality` |
| HEAD | `e345543b77ef5cc43e719479b7c9cedb41904ca1` |
| Merge baseline | `origin/main` = `989bf5d6ec27878d46505dc09becedfc848cd749` |
| Branch state | The feature branch is stacked on the still-open draft PR #32 (`round-31-portrait-production-repair`) and is not merged. Draft PR #33 targets that branch. The worktree also contains the user-owned untracked `envato/` directory, which was not changed. |
| Current official American Advanced Hero | `var/round19/work/projects/24875a39-fcfe-433f-9cb0-a29a541917f5/sources/51a6b349-103f-4bab-88d7-4f90aa18b31f/advanced-hero/runs/2b47121e-7156-465e-85b3-bd5117d2b5db/candidates/1fc57d0d-a82d-5e31-879a-f43189f5bc99/advanced.mp4` |
| Current official American render facts | 1080×1920, 30 fps, 36.833 s, H.264/AAC stereo 48 kHz, 1,105 frames, -17.3 LUFS integrated. |
| Current American render input | `kinetic-caption-v1`, `manual_window` with 13 windows, 19 caption cues, 3 typography events, **0** motion graphics, **0** B-roll events, **0** SFX events. |
| Current selected direction | `.../advanced-hero/plans/1fc57d0d-a82d-5e31-879a-f43189f5bc99/direction.json`; selected `kinetic-caption-v1` option has no asset placements and no motion graphics. |
| Real-frame inspection | The current contact sheets show a talking-head crop and readable caption plates, but no topic-specific illustration, no B-roll, and no deliberate cut/story progression. The source-native TEDx title frame is visible at the opening. |
| Manual 60-second credit experiment | `var/round19/work/operation/editorial-recut/credit-piggybacking-editorial-recut-60s-final-v4.mp4`; 60 s, -16.9 LUFS, -1.5 dBTP. It is an ignored manual composite, not a CLI-authorized Hero/Advanced Hero artifact. Its render input uses approximate transcript timing and contains repeated/awkward caption phrases such as `credit card` across adjacent cues. |
| Manual graphic experiment | `var/round19/work/operation/credit-graphic-review/credit-piggybacking-card-graphic-review-v4.mp4`; one animated credit-card card is visible, but this is an unapproved review composite with no current QA/final-review authorization. |
| Alignment gate before this repair | With no environment variable, direction verification returned `speech_evidence_missing`; the valid pack was present at `/home/pakka/.local/clipforge-speech-evidence` but was only discovered by pytest. |
| Alignment gate after first repair | Production now discovers the installed pack through the shared resolver; the same direction verification returns `PASS direction` with `style_id: kinetic-caption-v1`. |
| Current doctor after first repair | `uv run clipforge hero doctor --work-dir var/round19/work` reports `PASS speech_evidence: en-US verified_live (/home/pakka/.local/clipforge-speech-evidence)`. |
| Envato availability | `uv run clipforge assets doctor` reports `enabled: 0`, `connection: not_configured`, `direct_download: unsupported`. The project policy still requires manual download, license evidence, relevance review, and registration; campaign policy may block outside media. |
| New multi-cut diagnostic draft | `var/round19/review/arc-credit-graphic/advanced-credit-graphic.mp4`; 1080×1920, 30 fps, 8.733 s, H.264/AAC stereo 48 kHz. It uses three source-grounded ranges, two `clean_cut_v1` transitions, six remapped caption cues, and one `business_spotlight` illustration. It is retained as proof of the earlier fragment-start failure and is not an accepted edit. |
| Current multi-cut draft | `var/round19/review/arc-credit-v2/advanced-credit-graphic-v2.mp4` with contact sheet `var/round19/review/arc-credit-v2/contact.jpg`; body now begins at the source sentence “Today, his company…”, and duplicate graphic labels are suppressed when the caption already carries the exact phrase. It passes Advanced verify and QA, but still awaits independent human visual acceptance. |
| New draft proof | `clipforge hero advanced verify` and `clipforge qa verify` pass for the exact encoded artifact. The current v2 `ebur128` measurement is -16.5 LUFS integrated, LRA 2.5 LU, and loudnorm reports -5.79 dBTP true peak. OCR was unavailable because Tesseract is not installed; contact sheets and deterministic geometry/cue checks were used. |

The historical `docs/operations/round-31-validation.md` is not current visual
proof. It describes a synthetic smoke and a different temporary environment;
it does not clear the current missing speech-evidence gate or prove the current
campaign outputs.

## 1A. Post-fix re-audit (2026-10-15)

This is a second pass over the changes already landed on this branch. It is an
audit of the encoded outputs and the production path, not a claim that the
remaining defects are fixed.

| Check | Result and evidence |
|---|---|
| Exact code under review | `feature/motion-craft-production-quality` at `e345543b77ef5cc43e719479b7c9cedb41904ca1`; merge baseline `origin/main` `989bf5d6ec27878d46505dc09becedfc848cd749`; draft PR #33 is open and stacked on draft PR #32, neither merged. |
| Full local validation | `./scripts/validate.sh`: **752 passed, 2 skipped** in 11:41; schemas match; renderer lint/typecheck passed; renderer Vitest **38 passed**; doctor **10 pass, 0 warn, 0 fail**. This is technical evidence only. |
| Advanced verification and QA | Current credit arc returns `PASS` for Advanced verify and QA on the exact encoded artifact. Cache lookup returns a hit for the unchanged render. |
| Current encoded artifact | [`advanced-credit-graphic-v2.mp4`](../../var/round19/review/arc-credit-v2/advanced-credit-graphic-v2.mp4) is 1080×1920, 30 fps, 10.533 s, SHA-256 `13468994906bd73fd7933aa97293605b9b9b8d8e3b67267a0029d4325ea984`. The input declares `contain`, 7 captions, 2 typography events, 1 graphic, 2 transitions, 0 B-roll, and 0 SFX. |
| Decoded-frame proof | [`contact.jpg`](../../var/round19/review/arc-credit-v2/contact.jpg), plus the ignored review bundle at `var/round19/work/operation/post-fix-audit-2026-10-15/`, was inspected. Frames show complete portrait coverage but a vertically stretched 16:9 foreground, source-native opening text duplicated by generated caption treatment, a narrow four-line caption layout, and a generic upward chart over the speaker for an exotic-car/company statement. |
| Both production paths | The American Advanced and Hero contact sheets in the same review bundle show the same portrait foreground stretch pattern. This is not isolated to the credit fixture. |
| Timing/audio | The current artifact has matching zero-based starts and approximately 7 ms AAC duration padding; integrated loudness is -16.5 LUFS, LRA 2.5 LU, with true peak below the delivery ceiling. This proves file-level timing/loudness only; it does not prove perceptual lip-sync or SFX comfort. |
| OCR and human acceptance | Tesseract is unavailable. Deterministic frame/geometry checks and visual contact-sheet inspection were used; OCR is not claimed. No independent human final-review decision is bound to this artifact. |

### What landed correctly

The shared speech-evidence resolver now finds the installed measured pack and
fails closed for unsafe overrides. The Advanced path persists and stages the
exact ordered `TimeMap`; arc plans bind complete forced-word ranges, remap
captions/graphics/transitions onto the effective clock, reject diagnostic
events, and avoid padding a target duration by repeating footage. The current
multi-cut draft has two transitions at real interior boundaries, no repeated
source range, and no debug panels. Direction, Advanced verify, QA, schema
checks, cache identity, and stale-evidence bindings are exercised by the local
suite.

**Phase 1 status: LANDED / TECHNICALLY VERIFIED.** Hero and Advanced Hero now
share `containRect`, which produces explicit integer output-space bounds and
removes the `AbsoluteFill`/`objectFit: fill` stretch. New production renders
were encoded and inspected:

- Advanced: `var/round19/review/phase1-geometry-credit/candidates/b743351c-1cfd-5c07-92d9-efb2de224bab/advanced-geometry-v1.mp4`, SHA-256 `1542b81e7b01f182075b9f14ed3c5f689b27c15a99cfe0315a62cb7a48048693`.
- Hero: `var/round19/review/phase1-geometry-hero/candidates/b743351c-1cfd-5c07-92d9-efb2de224bab/hero-geometry-v1.mp4`, SHA-256 `db2a48bd1ea385fc653b3194626b5c1efc57b971d5f28a7ffdd5240760b86d99`.

Both contact sheets show an undistorted 16:9 foreground over the explicit
blurred review background. The recipe identities advanced to Hero v2 and
Advanced v4, so old cached artifacts cannot authorize this geometry.

The service-level proof was then rerun through the normal CLI with the
persisted database, approval, selected arc, and TimeMap. Those are the valid
production-path artifacts:

- Advanced CLI run `e31baca2-c786-4614-b19a-e24395eb4780`: `var/round19/work/projects/24875a39-fcfe-433f-9cb0-a29a541917f5/sources/b7b2132c-406f-4d3b-8092-df902dd7c290/advanced-hero/runs/e31baca2-c786-4614-b19a-e24395eb4780/candidates/b743351c-1cfd-5c07-92d9-efb2de224bab/advanced.mp4`, SHA-256 `093187876e595d5cb718270c37a899fbc8fd3a410848cef55449711653b1b63d`.
- Hero CLI run `500d777c-c7c7-48c7-aed0-201d2edcb754`: `var/round19/work/projects/24875a39-fcfe-433f-9cb0-a29a541917f5/sources/b7b2132c-406f-4d3b-8092-df902dd7c290/hero/runs/500d777c-c7c7-48c7-aed0-201d2edcb754/candidates/b743351c-1cfd-5c07-92d9-efb2de224bab/hero.mp4`, SHA-256 `a302d982dec6bb566048f0101ca927cee755282746b969e1f849c0631c1f502a`.

The manually staged Phase 1 experiments under `var/round19/review/phase1-geometry-*`
were used only to isolate the renderer transform. They are not service-level
artifacts and are excluded from approval or delivery claims.

**Phase 2 status: PARTIALLY LANDED / TECHNICALLY VERIFIED for layout.** The
renderer now consumes the clean style's safe margins, contrast mode, and font
identity for caption plates; the default Latin wrapping budget is 22 characters
instead of 12, while explicit locale tests retain their requested widths. The
browser regression decoded Arabic, Japanese, French, and English caption ink
against caption-free baselines. The current Hero artifact was deliberately
rerendered first, which made the previous Advanced approval stale; the service
correctly refused to render Advanced until a human re-approves that new Hero
artifact. The typed `SourceNativeText` annotation and duplicate suppression
path now exist. The joint review draft supplies a reviewed scene annotation for
the baked opening title, and clean draft rendering carries it through the
effective TimeMap. Actual font-file hash verification and source-native title
collision behavior are technically verified by the staged production renders;
independent visual acceptance remains open.

The post-layout Hero CLI artifact is run
`1e9ea5a1-57ae-464f-9053-47065f6616d2`,
`var/round19/work/projects/24875a39-fcfe-433f-9cb0-a29a541917f5/sources/b7b2132c-406f-4d3b-8092-df902dd7c290/hero/runs/1e9ea5a1-57ae-464f-9053-47065f6616d2/candidates/b743351c-1cfd-5c07-92d9-efb2de224bab/hero.mp4`, SHA-256 `aa0d47a2fb85e2473c2c33dac0dfe644af9a0c3a50b639e41511b71457c349d0`. Its decoded frame is retained at `var/round19/review/phase2-caption-cli-hero/frame-4.5.jpg` and shows two-line readable caption wrapping inside the portrait safe area. This new Hero artifact intentionally invalidates the prior Advanced approval.

After adding the pinned local Noto Arabic dependency, the production Hero was
rerendered again. The current exact encoded draft is run
`c46aa0b0-e13d-4fa9-9104-b2c873d2185e`,
`var/round19/work/projects/24875a39-fcfe-433f-9cb0-a29a541917f5/sources/b7b2132c-406f-4d3b-8092-df902dd7c290/hero/runs/c46aa0b0-e13d-4fa9-9104-b2c873d2185e/candidates/b743351c-1cfd-5c07-92d9-efb2de224bab/hero.mp4`, SHA-256
`c6f432c4b0fc18d4f5714d0a9f2f7ab276d19b97249003082883d16240a069f1`.
Its decoded contact sheet is
`var/round19/review/phase2-hero-v3-frames/contact.jpg` (SHA-256
`f6a56125cc24fe0ffe89f8ac980ea518d400f4cbc29aac96955f627d5d3588b8`).
The file is 1080x1920, 30 fps, 37.803 s container duration, 1,134 video
frames, H.264/AAC stereo at 48 kHz, and -15.6 LUFS integrated with 4.1 LU
LRA. The visual inspection shows a contained, undistorted source over the
deliberate blurred portrait fill and readable two-line caption plates; no
magenta/cyan diagnostic panels are present. The render input/profile now binds
three staged hashes: DejaVu Latin, Noto CJK, and Noto Arabic. The pinned-font
inventory and license evidence are documented in
`docs/architecture/caption-fonts.md`.

**Phase 4 semantic graphic guard: LANDED / TECHNICALLY VERIFIED.** The
`business_spotlight` template no longer accepts the word “company” alone. A
direction must contain evidence for business, founder, or enterprise meaning;
otherwise the native chart is omitted. The new regression rejects a
company-only claim. A topic-specific car/company illustration still requires a
reviewed allowlisted template or restraint; no unrelated Envato asset is
substituted.

### What is still blocking a reviewable short

1. **Source-native collision review is now available but still human-gated.**
   The current joint draft carries a reviewed opening-title annotation and
   suppresses duplicate optional typography while retaining speech captions.
   A human must still decide whether the source title and speech-caption
   treatment are editorially acceptable before approval.
2. **Caption geometry is technically present but visually cramped.** The
   current portrait layout wraps short phrases to roughly four narrow lines.
   Declared safe margins, contrast, and font identity are fingerprinted but are
   not all consumed by the renderer; hard-coded margins and font stacks remain.
   This is a contract/render mismatch and a cache-integrity risk.
3. **The arc is word-safe but not claim-complete.** The selected punch ends at
   “he also owns an exotic car company?” while the next source sentence,
   “He now lives with him full-time.”, is omitted. Word-boundary validation alone
   permits a semantically truncated sentence. Arc planning must inspect
   punctuation, continuation sentences, and claim closure before accepting an
   ending.
4. **The graphic is source-bound but semantically weak.** A generic rising
   business chart is shown for an exotic-car/company claim. Broad keyword
   matching (`business`, `company`, `founder`, etc.) is not enough. Graphic
   templates need claim-specific purpose and must be omitted when no truthful
   visual grammar exists.
5. **Audio event quality is not proved.** The current artifact contains no SFX,
   so the loudness gate does not exercise the reported sharp/annoying effect
   problem. Full-file LUFS cannot detect a harsh transient or speech masking;
   event-window peak/RMS, ducking, and speech intelligibility checks are still
   required.
6. **The review bundle is not yet a delivery gate.** The audit helper produced
   ffprobe, loudness, decoded frames, contact sheets, and evidence JSON under
   `var/round19/work/operation/post-fix-audit-2026-10-15/`, but production QA
   does not yet require semantic caption/graphic relevance and a human complete
   clip review before delivery.

The current status therefore remains **BLOCKED / NOT READY**. Green tests prove
contracts and executable paths; they do not clear these viewer-facing defects.

Latest full validation after the geometry, caption, semantic graphic,
source-native annotation, and three-font recipe changes: `./scripts/validate.sh`
completed with **753 passed, 2 skipped** in 13:20; schemas matched; renderer
lint/typecheck passed; renderer Vitest completed with **43 passed**; doctor
reported **10 pass, 0 warn, 0 fail**. The skipped tests remain the
repository's documented optional cases.

## 1B. Joint Hero/Advanced review draft proof (2026-10-16)

The operator requested that Hero and Advanced Hero be reviewed together before
approval. A narrowly scoped `--draft-only` path was added rather than
manufacturing a Hero review row. It records `hero_review_status: pending` in
the plan, render input, manifest, and cache identity. Default Advanced commands
remain approval-gated, and delivery preflight rejects pending sets.

The current source-grounded draft uses direction
`direction-b743351c-motion-graphic-v4-draft`, an annotated opening source title,
and the immutable arc `arc-b743351c-hook-body-punch-v1`. The arc keeps three
complete forced-word ranges in hook/body/punch order, adds two `clean_cut_v1`
transitions, and remaps the founder/business illustration onto the body beat.
The illustration was moved to the upper safe rail after decoded-frame review
showed it covering the PAC-10 source logo at its first placement.

The current Advanced draft is run
`3e8fd91d-9d4a-46bb-8dce-94ad2aece4aa`:
`var/round19/work/projects/24875a39-fcfe-433f-9cb0-a29a541917f5/sources/b7b2132c-406f-4d3b-8092-df902dd7c290/advanced-hero/runs/3e8fd91d-9d4a-46bb-8dce-94ad2aece4aa/candidates/b743351c-1cfd-5c07-92d9-efb2de224bab/advanced.mp4`, SHA-256
`603d6c2add5afabe3956fc47b2b8b4360ef6bc8bfa998555613acf2298b8198b`.
Its manifest is SHA-256
`ba71cbff409905a9f62e7aa98f5040df927c9c9d3a23f8b3dd41f15b6dbb8b92`.
The contact sheet is
`var/round19/review/advanced-joint-review-v2/contact.jpg` (SHA-256
`cfd14a1d35ecbd4c52e62a220cceea36712056ad668941bb264b3dd59960a862`).
It is 1080x1920, 30 fps, 21.967 s, 659 frames, AAC stereo 48 kHz, -15.6
LUFS integrated, 3.3 LU LRA, and -4.0 dBFS true peak. `hero advanced verify`
and `qa verify` pass for the exact artifact. OCR remains unavailable.

The full validation after this integration is **754 passed, 2 skipped** in
12:24; renderer Vitest remains **43 passed** and doctor remains **10 pass, 0
warn, 0 fail**. The focused pending-draft regression is included. The draft is
reviewable but not deliverable until a human approves the current Hero and then
the resulting Advanced artifact.

## 1C. Current re-audit after the joint-draft implementation (2026-10-16)

This pass supersedes the older status tables above for the current checkout at
`9ab8fd3e98f707a8607373462a5a4653704cb2ff`. It compares the production
render-input, encoded MP4, decoded contact sheet, manifests, and approval and
delivery paths. PR #33 is still a draft stacked on draft PR #32; neither branch
is merged into `main`. The user-owned untracked `envato/` directory was not
modified.

### What landed

| Area | Evidence | Status |
|---|---|---|
| Single output clock and multi-cut staging | The current Advanced render uses the persisted three-segment arc and two interior `clean_cut_v1` transitions. It does not repeat a source range to reach a target duration. | Landed; technically verified |
| Portrait geometry | The 16:9 source is undistorted inside the 9:16 output. The foreground is contained over an intentional blurred review background. | Landed for review `contain`; delivery fill still unproved |
| Caption production | The exact encoded input contains 12 complete grouped cues, a pinned style/profile, and the current locale-safe renderer. No debug marker layer is present. | Landed; decoded English coverage is visible |
| Review safety | `hero advanced render` remains approval-gated by default. `--draft-only` marks the set `hero_review_status: pending`; publish preflight rejects it. No review decision row was fabricated. | Landed; technical gate verified |
| File-level audio | The MP4 is 1080x1920, 30 fps, 21.966667 s video and 21.952000 s AAC, -15.6 LUFS integrated, 3.3 LU LRA, and -4.0 dBTP. | Landed for loudness measurement; perceptual cut sync unproved |
| Automated checks | The last full validation completed with 754 passed and 2 skipped; renderer Vitest reported 43 passed; doctor reported 10 pass, 0 warn, 0 fail. | Technical evidence only |

Current artifact paths and hashes:

- MP4: `var/round19/work/projects/24875a39-fcfe-433f-9cb0-a29a541917f5/sources/b7b2132c-406f-4d3b-8092-df902dd7c290/advanced-hero/runs/3e8fd91d-9d4a-46bb-8dce-94ad2aece4aa/candidates/b743351c-1cfd-5c07-92d9-efb2de224bab/advanced.mp4`, SHA-256 `603d6c2add5afabe3956fc47b2b8b4360ef6bc8bfa998555613acf2298b8198b`.
- Manifest: the same run's `manifest.json`, SHA-256 `ba71cbff409905a9f62e7aa98f5040df927c9c9d3a23f8b3dd41f15b6dbb8b92`; it records `hero_review_status: pending`.
- Contact sheet: `var/round19/review/advanced-joint-review-v2/contact.jpg`, SHA-256 `cfd14a1d35ecbd4c52e62a220cceea36712056ad668941bb264b3dd59960a862`.

### What still blocks a reviewable shorts machine

1. **The arc is word-complete but not editorially claim-complete.** The body
   ends with the ASR phrase “will his son Antoine Jr.” and omits the following
   completion “He now lives with him full-time.” The validator checks forced-word
   boundaries but cannot identify an unfinished clause or a premise whose
   consequence is missing. Add a claim-closure contract based on punctuation,
   continuation spans, and a reviewed beat purpose; reject or require review of
   an arc that ends on an open dependency.

2. **The selected graphic overstates the evidence.** `business_spotlight`
   draws a rising trend chart for the sentence that identifies a founder and
   companies. The source does not provide a time series or growth claim. The
   current keyword guard permits “founder” or “enterprise”, which is sufficient
   for a business identity card but not for a chart. Split the template grammar
   into identity/brand and quantitative-trend variants, and require numeric
   evidence plus a declared measure for the latter. If no truthful visual
   grammar exists, select restraint.

3. **Source-native text still competes with generated captions.** The decoded
   opening contains the baked question card and a generated caption that repeats
   the same spoken question. The optional typography layer is suppressed, but
   ordinary captions remain unaware of a reviewed source-native phrase. Add a
   source-native caption collision policy: delay or reposition the first cue, or
   explicitly mark the native phrase as the visible caption for that interval.
   The policy must be language- and region-aware and proven on decoded frames.

4. **The current draft proves only review `contain`, not an attractive final
   portrait composition.** The foreground is correctly undistorted, but blurred
   rails consume much of the portrait frame. No current artifact proves an
   explicit `center_crop`, valid `face_follow`, or reviewed manual trajectory
   with caption, face, and source-text collision checks. The delivery profile
   must choose a fill strategy explicitly and render and audit it before a short
   can be considered viewer-ready.

5. **Motion is still a capability demo rather than a finished visual direction.**
   The output has two clean cuts and one small chart, but no relevant B-roll or
   event-level sound design. This is acceptable for a restraint alternative, but
   the current selector chooses the chart without proving that it improves
   comprehension. Direction scoring needs a visual-purpose decision and a
   human-review checklist for each graphic, cutaway, and transition. Effects
   must remain optional and source-grounded; adding them by count would recreate
   the earlier unrelated-asset problem.

6. **Audio proof stops at the file level.** The AAC stream is about 14.7 ms
   shorter than the video stream and there is no current decoded boundary report
   proving that the first phoneme survives either interior cut. The current draft
   has no SFX, so the reported sharp-effect failure is not exercised. Add per-cut
   audio/video PTS and word-onset checks, and event-window peak/RMS plus
   speech-masking checks whenever SFX is present.

7. **Draft-only state is not isolated from the canonical Advanced pointer.** The
   pending path avoids inserting an approval row, but it writes the normal plan,
   current artifact, and sidecar locations. A pending review experiment can
   therefore replace the path that an older approved package expects. Give review
   drafts an explicit namespace or artifact kind and make cache, QA, final-review,
   and delivery resolve approved and pending sets independently. Existing
   approved artifacts must remain verifiable after a draft render.

8. **Technical QA does not yet gate viewer-facing meaning.** Advanced verify and
   QA pass while the chart/claim mismatch, open body clause, native-text
   duplication, and contain-only composition remain. Generate a decoded review
   bundle from the exact MP4 and make semantic findings visible to final review;
   delivery must require a human decision on that exact hash. OCR remains
   optional and unavailable in this environment.

### Next execution order

The repairs should be executed in this order, with a new encoded proof bundle
after each boundary:

1. **Contract integrity:** isolate pending drafts, preserve legacy approved
   pointers, and include draft kind/status in every cache and stale-evidence
   binding. Add tests for approved artifact verification after a pending render.
2. **Editorial closure:** add claim-complete hook/body/punch validation and
   update the current arc so the body either includes its consequence or ends at
   a defensible complete claim. Do not invent missing words; if ASR is wrong,
   re-align the selected clip or mark the source evidence for human review.
3. **Source-native collision:** implement the reviewed native-text lane for
   captions and typography, then decode the first cue and opening title at frame
   boundaries.
4. **Purposeful graphics:** replace the generic chart with an identity graphic
   or restraint for this source. Add quantitative graphics only when exact
   values, units, and comparison semantics are present. Add B-roll only after
   local registration, rights evidence, tags, and relevance review.
5. **Portrait delivery:** render and inspect explicit center-crop/face-follow
   candidates, choose one from the profile, and prove safe bounds through the
   complete arc. Retain `contain` as an intentional review derivative.
6. **Cut/audio proof:** measure encoded PTS and word onset at every cut; add
   bounded audio envelopes and event-window checks for any SFX. Reject drift,
   truncated phonemes, clipping, harsh effects, and near-silence.
7. **Semantic review gate:** require the decoded bundle, caption coverage,
   repeated-range report, graphic-purpose evidence, asset rights, and a human
   final decision before delivery. Re-run the complete Hero and Advanced pair
   and record separate technical verification and human visual acceptance.

This re-audit remains **BLOCKED / NOT READY**. The implementation has landed
useful timing, geometry, caption, and approval protections, but the current
encoded draft does not yet demonstrate a coherent, semantically supported,
viewer-ready portrait short.

## 2. Root-cause map

### A. Production cannot currently prove selected-clip timing

**Observed symptom:** a new direction verification fails before production with
`speech_evidence_missing` even though a stored alignment row says
`verified_live`.

**Responsible contract/path:** `language.evidence.validate_current_alignment_evidence`
requires the external measured WAV named by the packaged speech catalog. The
callers in Hero verify, Advanced Hero planning/render verification, final review,
campaign production, and publish preflight correctly revalidate it. The missing
`CLIPFORGE_SPEECH_EVIDENCE_ROOT` is therefore a real hard stop, not a UI issue.

**Why prior reports missed it:** prior reports accepted stored JSON status and
synthetic smoke evidence. A stored status is intentionally not proof in the
current contract.

**Required fix:** first establish a documented, reproducible evidence setup for
the authorized sources and run the actual selected-clip WhisperX alignment. Do
not downgrade the gate, copy a catalog row, or use approximate ASR timing for
Hero captions. If live evidence cannot be produced, the run remains blocked.

**Acceptance:** both authorized sources have a current alignment file, measured
speech-evidence facts, matching model/checkpoint/manifest hashes, and a passing
`direction verify` before any new production render.

### B. The editorial authority is too weak for a coherent short

**Observed symptom:** the system can render a technically valid portrait clip,
but it does not reliably create a hook → body → payoff sequence. The manual
60-second experiment had a coherent source order but was outside the production
path; the official Advanced output is essentially one talking-head treatment.

**Responsible contract/path:** `candidates.windows.generate_windows` builds
consecutive transcript windows. `candidates.scoring` measures duration,
coverage, density, punctuation, and visual opportunity, but not claim setup,
curiosity resolution, redundancy, false starts, payoff strength, mute-story
readability, or native-branding penalty. `DirectionDocument` validates three
ordered beats, but it does not yet express a reviewed multi-range editorial arc
or shot-by-shot purpose. The renderer cannot invent those decisions safely.

**Why prior tests missed it:** unit tests prove deterministic ranking and schema
validity, not whether a human can summarize the resulting story or whether a
60-second output repeats a source range.

**Implemented:** a versioned, source-grounded editorial arc contract now
must bind hook, one or more body beats, and payoff to exact aligned words,
ordered TimeMap segments, visual scenes, and an explicit reason for every cut.
It must allow a short to end early when the source has no truthful payoff; it
must never pad a target duration by repeating footage. Candidate mining remains
cheap; this plan is selected and reviewed only after promotion.

**Acceptance:** a plan report can list each output segment once, its spoken
words, source range, visual purpose, and beat role. The plan rejects duplicate
ranges, unsupported claims, cuts inside words, false starts, and a missing
payoff. No “60-second” requirement can cause repetition.

### C. TimeMap and audio continuity are not proven at the edit boundary

**Observed symptom:** earlier trial outputs changed words at cuts (`how` became
`ow`), accumulated drift, or contained audible `aaa`/hard-cut artifacts. The
current code has improved single-clock staging, but no current campaign render
has been re-proven after a complete editorial recut.

**Responsible contract/path:** `TimeMap` is the correct canonical clock and
`docs/adr/0071` specifies identical picture/speech staging and short boundary
envelopes. The missing layer is a production QA assertion that every selected
cut is outside a forced word, that decoded audio and video begin/end together,
and that a speech onset is not truncated.

**Why prior tests missed it:** tests cover mapper arithmetic and synthetic
staging; they do not decode every production cut and compare the first/last
word against the encoded audio.

**Implemented:** the editorial arc produces only complete-word boundaries;
stage every ordered segment with one TimeMap transaction; apply the existing
bounded discontinuity envelope; add decoded boundary checks and a word-onset
regression fixture. No independent millisecond or float timeline may enter the
renderer.

**Acceptance:** at every cut, the first and last spoken words remain intact;
source audio/video PTS start at zero and have the same measured duration; no
interior cut accumulates frame or sample drift.

### D. Caption coverage and duplicate prevention are incomplete

**Observed symptom:** the official current output has 19 grouped cues, but the
manual credit edit has gaps and adjacent duplicate wording. The renderer’s
duplicate check only compares visible same-frame strings; it cannot detect
duplicate phrases across neighboring cues or prove that every spoken word is
covered.

**Responsible contract/path:** `hero_caption_pieces` groups forced words by
word count, character count, punctuation, and gaps. It does not enforce a
readable minimum duration, phrase continuity across a cut, a complete-coverage
interval audit, or semantic duplicate suppression. `CaptionPlate` uses a
generic local stack and reserves a lane, but the plan does not carry a measured
caption bounding box or collision evidence.

**Why prior tests missed it:** layout tests and component tests prove that text
can be painted; they do not compare decoded glyph pixels against forced-word
intervals or test a real cut with adjacent overlapping wording.

**Implemented in the Advanced recut path:** captions are built from remapped
selected-clip forced alignment only;
normalize whitespace at the contract boundary; group phrase-sized cues while
preserving exact source text and punctuation; guarantee a minimum readable
frame budget for short words without extending beyond the cue; keep phrase
geometry stable; handle RTL/CJK as shaped runs; reject duplicate/overlapping
coverage; record the safe-area box and font dependency.

**Acceptance:** a decoded-frame audit reports every forced word covered exactly
once, no isolated punctuation, no duplicate visible phrase, and no caption box
outside the configured 1080×1920 safe region for English, French, Japanese, and
Arabic-shaped test fixtures. Unsupported locales fail closed.

### E. The visual plan is conservative but not yet an engaging edit

**Observed symptom:** current official direction files select a kinetic style
but request no graphics, B-roll, or SFX. The output is a centered talking head
with caption plates. The Remotion component is capable of three small native
illustrations, but no current direction requests one.

**Responsible contract/path:** `DirectionMotionGraphic` allowlists only
`credit_card`, `travel_postcard`, and `business_spotlight`; `_motion_graphics`
maps only selected records. `AdvancedHeroDraft` renders only those templates,
and `MotionGraphicCard` has no general topic-illustration grammar. This is
correctly safe against arbitrary JSX, but it means the direction skill and
operator workflow do not make a purposeful graphic decision. B-roll is an
optional reviewed placement, not an automatic shot replacement.

**Why prior tests missed it:** renderer tests exercise supported payloads and
reject unsupported ones; they do not require a meaningful visual plan for a
source whose story would benefit from one.

**Implemented for the current draft:** the direction vocabulary uses an audited,
source-grounded templates (not arbitrary code). Add a visual beat/shot plan:
source shot, crop strategy, graphic or B-roll purpose, entry/exit, caption
collision region, and whether restraint is preferred. Use a graphic only when
the transcript and scene evidence support its semantics. Add cutaways only when
the registered asset’s content tags and license evidence match the phrase and a
human has reviewed relevance.

**Acceptance:** a topic-appropriate graphic is visible when explicitly selected,
has deterministic entrance/exit motion, leaves the caption/face safe regions,
and displays no unsupported claim. A direction with no truthful visual addition
remains valid and is not padded with decoration.

### F. Audio policy exists, but event-level sound design is not yet a quality gate

**Observed symptom:** the reviewed credit-card composite measures near the
target overall loudness, but the user reported sharp/annoying SFX. Overall LUFS
does not prove that an individual effect is comfortable or that it does not
mask speech.

**Responsible contract/path:** Advanced Hero layers source audio and SFX. The
current renderer applies a per-event gain and short fade, while the delivery
normalizer measures the final file. There is no decoded event-level peak/RMS,
speech-ducking assertion, or harsh-transient guard. Narration is a separate
layer and must not be assumed to improve the edit.

**Why prior tests missed it:** `ebur128` integration checks can pass while a
single transient is too loud; synthetic fixtures do not contain real speech
and a real SFX overlap.

**Existing policy enforced:** one audio bus policy preserves source audio without
narration, explicit source ducking when narration/SFX requires it, SFX gain cap
and envelope, target `-16 LUFS` ±1.5 LU, true peak ≤`-1.5 dBTP`, bounded LRA,
and near-silence failure. Measure event windows plus the final file. No music.

**Acceptance:** speech remains intelligible in every SFX window; event peak and
RMS stay within policy; source/narration durations are declared and covered;
short narration is rejected rather than stretched, looped, or silently cut.

### G. External assets are not an automatic remedy

**Observed symptom:** Envato material was previously unrelated to the topic,
and the current Envato doctor reports no configured connection. The user-owned
`envato/` files remain untouched.

**Responsible contract/path:** `docs/adr/0060` and campaign policy keep Envato
discovery/manual registration separate from rendering. Assets require hash,
probe, license evidence, rights status, content tags, and a source-grounded
placement. For the Antoine campaign, outside media may be prohibited.

**Policy retained:** keep Envato optional. Search only after a direction identifies
a concrete semantic need; request topic-specific terms; require operator
download and license evidence; register under the work root; verify tags and
rights before planning. If policy blocks outside media, use native Remotion
graphics or source footage and record the restriction.

**Acceptance:** no unrelated stock can enter a render because it exists in a
folder, and no render waits on a non-configured MCP. A blocked asset request is
reported as blocked, not silently replaced by a random clip.

### H. QA proves files, not enough viewer-facing meaning

**Observed symptom:** ffprobe and technical QA can pass while an output still
feels repetitive, lacks a payoff, or has a visually irrelevant overlay.

**Responsible contract/path:** `qa.technical`, Advanced verification, final
review, and delivery correctly bind hashes, rights, direction, style, TimeMap,
and approvals. They do not yet provide a full decoded-frame semantic report:
caption glyph proof, repeated-range detection, shot-change assessment, asset
relevance evidence, or audio event comfort.

**Required fix:** add a production review bundle (outside Git) generated from
the actual MP4: ffprobe, ebur128, decoded frames at every cue/beat/cut, contact
sheet, frame-safe geometry, repeated-frame/range detection, caption coverage,
graphic/asset binding, and an explicit human review checklist. OCR is optional
evidence only; absent language packs must be reported.

**Acceptance:** no artifact can be called technically verified until the bundle
exists for the current MP4, and no artifact can be called editorially accepted
without a human final decision bound to that exact artifact.

## 3. Prioritized execution plan

### P0.1 — repair the shared portrait transform before visual polish

This is the first remaining production blocker. The current `contain` path is
not merely a letterbox choice: an `AbsoluteFill` foreground receives an
implicit 100% height and the inner video uses `objectFit: fill`, stretching the
16:9 source. Implement one typed transform helper used by Hero, Advanced Hero,
browser smoke, and any ffmpeg fallback:

- keep a full-frame blurred background only when the explicit review profile
  requests `contain`;
- place the source in an explicit aspect-ratio box with calculated integer
  pixel dimensions and `objectFit: contain`, never an `AbsoluteFill` whose
  injected height can override the box;
- use the same post-transform coordinate space for captions, graphics, faces,
  and safe regions;
- make final delivery choose `center_crop`, eligible `face_follow`, or a
  reviewed manual trajectory explicitly; no silent fallback to `contain`;
- add decoded geometry assertions for both Hero and Advanced Hero and compare
  an unwarped source landmark across the first, middle, and last shot.

Do not fix this by changing the background color or hiding the foreground.
The transform policy and its numeric parameters must be present in render
input, manifest, QA, final review, delivery metadata, and cache identity.

### P0.2 — make the visual review gate semantic, not only technical

Before adding more effects, require a review bundle for every real render. It
must flag source-native title overlap, incomplete sentence/claim endings,
graphic-purpose mismatch, caption collision, repeated source ranges, and
unreviewed stock. A human still decides acceptance; the machine must make the
failure evidence easy to inspect and must block local delivery on stale or
missing evidence.

### P0 — unblock and reproduce the real pipeline

**Completed for this repair point:** production and tests now share evidence
discovery. The installed measured pack is found without an environment export;
an explicit missing or unsafe override still fails closed. The provider and
alignment gates remain unchanged.

1. Configure a measured speech-evidence directory outside Git for the actual
   selected-clip audio. Verify its WAV hash, sample rate, channels, duration,
   transcript, WhisperX model/checkpoint, and device.
2. Re-run current Hero alignment for both authorized sources. Preserve all old
   artifacts; create new run ids. Do not use the manual 60-second composites as
   inputs or proof.
3. Run `hero verify`, direction verification, and the current Advanced plan
   path. Record every failure before changing code.
4. If P0 cannot complete, stop the production upgrade and report the exact
   missing evidence. This is a hard gate.

### P0.5 — preserve an editorial map through Advanced staging

The first cut-related repair now persists the exact Advanced Hero
`TimeMapDocument` beside its digest and makes browser staging consume that map.
The regression suite covers the new field and old plans remain readable. This
fix prevents a reviewed jump-cut map from being silently replaced by the
single-range Hero map.

### P1 — make the editorial arc a first-class reviewed contract

The first production slice is now implemented: `EditorialArcDocument` carries
ordered hook/body/punch ranges, exact forced word ids, and a TimeMap;
`clipforge hero advanced plan --editorial-arc-file` validates and remaps it;
the remapped alignment and map are persisted and staged by Advanced Hero.
Direction intervals, native graphics, B-roll, and SFX are remapped onto the
effective arc clock instead of retaining stale parent timestamps. Arc plans
also derive short, deterministic
`clean_cut_v1` transitions at interior TimeMap boundaries; they never appear
for a one-range clip and cannot alter the output clock.

Add a versioned schema/ADR (rather than a free-form dict) for an
`EditorialArcPlan` or an equivalent extension of `DirectionDocument` containing:

- source-grounded hook, body beat(s), and payoff/punch;
- exact aligned word/evidence ids and output intervals;
- ordered TimeMap segments and source ranges, with no duplicates;
- shot/scene purpose and cut reason for every boundary;
- optional title/callout text only when copied from evidence;
- “restraint” as an explicit valid decision when no B-roll/graphic is truthful;
- arc/plan digest included in render, QA, final-review, delivery, and cache
  identity.

Update the motion-direction skill to return this declarative plan and require
the operator to inspect policy, transcript, alignment, visual scenes, profile,
and current artifacts first. The skill must not write executable renderer code.

### P2 — repair selection and cut timing

- Add editorial heuristics as separate measured fields: claim completeness,
  hook clarity, setup/payoff relation, false-start penalty, repetition penalty,
  native-title/sponsor penalty, visual support, and mute readability.
- Keep candidate quality and edit opportunity separate; do not claim virality.
- Permit multi-segment approved TimeMaps while preserving segment order and
  canonical microseconds.
- Reject cuts inside forced words and reject a plan that fills duration by
  repeating a range.
- Add real-source tests for the two authorized sources and synthetic tests for
  jump cuts, exact boundaries, and duplicate ranges.

### P3 — unify captions and portrait visual treatment

- Generate one complete caption layer from selected-clip forced words; keep
  optional typography/callouts separate.
- Add min-frame readability, stable phrase geometry, punctuation/number rules,
  and adjacent duplicate detection.
- Bind caption boxes, font identity/hash, locale, and safe region to the style
  fingerprint.
- Make the visual plan choose `center_crop`, eligible `face_follow`, or a
  reviewed manual trajectory explicitly. `contain` remains a deliberate
  review option, never a silent delivery fallback.
- Add shot-to-shot crop and collision checks for faces, captions, graphics, and
  source-native text.
- Consume every declared style field or remove it from the versioned contract:
  safe margins, contrast treatment, font identity/hash, and maximum emphasis
  must change the actual renderer output. Measure caption width against the
  configured portrait safe region instead of the current narrow hard-coded
  wrapping. Add a source-native-title evidence lane so a generated hook is
  either suppressed, shortened, or placed without duplicating the baked text.

### P4 — make Remotion graphics and B-roll purposeful

- Expand native graphics only through audited typed templates with semantic
  evidence, geometry, bounded `useCurrentFrame` motion, and decoded proof.
- Add a graphic/shot-purpose registry so a template cannot be selected solely
  because it looks attractive.
- Narrow template semantics. A `business_spotlight` chart cannot be used for a
  generic `company` keyword; it needs explicit evidence for a trend, amount,
  comparison, or process that the chart actually depicts. For an exotic-car
  statement, use a reviewed car/company illustration or choose restraint. Add
  a decoded semantic-purpose checklist to the direction and QA records.
- Require B-roll content tags, exact source evidence, output interval, and
  human relevance review. Do not auto-slot assets.
- Add restrained transitions at approved cut boundaries only; no generic
  pattern interrupts, glow, emoji, skull, or music.

### P5 — enforce audio and sync quality

- Stage picture and speech from one ordered TimeMap transaction.
- Keep source speech intact when narration is absent; duck only under a declared
  narration/SFX policy.
- Enforce final `-16 LUFS` target, `-1.5 dBTP` ceiling, bounded LRA, and
  near-silence failure. Measure event windows, not only the full file.
- Add a decoded audio/video cut-boundary test and a real-word onset fixture.

### P6 — add production proof and operator workflow

For every candidate render, generate an ignored review bundle containing:

1. MP4 SHA-256 and full ffprobe JSON;
2. `ebur128`, true peak, silence, channel/sample-rate facts;
3. decoded frames at first frame, beat starts/ends, every caption interval,
   every cut, every graphic/B-roll/SFX interval, and final frame;
4. contact sheets and safe-region/collision report;
5. caption coverage and duplicate report;
6. repeated-range/perceptual-similarity report;
7. OCR result or an explicit “OCR unavailable” record;
8. source/asset/license/direction/TimeMap/cache bindings;
9. human review checklist and final-review id.

Only after the bundle exists should QA, final review, and local delivery be
considered. A render is a draft until a human approves that exact artifact.

### P7 — re-render the real sources and obtain independent visual acceptance

After P0.1–P6 land, render the same authorized excerpts through both Hero and
Advanced Hero, preserving source spans so before/after comparison is fair.
Render at least one multi-cut arc, one explicit `contain` review derivative,
one portrait-fill delivery, one purposeful native graphic, one restrained
no-graphic case, and an SFX case with event-level audio measurements. Watch
the complete clips with audio, inspect the decoded contact sheets, and bind an
independent human final-review decision to the exact artifact hashes. Until
that happens, an implementation can be technically verified but cannot be
called accepted or production-ready.

## 4. Required tests before calling the machine reliable

### Contract and editorial tests

- arc plan rejects fabricated text, unsupported claims, duplicate ranges,
  missing payoff, ambiguous units, and cuts inside words;
- source order and TimeMap digest are preserved through Hero, Advanced Hero,
  campaign production, resume, cache hit, and forced rerender;
- a valid “no graphic/no stock” direction passes without adding decoration;
- a selected graphic/B-roll/SFX must match evidence, tags, rights, and interval;
- changed arc, style, font, asset tags, audio policy, or renderer recipe makes
  a cache miss and invalidates QA/final approval/delivery.

### Render and frame tests

- real Remotion Hero and Advanced Hero renders for both authorized sources;
- portrait fill, explicit contain review, center crop, face-follow, and manual
  crop trajectories;
- complete English captions plus French, Japanese, and shaped Arabic fixture;
- first/last cue frame, short-word readability, punctuation, numeric values, and
  no duplicate text layer;
- native motion graphic entrance/mid/exit, safe region, face/caption collision,
  and unsupported-template rejection;
- no debug panels, large accidental bars, or repeated 20-second block;
- B-roll and SFX relevance/rights rejection paths.

### Audio and gate tests

- no narration, narration with ducking, short narration rejection, quiet/loud
  source, SFX peak/envelope, near silence, true-peak limit, and target LUFS;
- decoded picture/audio duration and PTS equality at every jump cut;
- stale source, alignment, TimeMap, direction, style, font, asset, audio,
  QA, and final approval block reuse and delivery;
- failed promotion leaves the previous verified package intact.

## 5. Operator sequence after implementation

The implementation round should publish one exact, repository-documented
sequence using the normal CLI (no ad-hoc ffmpeg composition):

```text
clipforge hero doctor --work-dir WORK_ROOT
clipforge hero align SOURCE_ID CANDIDATE_ID --db DB --work-dir WORK_ROOT
clipforge hero plan SOURCE_ID CANDIDATE_ID --db DB --work-dir WORK_ROOT
clipforge hero render SOURCE_ID --db DB --work-dir WORK_ROOT
clipforge hero review open SOURCE_ID --db DB --work-dir WORK_ROOT
clipforge hero advanced direction plan SOURCE_ID CANDIDATE_ID --db DB --work-dir WORK_ROOT
clipforge hero advanced direction verify SOURCE_ID CANDIDATE_ID --db DB --work-dir WORK_ROOT
clipforge hero advanced plan SOURCE_ID CANDIDATE_ID --db DB --work-dir WORK_ROOT
clipforge hero advanced render SOURCE_ID --db DB --work-dir WORK_ROOT
clipforge qa run SOURCE_ID --db DB --work-dir WORK_ROOT
clipforge qa gate SOURCE_ID --db DB --work-dir WORK_ROOT
clipforge final review open SOURCE_ID --db DB --work-dir WORK_ROOT
clipforge publish plan SOURCE_ID CANDIDATE_ID --db DB --work-dir WORK_ROOT
clipforge publish export SOURCE_ID CANDIDATE_ID --db DB --work-dir WORK_ROOT
```

The exact options must be checked against `--help` during implementation; the
sequence is intentionally shown as a pipeline order, not permission to bypass
human review. Envato search/request/register is a separate optional branch and
must stop for manual download and license confirmation before use.

## 6. Definition of done for this upgrade

The machine is not ready merely because tests or CI are green. The next round
is complete only when all of these are true:

- current selected-clip alignment evidence is live and revalidated;
- a human-reviewed arc selects coherent source ranges with no padding/repeats;
- Hero and Advanced Hero use the same canonical TimeMap for picture and speech;
- decoded captions cover the spoken words exactly once and stay readable;
- the portrait frame is intentional and safe; no accidental bars or overlays;
- graphics/B-roll/SFX are relevant, licensed, timed, restrained, and visible for
  a reason—or explicitly omitted;
- audio meets the declared loudness/peak/event policy and remains intelligible;
- the proof bundle is generated from the encoded MP4, with OCR limitations
  recorded honestly;
- cache, stale approval, rights, provenance, QA, final review, and delivery
  gates bind the exact artifact;
- a human watches the complete clips with audio and records acceptance or
  changes requested.

Until then, the correct system status is **BLOCKED / NOT READY**, not PASS.

## 7. Detailed execution runbook

This runbook is the order of work for the next implementation cycle. Each phase
must finish its stop gate before the next phase starts. A green unit suite does
not waive a failed decoded-frame or editorial gate. All work stays on the
existing feature branch and draft PR; no implementation is merged until an
independent code and visual review is complete.

### Phase 0 — establish a reproducible baseline

**Purpose:** ensure every later comparison refers to the same code, sources,
plans, and artifacts.

1. Record `git status --short --branch`, `git log --oneline --decorate --graph
   --all -80`, `git branch -vv`, `git remote -v`, current `HEAD`,
   `origin/main`, PR state, and the merge base.
2. Rehash the two authorized source files, transcript/alignment evidence, the
   current direction document, the current arc document, and each baseline MP4.
3. Copy no media into Git. Keep renders, probes, decoded frames, and review
   bundles below the ignored work root.
4. Run the documented `--help` commands before using any CLI sequence. Capture
   the exact command line, working directory, elapsed time, and exit code.

**Stop gate:** if a source binding, alignment evidence pack, rights record,
TimeMap digest, or baseline artifact cannot be identified, stop and report the
missing binding. Do not regenerate a substitute fixture.

### Phase 1 — repair and centralize portrait geometry

**Purpose:** remove the current stretched-speaker defect while retaining an
explicit review-only `contain` derivative.

1. Add one typed media-transform helper in the renderer boundary. It accepts
   source dimensions, output dimensions, strategy, crop window/trajectory, and
   safe-region policy; it returns integer pixel bounds and the post-transform
   coordinate transform.
2. Use a nested aspect-ratio element for `contain`. Do not put the foreground
   video in an `AbsoluteFill` whose implicit height can override its aspect
   ratio. Do not use `objectFit: fill` for source footage.
3. Keep the blurred background as a separate layer only for an explicitly
   requested review profile. Final delivery must select `center_crop`, valid
   `face_follow`, or reviewed manual framing; an invalid strategy fails closed.
4. Apply the same transform to Hero, Advanced Hero, browser smoke, and any
   supported ffmpeg fallback. Captions, graphics, faces, and source-native text
   collision boxes must consume the returned output-space transform.
5. Include strategy, numeric bounds, trajectory digest, and transform version
   in render input, manifest, QA, final review, delivery, and cache identity.

**Required tests:** 16:9→9:16 contain, center crop, valid/invalid face-follow,
manual trajectory, B-roll crop, exact safe bounds, no unintended bars, and cache
miss/invalidation when any transform value changes.

**Stop gate:** decode first/middle/last frames from both Hero and Advanced Hero;
verify the source aspect ratio is preserved for contain and the intended subject
fills the frame for delivery. Any distortion, silent fallback, or coordinate
drift blocks the next phase.

### Phase 2 — make caption and source-text layout contract-complete

**Purpose:** make readable captions and optional typography use the same final
coordinate system without duplicating baked source text.

1. Decide the versioned style contract fields: safe margins, font identity and
   file hash, contrast mode, caption width, line height, entrance/exit frames,
   emphasis limit, and locale shaping mode.
2. Either wire every field into `CaptionPlate`/layout or remove unsupported
   fields from the contract. Fingerprinting a field that the renderer ignores
   is prohibited.
3. Replace fixed character-count wrapping with measured portrait-safe layout;
   preserve punctuation, numbers, whitespace normalization, phrase geometry,
   and RTL/CJK shaping. Keep short cues visible for a minimum readable frame
   budget without extending past the canonical cue interval.
4. Add a source-native-text evidence record from decoded frames or an explicit
   reviewed annotation. When the source already displays the hook, suppress or
   reposition the generated hook; never hide required source content.
5. Keep baseline captions, active-word emphasis, typography cards, callouts,
   and diagrams as separate layers. Render each spoken phrase exactly once.
6. Record font availability and hashes. A missing or changed font is a
   deterministic failure/cache miss, not a silent system-font substitution.

**Required tests:** English, French, Japanese, shaped Arabic, punctuation and
currency, leading whitespace, short-word first/last frames, duplicate phrase
rejection, source-title collision, safe-region bounds, missing-font failure,
and style/cache invalidation.

**Stop gate:** decode frames at every cue start, middle, and end; confirm bright
glyph pixels, readable line widths, no duplicate phrase, no clipping, and no
overlap with face, graphic, or source-native title regions.

### Phase 3 — promote semantic editorial arcs, not only word-safe ranges

**Purpose:** prevent coherent-looking but incomplete or repetitive cuts.

1. Keep candidate mining separate from Hero editorial decisions. A selected arc
   must bind hook, body beat(s), and payoff to exact aligned words and ordered
   source ranges.
2. Add sentence/claim completeness validation: inspect punctuation, continuation
   sentences, pronoun references, and the next aligned span before accepting an
   ending. A complete word boundary is necessary but not sufficient.
3. Score and report, without claiming virality: hook clarity, setup/payoff
   relation, false-start penalty, redundancy, native-title penalty, visual
   support, mute readability, and ending completeness.
4. Reject duplicate ranges, unexplained order changes, cuts inside words, and
   target-duration padding by repetition. If a truthful payoff is unavailable,
   return `needs_review`/blocked rather than inventing one.
5. Require a concise direction brief and a validated declarative arc plan before
   Advanced render. The motion skill may advise; it may not inject executable
   renderer code or unsupported claims.

**Required tests:** incomplete-sentence rejection, continuation detection,
duplicate-range rejection, source-order preservation, jump-cut TimeMap digest,
exact frame boundaries, and cache invalidation after arc changes.

**Stop gate:** a reviewer can read the arc report and summarize the story in
   one sentence; each selected range appears once; the output ends at a
   meaningful source boundary; and the caption/audio map uses the same TimeMap.

### Phase 4 — make graphics, B-roll, and transitions purposeful

**Purpose:** add visual energy only when it clarifies the source claim.

1. Define a typed graphic-purpose registry: amount, comparison, process,
   timeline, location, object, or restraint. Each template must declare the
   evidence it needs and the claim it is allowed to depict.
2. Narrow `business_spotlight` so broad words such as “company” cannot select a
   growth chart. For the current exotic-car statement, use a truthful car/company
   illustration only if evidence supports it; otherwise choose restraint.
3. Require source span ids, output interval, region, labels, units, scale, and
   collision box for every graphic. Decimal/currency/unit strings remain exact;
   do not infer numeric meaning from loose text.
4. Require B-roll tags, asset hash, license/evidence URI, campaign-policy
   clearance, semantic relevance, and a reviewed placement. A file merely
   present in `envato/` is never auto-selected.
5. Keep transitions only at approved non-touching TimeMap boundaries. Do not add
   generic pattern interrupts, decorative motion, music, or unrelated stock.

**Required tests:** supported/unsupported template, region bounds, truthful
proportional geometry, decimal/currency fidelity, graphic/caption/face collision,
B-roll relevance and rights rejection, and no-transition single-range output.

**Stop gate:** decoded frames show the graphic entering and exiting as declared,
the visual meaning matches the spoken claim, and captions/face remain readable.

### Phase 5 — enforce cut-safe audio and event-level sound design

**Purpose:** prevent word truncation, drift, harsh effects, and speech masking.

1. Stage picture and source speech from one ordered integer-microsecond TimeMap;
   never create a second millisecond/float timeline.
2. At every cut, assert the boundary is outside a forced word and decode the
   first/last frame and audio window around the cut. Preserve complete phonemes;
   reject abrupt starts, clipped tails, and accidental filler sounds.
3. Use the declared audio policy: preserve source when narration is absent,
   duck only under an explicit narration/SFX plan, reject short narration, and
   never silently stretch, loop, or truncate it.
4. Measure final integrated LUFS, true peak, LRA, silence, channel layout, and
   per-event RMS/peak. Add a speech-masking/ducking assertion around each SFX.
   Keep the target at `-16 LUFS ±1.5`, true peak ≤`-1.5 dBTP`, and fail near
   silence.
5. Bind source hash, narration hash/duration/script/model, SFX hashes, gain
   envelopes, and mix-policy version into cache identity and stale approval
   invalidation.

**Stop gate:** decoded audio/video durations and PTS align, every cut preserves
   speech, and event windows remain comfortable and intelligible. A full-file
   LUFS pass alone is insufficient.

### Phase 6 — make decoded review evidence a hard production gate

**Purpose:** make technical and viewer-facing proof reproducible.

For every real MP4, generate an ignored review bundle containing:

1. MP4 SHA-256 and complete `ffprobe` JSON;
2. `ebur128`, true-peak, silence, channel, and sample-rate reports;
3. frames at first/last, each cue start/middle/end, every cut, graphic/B-roll/
   SFX interval, and final second;
4. contact sheets and transform/safe-region/collision measurements;
5. caption coverage, duplicate, source-native-text, and shaping results;
6. repeated-range/perceptual-similarity findings;
7. OCR output only when the engine and language pack are installed, otherwise an
   explicit unavailable record;
8. source, asset, license, direction, arc, TimeMap, style, cache, QA, and
   final-review bindings;
9. a human checklist with a final-review id bound to the exact artifact hash.

**Stop gate:** missing or stale evidence blocks QA/delivery. A technical pass
cannot be promoted without a human decision on the exact encoded artifact.

### Phase 7 — integration, cache, and stale-evidence audit

1. Trace the new transform, caption, arc, graphic, and audio fingerprints through
   Hero, Advanced Hero, campaign production, resume, cache hit, forced rerender,
   browser render, and fallback render.
2. Verify a changed source hash, alignment/model evidence, TimeMap, arc, style,
   font, asset/license, audio policy, or renderer recipe creates a new artifact
   identity and invalidates QA, effective final approval, and package reuse.
3. Verify a failed promotion leaves the last verified package intact.
4. Preserve old artifacts as immutable records; never reinterpret them under new
   style defaults.

**Stop gate:** cache behavior and stale approvals are demonstrated with both
   hit and miss cases, and no approval can authorize a newly styled artifact.

### Phase 8 — real-source proof and independent review

1. Render the same authorized excerpts through Hero and Advanced Hero for fair
   before/after comparison. Include a multi-cut arc, explicit contain review,
   portrait-fill delivery, a purposeful native graphic, a restraint case, and a
   real SFX case.
2. Run targeted tests, then `./scripts/validate.sh`, renderer lint/typecheck/
   tests, schema check, doctor, and all relevant verify commands. Record exact
   counts, skips, paths, hashes, elapsed times, and limitations.
3. Decode and inspect complete clips with audio, not only stills. Record source
   spans, renderer/backend, profile/recipe, and human findings.
4. Request independent code and visual review. Do not merge the draft PR, create
   an approval, publish, or claim production readiness automatically.

**Final gate:** status can move from BLOCKED only when geometry, caption
coverage, semantic arc, graphic relevance, audio event quality, decoded proof,
rights/provenance, cache invalidation, and human review all pass for the exact
artifact being delivered.
