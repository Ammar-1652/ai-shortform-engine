# Tarteel review-trio repair execution ledger

Updated 2026-10-24. This records current code and evidence, not editorial
acceptance. The detailed exit criteria remain in
[the next-round runbook](tarteel-review-trio-system-repair-next-round.md).
The current audit and next-round decision record is
[tarteel-review-trio-audit-2026-10-24.md](tarteel-review-trio-audit-2026-10-24.md).
The latest audit and follow-up execution steps are in
[tarteel-review-trio-followup-plan.md](tarteel-review-trio-followup-plan.md).
The complete phase-by-phase workflow, gate matrix, recovery rules, and
checkpoint contents are in
[tarteel-review-trio-complete-resolution-workflow.md](tarteel-review-trio-complete-resolution-workflow.md).

## Baseline and authority

- Branch: `round-35-quran-caption-verification`; starting HEAD:
  `4ac0748bbf8efa4dc7f66f6de5b6904945bd824e`.
- `origin/main` at the start of this audit:
  `989bf5d6ec27878d46505dc09becedfc848cd749`.
- Draft PR #37 is open and stacked on `round-34-envato-material-prep`.
  Nothing in this ledger means the branch has merged to main.
- The six ignored `var/work/campaigns/Tarteel/review-trio` MP4s are historical
  diagnostic outputs, not new service evidence or delivery candidates.
- The worktree remains intentionally dirty with this round's implementation and
  generated schemas. No reset, force-push, or history rewrite was performed.

## R1: Advanced browser authorization

The service now issues a candidate receipt after checking the canonical batch,
staged media and renderer dependency map. The worker validates the same map,
the exact input, authorized output and owned frame range before importing
Remotion. Candidate receipts persist across a multi-candidate run. The
canonical batch must have exactly one item for the candidate.

Focused authorization tests currently cover full render, video/audio units,
changed input/digest/media/output, moved/copied runs, symlinks, missing
receipt, dependency mismatch, ambiguous canonical candidate and retained
per-candidate audio evidence. Browser and full-suite evidence are recorded
below. The receipt is not a cryptographic signature against the local owner.

## R2: Caption and audio evidence

Caption preflight now checks exact forced-word ids, order, microseconds and
frames. The service writes a `CaptionAudioCoverageReport` and decoded PNGs
from the final MP4, including first/last, cue edges and every word-highlight
edge. QA and clean-browser cache lookup check report, PNG, render-input,
encoded-media and staged-audio bindings. Positive sub-frame cues follow the
renderer one-frame display rule. A generated encoded-MP4 regression checks
correct binding and rejection of altered frame/audio hashes.

The existing typed speech-review sidecar is now loaded by the production
service when present, checked against source/ASR/transcript hashes, required to
cover every retained source range, copied into the candidate evidence folder,
and bound into the caption report. A missing inventory remains
`insufficient_evidence`; malformed, stale, duplicate, or incomplete inventory
fails closed. Decoded glyph/color analysis and a real Tarteel service report
are still required before R2 can exit.

## R3–R8

- R3: the typed `OverlayExclusionEvidence` contract is now implemented and
  bound to clean Python and Remotion render inputs. It requires transformed
  face, child/body, tablet, caption, context, source-logo, watermark, and
  platform-rail records across entrance/hold/exit/maximum CTA samples. Branding
  measurement samples each retained source range (not the min/max envelope),
  and staging rejects changed reviewed CTA timing/geometry/logo visibility.
  No real Tarteel sidecar exists yet, so clean Tarteel rendering remains
  correctly blocked until reviewed evidence is supplied.
- R4: the service now requires an accepted, hash-bound `editorial-arc-review.json`
  for clean Tarteel planning, validates its representative frame hashes after
  the persisted arc bytes are known, and carries its digest into the plan and
  render input. No accepted real-source sidecar or shot strip has been
  produced yet, so R4 remains open for source evidence.
- R5: ordinary Arabic correction and dialogue/reaction/nasheed coverage
  contract remain open. Quran canonical display evidence is separate.
- R6: a new coherent t33 replacement candidate has not been reviewed.
- R7: objective viewer evidence is implemented; human playback and campaign
  evidence remain open. Clean browser renders now carry a typed
  `ViewerEvidenceBundle` with decoded first/middle/last frames, 4:5 and 1:1
  crop previews, contact sheets, measured loudness/true peak, and hashes for
  every file. QA/cache validate those bindings. `HumanPlaybackReview` is never
  generated automatically. Technical QA no longer requires mutating that
  immutable bundle; clean final approval now requires a separate append-only
  `HumanPlaybackReview` sidecar bound to the exact MP4, source and plan, with
  explicit audio and muted observations. No real campaign watch has been
  recorded.
- R8: no new real-source, multi-cut service render or six reviewed variants
  has been produced by this execution. Historical media must not substitute.

## Validation record

- Earlier full `./scripts/validate.sh`: `823 passed, 2 skipped, 1 failed`;
  the round-29 browser fixture lacked the then-new authorization. That fixture
  was repaired and passed alone. This does not constitute a later full pass.
- A later affected browser group: `30 passed, 1 failed`; the round-30
  caption-free Advanced render lost its Chrome target. The cause is not yet
  established. Do not label it an authorization failure or an OOM.
- Current focused unit group after the latest changes:
  `uv run pytest tests/test_caption_evidence.py tests/test_render_authorization.py
  tests/test_caption_coverage.py -q` → **27 passed**.
- `uv run mypy` → **278 source files checked, no issues**.
- `uv run ruff check` on the changed R1/R2 Python files → passed.
- Full `./scripts/validate.sh` rerun from the current head: **842 passed, 2
  skipped, 3 failed in 900.50s**. The failures were browser-resource
  failures, not assertion regressions: two rough-preview tests reported
  Chrome `Page crashed`/30-second browser setup timeout while the host had
  only ~210 MiB available, and the Round-30 caption browser render timed out
  after Chrome target-close retries. The isolated browser pair immediately
  afterward passed (`2 passed`), and the Round-30 test alone passed. The host
  has a long-running Firefox session consuming multiple GiB; the full-suite
  result is therefore not a clean production validation. No test was skipped
  or weakened to hide this resource blocker.
- `uv run pytest -m 'not browser' -q -ra`: **exit 0**; the only skips are the
  documented VoiceStudio live smoke and Whop live smoke. The renderer lint,
  typecheck, Vitest (59 tests), schema check, doctor, and isolated browser
  checks are also green. Browser coverage still needs a clean host with the
  long-running Firefox session closed before this can be called a full green
  validation.
- Affected regression group after the viewer-evidence writer/QA/cache changes:
  `tests/test_viewer_evidence.py`, `tests/test_render_authorization.py`,
  `tests/test_caption_evidence.py`, `tests/test_qa_caption_coverage.py` →
  **24 passed**; `tests/test_advanced_hero.py` → **all passed** after fixing
  resumable artifact-row reuse. Renderer lint/typecheck/Vitest remain green.
- Latest range-scoped branding and speech-inventory regressions:
  `tests/test_tarteel_overlay_direction.py` and
  `tests/test_caption_evidence.py` → **18 passed**; `tests/test_advanced_hero.py`
  → **all passed** after the reviewed CTA binding and speech-review staging
  changes.
- Latest R3 exclusion contract regression group:
  `tests/test_tarteel_overlay_direction.py`, `tests/test_advanced_hero.py`,
  `tests/test_qa_caption_coverage.py`, and `tests/test_viewer_evidence.py` →
  **all passed**. Renderer lint/typecheck/Vitest remain **59 passed**. The full
  non-browser suite also exited **0** with only the two documented live-service
  skips. A full browser validation has not been rerun because the earlier host
  memory condition remains unresolved.
- Latest R4 arc-review regression group:
  `tests/test_editorial_arc.py`, `tests/test_advanced_hero.py`,
  `tests/test_tarteel_overlay_direction.py`, and
  `tests/test_qa_caption_coverage.py` → **all passed**. The combined full
  non-browser suite exited **0** again with only the VoiceStudio and Whop live
  skips. No current source-bound arc review exists under `var/work`, so the
  clean Tarteel planner remains blocked as designed.
- Latest focused speech/arc/overlay/viewer/final-playback group: **72 passed**.
  It covers exact caption text and verification, omitted reaction/nasheed,
  stale Quran/Arabic evidence, transformed CTA geometry, append-only human
  playback, stale watch rejection, and resumable render recovery.
- Renderer lint/typecheck/Vitest: **59 passed**. The affected production
  Advanced Chrome test passed **2 passed in 70.27s** after the renderer changed
  its bounded browser setup/render timeout from the default 30 seconds to 90
  seconds. The full validator log at
  `var/work/validation/tarteel-repair-20261022/validate.log` records the prior
  constrained-host result: **883 passed, 2 skipped, 1 browser timeout** before
  this targeted rerun; it was not relabeled as a green full suite.
- Final split validation after the campaign-verification precedence fix:
  `./scripts/validate.sh` completed with **870 passed, 2 skipped** in the
  mandatory non-browser process, **18 browser tests passed** in the isolated
  Remotion process, renderer **62 tests passed** across 12 files, schemas
  matched, Ruff/mypy/typecheck passed, and doctor reported **9 pass, 1 GPU
  warning, 0 fail**. The two skips are the explicitly unavailable VoiceStudio
  and unconfigured Whop live smokes. Full log:
  `var/work/validation/tarteel-repair-20261024/final/validate.log`.

- Latest role-boundary validation on the current worktree: **877 passed, 2
  skipped** in the non-browser partition, **18 browser tests passed**, renderer
  **62 tests passed**, schemas matched, mypy/Ruff/typecheck passed, and doctor
  reported **9 pass, 1 GPU warning, 0 fail**. SQLite was migrated safely to
  schema 7 and `ReviewDecision.reviewer_role` round-trips through storage.

## Restart rule

Verify Git state and the current artifact hashes before reusing this ledger.
Continue the earliest open gate. Do not create a delivery or final approval
from this partial implementation.
