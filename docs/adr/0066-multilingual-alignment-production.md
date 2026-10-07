# ADR 0066: Multilingual alignment production

## Status

Accepted for Round 30. `verified_live` requires an external speech file whose SHA-256, sample rate, channel count, and duration match the packaged speech record, and whose locale and model identity match the checkpoint measured on disk. A JSON row, a tone, a sine wave, noise, silence, a catalog constant, or a copied manifest is not evidence. A missing evidence root or file stays non-live. en-US, fr-FR, and ja can be `verified_live` only with their own eSpeak NG speech files. en-GB is not verified unless it has its own speech record. Spanish and German remain `model_missing`. Full-source alignment is `not_configured`. Selected-clip `hero align` is the production path.

## Context

Hero alignment called WhisperX with `language_code="en"` and `WAV2VEC2_ASR_BASE_960H` for every request. A missing model and an unsupported language were both reported as `alignment_not_claimed`. WhisperX's built-in French, Spanish, and German torchaudio bundles are VoxPopuli weights, which this project does not treat as commercially permitted.

## Decision

Provider lookup is a typed catalog. The stored document keeps the requested locale. Lookup uses a normalized language code: `en`, `fr`, `es`, `de`, `ja`, `ar`, or `zh`.

Statuses stay specific. `verified_live` means a real provider execution of a hashed checkpoint. `model_missing` means the model id and license are known and the weight file is not installed. `alignment_not_claimed` means this install will not claim that language. `unsupported_language` means the locale is outside the matrix. A fake provider cannot be stored as `verified_live`.

The English checkpoint expected identity stays `WAV2VEC2_ASR_BASE_960H`, revision `3.4.5`, SHA-256 `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d`. A catalog row is not proof. The worker must report the same revision, and the parent remeasures the local files before writing an alignment.

Japanese is `verified_live` only when its external speech file and this measured identity both match:

- `jonatasgrosman/wav2vec2-large-xlsr-53-japanese`, revision `cf031e020336460d15a417eba710bbc5bb43be9a`, checkpoint SHA-256 `4f6821dcd79770fcd4c11487c4ee5c040b3a7e1863425224014ba5ea8fbc1b67`

French is `verified_live` only when its external speech file and this measured identity both match:

- `jonatasgrosman/wav2vec2-large-xlsr-53-french`, revision `7c79e105a6525d38e1e69f640b974b4a679723cc`, checkpoint SHA-256 `2fc4760bab7bf7d0d6c06e9b7f829a27a3e66eefee3733f53c88dbedf6607f2e`

Spanish and German name these Apache-2.0 models and stay `model_missing`:

- `jonatasgrosman/wav2vec2-large-xlsr-53-spanish`, revision `96d7e9b4e4a78af515a3c6d3cee7c0826045d276`
- `jonatasgrosman/wav2vec2-large-xlsr-53-german`, revision `4b8a02957378d0f2da2ef74091156b032c485a89`

`VOXPOPULI_ASR_BASE_10K_*` is refused. A non-English request does not load the English checkpoint. The transcript text is not translated. Arabic stays `alignment_not_claimed` because no Arabic checkpoint has been hashed and smoked here. `zh-CN` stays `unsupported_language`.

Alignment cache identity includes the source asset, source or ASR hash, transcript hash, transcript language, locale, normalized language, TimeMap digest, provider, version, model, revision, checkpoint, recipe, and candidate scope. A stale alignment fails before Hero planning. Jump cuts align each source interval and map the result through the existing TimeMap.

Campaign production records the requested locale, provider, model, revision, checkpoint, artifact id, cache status, and blocker on each source. An unsupported locale blocks that source only. Resume retries the incomplete source. No command approves a review.

Narration stays the smoked en-US KittenTTS identity. Other locales fail before a job. The narration cache includes locale, script hash, source hash, transcript hash, provider, engine, model, revision, voice, and license.

Captions keep source characters. Latin text wraps on spaces. Arabic stays right to left. Japanese wraps by character. Plates are React text nodes.

Whop MCP and external publishing stay deferred. SQLite schema stays 6. Contract `schema_version` stays `1.0.0` because the new fields have defaults and old documents still load.

## Consequences

A language is not live because Whisper transcribed it or because a test double returned times. Promoting Japanese or a European locale to `verified_live` requires the checkpoint SHA-256, the runtime, the device, the command, the word count, and the artifact hash from a real WhisperX run. Normal runs stay offline. Only `--allow-model-download` may fetch weights, and CI does not.
