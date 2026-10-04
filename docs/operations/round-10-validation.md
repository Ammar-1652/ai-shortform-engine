# Round 10 validation

Date: 2026-10-04. Branch `round-10-advanced-hero`. Started from Round 9 merge `57980d6848728a7a7e218d58d311e6db49db7219`. Merged on main as `81d49fff27f6ee8a2765746fc9054ac3e27a55ba`.

## Scope

Advanced Hero drafts are a new artifact, `advanced_hero_draft_set_json`, profile `advanced-hero-v1`. Hero v1 manifests are not rewritten. Envato is not implemented. Music is rejected. Faces are not speakers.

Commands:

```text
clipforge hero advanced doctor
clipforge hero advanced plan SOURCE_ID CANDIDATE_ID
clipforge hero advanced render SOURCE_ID
clipforge hero advanced list SOURCE_ID
clipforge hero advanced show SOURCE_ID CANDIDATE_ID
clipforge hero advanced verify SOURCE_ID
```

Review routes:

```text
GET /api/advanced-hero-review
GET /media/advanced-hero/<candidate_id>
```

## Production behavior

`clipforge hero advanced render` selects `RemotionAdvancedRenderBackend`. Tests that need a fast encoder pass `FakeAdvancedRenderBackend`. The advanced review page offers `approved`, `rejected`, and `changes_requested` with no preselected radio. Asset confinement is lexical and rejects same-content symlinks. Contain framing and SFX gain are applied by `AdvancedHeroDraft`. A render revalidates the current Hero approval and producer bindings before inserting `advanced_hero_render`.

Chrome proof:

```text
uv run pytest tests/test_advanced_hero_chrome.py -q
```

## Checks

`uv run ruff check` and `uv run ruff format --check` passed. `uv run mypy` reported no issues in 149 source files. `uv run pytest` passed 318 tests. A remote license-evidence URL is rejected before an advanced render job. Diagram labels and asset display names that contain HTML are returned as JSON text, and the review page assigns them with `textContent`. `uv run clipforge schema check` matched `schemas/generated`. `pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed (23 Vitest tests).

`tests/test_advanced_hero_chrome.py` calls `render_advanced_drafts` with no injected backend, which selects Remotion. The render log contains `bundleSeconds`. ffmpeg decodes frames from that MP4. The center pixel is red during the B-roll interval and green after it. The top of the frame is the neutral-dark contain bar. The diagram region is magenta on the left and cyan on the right. The typography plate is yellow. `Café` and `$12.50` are in the render input and on the plate. The output is H.264, AAC, `yuv420p`, 1080×1920, and 30/1. The render input records SFX gain `-6` dB and `broll_source_in_us` 0. The advanced review page in Chrome shows B-roll, SFX, typography, diagram, and emphasis facts, saves `rejected`, `changes_requested`, and `approved`, reloads the effective decision and history, and rejects a stale set id.

Push CI on `bd66bdd` failed because a page reload closed the Chrome debugger socket. The Hero review smoke then read an empty result, and the advanced review smoke received "Inspected target navigated or closed". The preview job's Remotion render smoke had already passed. The smokes now reconnect to the same page and wait until the new document shows the saved decision.

That reload fix is `f808994a3b3007bca923ea566d39be328554f1a6`. Push CI https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37161495061 and pull request CI https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37161497840 both succeeded.

## Limitations

- No Envato search or download.
- No publishing, music, analytics, or automatic approval.
- No full-source WhisperX.
- No speaker attribution or face recognition.
- Unit tests inject `FakeAdvancedRenderBackend`. Production render uses Remotion.
- The production renderer implements `contain`. Other reframing strategies fail before a job.
