# Round 18 validation

Branch `round-18-campaign-ingestion-multilingual-voice-envato` starts from `646c805fc4490042597c173f468c1e6ed3a1d32d`. SQLite stays at schema version 6. No migration was added.

## Sources

Only these two files were downloaded. Both are under 200 MB. They are not in Git.

| File | Drive id | Bytes | SHA-256 |
| --- | --- | --- | --- |
| Before They Were Famous | `12RKu2wuIgCccBpcwjhlbzEUM7lEt8vwN` | 180882018 | `abe817eb72bdd67980de1b6a945858043ffead6567585d45b3ccdf1edfd08a89` |
| The Great American Secret | `1IzZ6Klx6_y6stfhpa2q2Cf9qIK92eeim` | 163530208 | `495ae005f3ec2e7365a6baf57abc1e0c57529860dfa090cc3cb449da160b9ba8` |

ffprobe:

- Before They Were Famous: h264 1920x1080, 30000/1001, aac 44100 Hz stereo, duration 587.743492 seconds.
- The Great American Secret: h264 1920x1080, 24000/1001, aac 44100 Hz stereo, duration 835.732608 seconds.

Not downloaded, `download_status = not_selected_for_round_18`:

- `Copy of YTDown.com_YouTube_OG-Cuicide-In-The-Building-with-Antoine-_Media_9UQaKdtK0bM_001_1080p.mp4`
- `Antoine - Sept 1.mp4`
- `Antoine Septemberr 3.mp4`

Rights evidence is the campaign guide plus an explicit operator confirmation. Drive folder membership is not rights evidence. Newest-footage priority stays `needs_operator_clarification`.

## Policy

`external_black_box_ai_tool` is blocked. `clipforge_native_editor` is allowed. Reviewed native captions are allowed. Glow, aura, skull, and emoji captions are blocked. A caption without review is `needs_operator_confirmation`.

## Envato MCP

Live `initialize` against `https://mcp.envato.com/mcp` connected. Provider version `3.2.4`. Advertised tools include `search_stock_video` and `search_items`. Authentication is delegated. No token was stored.

A live `search_stock_video` for `office desk`, vertical, 1080p, returned five item-page URLs. Item ids, durations, formats, and direct download URLs were absent and were left null. Every row is `blocked` with `outside_media_prohibited_by_campaign_policy`. Request files:

- `docs/operations/assets/antoine-sallis/asset_download_requests.json`
- `docs/operations/assets/antoine-sallis/asset_download_requests.md`

Envato did not download a file. None of those assets entered a render.

## VoiceStudio and languages

`CLIPFORGE_VOICESTUDIO_URL` and `CLIPFORGE_VOICESTUDIO_LIVE_SMOKE` were unset. The live sidecar was not contacted. Fake narration covers the disabled plan, a successful mix, a changed script, and cache behavior through the existing generator.

Profiles exist for `en-US`, `en-GB`, `fr-FR`, `es-ES`, `de-DE`, `ar`, and `ja`. Arabic is RTL. WhisperX alignment is `not_claimed` outside English. Non-English Antoine output is `needs_operator_confirmation`. `zh-CN` is `unsupported_language`.

## Publishing

External platform publishing stays deferred. It does not block technical readiness.

## Local commands

Both full pytest runs used `uv run pytest -q --tb=line -p no:cacheprovider`.

| Run | Result |
| --- | --- |
| First | 417 passed, 1 skipped, 0 failed |
| Second | 417 passed, 1 skipped, 0 failed |

`uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy` passed. mypy checked 219 source files. `uv run clipforge schema check` matched `schemas/generated`. `uv run clipforge doctor` reported 10 pass. Schema version stayed 6.

`pnpm --dir apps/renderer lint`, `typecheck`, and `test` passed. Vitest ran 23 tests.
