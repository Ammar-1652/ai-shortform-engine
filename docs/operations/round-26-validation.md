# Round 26 validation

Round 26 starts from merge `5ce59f0fecaf5851edf71c0cca67275b680c76cb` on branch `round-26-multilingual-alignment-narration`. SQLite stays at schema 6. Contract `schema_version` stays `1.0.0`. No migration was added.

Full-source alignment and narration are capability records. A fake provider cannot be `verified_live`. Live Whop crawling and external publishing stay outside this round. This file does not store credentials, cookies, bearer tokens, or filesystem paths.

## Commands

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run clipforge schema check
uv run clipforge doctor
pnpm --dir apps/renderer lint
pnpm --dir apps/renderer typecheck
pnpm --dir apps/renderer test
```

Local results on this branch: ruff, format, mypy, schema check, and doctor passed. Doctor reports SQLite schema version 6. Schema export wrote 187 files. Pytest: 529 passed, 1 skipped, 445 seconds. Renderer lint, typecheck, and 27 tests passed.

CI uses the Round 21 workflow: `verify-python`, then `verify-renderer-browser`, on `[self-hosted, linux, x64, clipforge]`. Feature-branch pushes do not start that workflow. Model downloads stay off. Live alignment and narration smokes stay opt-in.

## Capability matrix

| Language | Alignment | Narration |
| --- | --- | --- |
| en-US | `whisperx`, `verified_live` | KittenTTS `verified_live` |
| en-GB | same English checkpoint | `locale_not_smoked` |
| fr-FR, es-ES, de-DE | `alignment_not_claimed` | `unsupported_language` |
| ar | `alignment_not_claimed` | `unsupported_language` |
| ja | `alignment_not_claimed` | `unsupported_language` |
| zh-CN | `unsupported_language` | `unsupported_language` |

`language doctor` also prints `full_source_runtime: not_configured`, `whop_live: not_configured`, and `publishing: deferred`.

## Alignment evidence

No new WhisperX process was executed in this round. English `verified_live` remains the previously smoked checkpoint `WAV2VEC2_ASR_BASE_960H`, revision `3.4.5`, SHA-256 `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d`. Calling full-source WhisperX without `CLIPFORGE_ALIGNMENT_LIVE_SMOKE=1` returns `not_configured` and inserts no job. French returns `alignment_not_claimed` before a job. `zh-CN` returns `unsupported_language` before a job.

A fake Arabic alignment stores `مرحبا` unchanged with status `available_not_smoked`. A fake Japanese alignment stores `説明12` the same way. Neither document can be bound into Hero planning. The same source and transcript hashes are a cache hit and do not insert another job. A changed source hash or transcript hash is a new alignment id. A changed artifact fails `verify` with `corrupt_alignment`. A changed capability fingerprint fails with `stale_profile`. `verify` does not change work-tree or database bytes.

## Narration evidence

`voice languages` lists the matrix above. Requesting Arabic narration fails with `unsupported_language` before a job. en-GB fails with `locale_not_smoked`. A `k2-fsa/` model fails with `license_not_permitted`. A fake provider record stays `available_not_smoked`. The smoked KittenTTS identity (`KittenML/kitten-tts-mini-0.8`, revision `c02725660cea441db4c383af69f1f26f5cd00947`, voice `expr-voice-2-f`, license `Apache-2.0`) can be recorded as `verified_live` because that is the existing live claim, not a new generation. The same script is a cache hit. A different script is a new narration id. `narration_not_requested` does not block.

## Caption evidence

Renderer tests keep Arabic `مرحبا، 12!` in character order with direction `rtl`. Japanese `説明です。12` and `価格は１２３円です。` wrap without inserted spaces and without a line that starts with `。`. The safe box is left 64 and right 1016 on a 1080-wide frame. Markup is rejected. The plate source contains `{line}` and does not contain `innerHTML`, `eval(`, or a remote URL.

## Security

Rejected before a job or a sidecar: unsupported language, missing runtime, HTML word text, bearer text, a zero-length word, a non-matching checkpoint, a prohibited model license, and a stale script hash. The board payloads for `/api/languages` and `/api/sources/source-1/alignments` contain no `/home/` and no `file:`.

## Limits

Arabic and Japanese do not have an installed full-source aligner, so they stay `alignment_not_claimed`. KittenTTS is still English-only. This round does not crawl Whop and does not publish.
