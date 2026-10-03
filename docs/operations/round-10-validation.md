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

`uv run ruff check` and `uv run ruff format --check` passed. `uv run mypy` reported no issues in 149 source files. `uv run pytest` passed 300 tests. `uv run clipforge schema check` matched `schemas/generated`. `pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed (22 Vitest tests).

`tests/test_advanced_hero_chrome.py` renders `AdvancedHeroDraft` through Remotion in local Chrome. The render log contains `bundleSeconds`. Decoded frames show red B-roll during its interval, the green source outside that interval, magenta and cyan diagram bars, and a yellow typography plate. `Café` and `$12.50` are in the render input and on the plate. The advanced review page in Chrome shows B-roll, SFX, typography, diagram, and emphasis facts, saves a decision, reloads it, and rejects a stale set id.

CI run URLs are added when the draft pull request finishes.

## Limitations

- No Envato search or download.
- No publishing, music, analytics, or automatic approval.
- No full-source WhisperX.
- No speaker attribution or face recognition.
- The deterministic encoder used by tests is ffmpeg. The Remotion composition is `AdvancedHeroDraft`.
