# Round 20 validation

Round 20 starts from merge `75f1553da04d6703fea1f7861dcd2dd999f4dafc` on branch `round-20-campaign-production-multilingual`. SQLite stays at schema 6. Contract `schema_version` stays `1.0.0`. No migration was added. External platform publishing stays deferred and is not a gate.

This file records commands and measured identities. It does not store credentials, cookies, bearer tokens, or filesystem paths.

## Local checks

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

Local checks on the integrity fix passed: ruff, format, mypy, schema check, and doctor. Pytest: 470 passed, 1 skipped. Renderer: 23 tests passed. The corrected commit `535dde0c2b6fa3f7ead6c57d63d8a2bd413a8a89` then passed both self-hosted runs. Push CI: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37334872752. Pull-request CI: https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/37334878071. Each run completed analytics, benchmark, media, python, review, candidate, renderer, hero, vision, transcription, and preview. A campaign run is not treated as succeeded until package files, reviews, producer jobs, and symlink confinement have been rechecked.

## Campaign run

`clipforge campaign plan` does not insert jobs. `clipforge campaign run` for `antoine-sallis` reused the verified artifacts for both selected sources. A second run returned the same document. The narration probe was not called. One `campaign_production` job was inserted on the first run and none on the second. `verify` returned PASS.

| Field | Value |
| --- | --- |
| Campaign run | `018328af-e84b-4274-be72-41f4685c7945` |
| Evidence fingerprint | `e3d7f2882e9a8a6d9d2f8a74075ad6b8d30681dcae4c1ec1ab51b394e345d706` |
| Language | `en-US` |
| Alignment | WhisperX `3.4.5`, `WAV2VEC2_ASR_BASE_960H`, checkpoint `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d` |
| Narration policy | enabled for `src-before-famous`; `narration_not_requested` for `src-american-secret` |
| Final status | `succeeded` |

| Source | Delivery | Manifest SHA-256 | Candidate | QA set |
| --- | --- | --- | --- | --- |
| src-before-famous | `e5a07bd9c23e489c0c5228a21a568c79` | `80ff81a1eb571c2221c2acdf4e20632eebeadf07bdf16b8002682ab84bd50ea7` | `a6b6e6cd-b5e7-5dd7-8ec2-05967b5beddd` rank 1 score 0.928161, source 117610000–136090000 µs | `11c825cb-d7af-4244-909c-619d06b925f1` / `892524068c362610bae348a4e9c44825fe6cde63a6785314596fb0e96d17961b` |
| src-american-secret | `34a99657b1912b094a59260f959a39c0` | `06f525c3b16df35e9ba492bc663a56a6415fe5f524ef21060f5ec3bdde81af94` | `a947bea0-0089-5293-a926-a09dda2aac01` rank 1 score 0.944075, source 4610000–23390000 µs | `80910ff8-fa0e-425f-b3e2-739723e530d8` / `7809f2f4c774375212d18339b87e66a3de1b49e40863143f41677af1eec41b40` |

Narration artifact `18e63eb2-fa0e-4c20-a603-2e26066b4af7`, audio SHA-256 `bac1ab0aed6316fe28060c5f95f10b9260cbd860c523b382bb05edc81ddbdc97`. Engine `kittentts`, model `KittenML/kitten-tts-mini-0.8`, revision `c02725660cea441db4c383af69f1f26f5cd00947`, license Apache-2.0, voice `expr-voice-2-f`, script `Café costs $12.50 today.` The manifest contains no absolute path, `file:` URI, or secret-like token. Both sources recorded `cache_status: hit`. Reviews `365a81c0-1e3b-4357-ae8e-59c3d98d5326` and `4668bc1e-2b0e-4e38-abb4-809258219f33` were the existing approved rows. The runner did not insert a new approval.

## Language capability

| Tag | Alignment | Narration |
| --- | --- | --- |
| en-US | verified live WhisperX | verified live KittenTTS |
| en-GB | verified live WhisperX (same English checkpoint) | `locale_not_smoked` |
| fr-FR, es-ES, de-DE | `alignment_not_claimed` | `unsupported_language` |
| ar | `alignment_not_claimed`, RTL logical order | `unsupported_language` |
| ja | `alignment_not_claimed`, character wrap | `unsupported_language` |
| zh-CN | unsupported | unsupported |

No Arabic or Japanese aligner was installed. Captions for those languages keep the source characters and do not claim word timings. `FakeForcedAlignment` is not used by a production campaign.

## VoiceStudio

The loopback service reported version `0.5.7` and protocol `voicestudio.speech.v1`. `kittentts` was available, CPU-only, 24000 Hz, mono, English, and not a cloning engine. `omnivoice` was also available and was not used: its display name is the `k2-fsa/OmniVoice` family, which this project does not treat as commercially permitted. No available engine advertised Arabic or Japanese.

A live `POST /v1/audio/speech` with engine `kittentts`, voice `expr-voice-2-f`, language `en`, and the script `Café costs $12.50 today.` returned HTTP 200, `audio/wav`, 242078 bytes, SHA-256 `b941ab15deb55b08a805853f22c2a1b53b5f09b0928dae718bb98be93a02e2e9`. That hash differs from the campaign-bound artifact. The new bytes were not inserted into the campaign and were not copied into a delivery. The service was stopped after the smoke. Nothing was left listening on port 3900.

## Envato

The live search flags were unset, so this round did not send a new MCP request and did not rewrite `asset_download_requests.json` or `asset_download_requests.md`. The Round 19 search remains the last live record: provider 3.2.4, tool `search_stock_video`, query `office desk`, filters mapped to categories, orientation, `1080p (Full HD)`, and duration bounds. A container filter was rejected before `tools/call`. Direct download URLs stayed null, and campaign policy blocked every row. Round 20 tests reject a blocked hit, a remote URL, and a hit with no license evidence before it can enter a render. An Envato miss does not fail a campaign that does not need outside assets.

## Integrity correction

A later review found that manifest hashes alone accepted a corrupt MP4, a review for another artifact, a symlink parent, and a cache hit that did not re-read the files. The corrected runner loads the publish package, checks every listed file and `checksums.sha256`, requires succeeded producer jobs, and binds the candidate review to the current preview artifact. The hero approval must match the current hero or advanced artifact.

On the restored authorized files, campaign run `018328af-e84b-4274-be72-41f4685c7945` verified. A second run was a cache hit and sent no narration request. Replacing one byte of the src-before-famous delivery MP4 made the next run `partial` and stopped that source from staying `succeeded`. The original video bytes were restored. Their SHA-256 is `c1a8a90f0cacc21025a372ae9198de3cd352999792b90f7172a7817ef7cf84b5`.

## Recovery

Unit tests cover a missing QA file, `resume` of only that source, cancellation of one source, a changed source hash that fails one source and keeps the other, symlink and traversal rejection, stale alignment, QA, narration, and delivery bytes. The long-source Remotion regression still asserts `media_trim_frame` 0 on the staged span. Browser concurrency in the campaign document is 1.

## Readiness

| Area | State |
| --- | --- |
| Technical checks on this machine | passed |
| Campaign run | succeeded for both selected sources |
| Local delivery | both existing packages verified and reused |
| Language capability | English alignment and en-US narration are live claims; Arabic and Japanese alignment are not claimed |
| VoiceStudio | live English KittenTTS smoke passed; Arabic and Japanese are unsupported |
| Envato discovery | policy gate tested; live search not repeated |
| External publishing | deferred |
