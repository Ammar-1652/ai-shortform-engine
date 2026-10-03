# Round 10 validation

Date: 2026-10-04. Branch `round-10-advanced-hero`. Started from Round 9 merge `57980d6848728a7a7e218d58d311e6db49db7219`. The pull request is a draft and is not merged.

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

## Checks

`uv run ruff check` and `uv run ruff format --check` passed. `uv run mypy` reported no issues in 149 source files. `uv run pytest` passed 306 tests. `uv run clipforge schema check` matched `schemas/generated`. `pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed (22 Vitest tests).

`tests/test_advanced_hero_chrome.py` renders `AdvancedHeroDraft` through Remotion in local Chrome. The render log contains `bundleSeconds`. ffmpeg decodes frames from that MP4. The center pixel is red during the B-roll interval and green after it. The diagram region is magenta on the left and cyan on the right. The typography plate is yellow. `Café` and `$12.50` are in the render input and on the plate. The output is H.264, AAC, 1080×1920, and 30/1. The advanced review page in Chrome shows B-roll, SFX, typography, diagram, and emphasis facts, saves a decision, reloads it, and rejects a stale set id.

Push CI on `bd66bdd` failed because a page reload closed the Chrome debugger socket. The Hero review smoke then read an empty result, and the advanced review smoke received "Inspected target navigated or closed". The preview job's Remotion render smoke had already passed. The smokes now reconnect to the same page and wait until the new document shows the saved decision.

CI run URLs are added when the draft pull request finishes.

## Limitations

- No Envato search or download.
- No publishing, music, analytics, or automatic approval.
- No full-source WhisperX.
- No speaker attribution or face recognition.
- The deterministic encoder used by tests is ffmpeg. The Remotion composition is `AdvancedHeroDraft`.
