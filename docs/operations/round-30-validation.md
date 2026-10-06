# Round 30 validation

Branch `round-30-multilingual-alignment-production`, started from `4d9254f52891284a702334e20b762a50ae9b0d2a`.

## Result

English, Japanese, and French alignment ran on the optional WhisperX interpreter. Spanish and German stay `model_missing`. Arabic stays `alignment_not_claimed`.

## Languages

| Locale | Alignment status | Model | License |
| --- | --- | --- | --- |
| en-US, en-GB | `verified_live` | `WAV2VEC2_ASR_BASE_960H` revision `3.4.5` | Apache-2.0 |
| ja, ja-JP | `verified_live` | `jonatasgrosman/wav2vec2-large-xlsr-53-japanese` revision `cf031e020336460d15a417eba710bbc5bb43be9a` checkpoint `4f6821dcd79770fcd4c11487c4ee5c040b3a7e1863425224014ba5ea8fbc1b67` | Apache-2.0 |
| fr-FR | `verified_live` | `jonatasgrosman/wav2vec2-large-xlsr-53-french` revision `7c79e105a6525d38e1e69f640b974b4a679723cc` checkpoint `2fc4760bab7bf7d0d6c06e9b7f829a27a3e66eefee3733f53c88dbedf6607f2e` | Apache-2.0 |
| es-ES | `model_missing` | `jonatasgrosman/wav2vec2-large-xlsr-53-spanish` revision `96d7e9b4e4a78af515a3c6d3cee7c0826045d276` | Apache-2.0 |
| de-DE | `model_missing` | `jonatasgrosman/wav2vec2-large-xlsr-53-german` revision `4b8a02957378d0f2da2ef74091156b032c485a89` | Apache-2.0 |
| ar | `alignment_not_claimed` | none | not applicable |
| zh-CN | `unsupported_language` | none | not applicable |

English checkpoint SHA-256 remains `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d`. The Japanese checkpoint SHA-256 is `4f6821dcd79770fcd4c11487c4ee5c040b3a7e1863425224014ba5ea8fbc1b67`. The French checkpoint SHA-256 is `2fc4760bab7bf7d0d6c06e9b7f829a27a3e66eefee3733f53c88dbedf6607f2e`. `VOXPOPULI_ASR_BASE_10K_*` is refused.

Narration stays en-US KittenTTS `KittenML/kitten-tts-mini-0.8`, revision `c02725660cea441db4c383af69f1f26f5cd00947`, voice `expr-voice-2-f`, license `Apache-2.0`. Other locales fail before a job.

## Behavior

A cache hit requires the source asset, hashes, locale, normalized language, TimeMap digest, provider, model, revision, checkpoint, recipe, and candidate scope. A changed value invalidates the alignment before Hero planning. One source with an unsupported or missing model fails alone. Resume retries that source. Final approval stays human. Local delivery stays blocked without an effective final approval.

Caption fixtures keep Arabic order, Japanese characters, and Latin currency tokens. They are fixtures, not live alignment evidence. Whop MCP and external publishing stay deferred. SQLite schema stays 6. Contract `schema_version` stays `1.0.0`.

## English live regression

Command: the optional interpreter `~/.local/clipforge-hero-align/bin/python` running `clipforge.hero.align_worker` with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`, and `NLTK_DATA` pointed at that environment. `allow_model_download` was false.

| Fact | Value |
| --- | --- |
| Locale | `en` |
| Fixture | local 16 kHz sine wave, not committed |
| Provider | whisperx `3.4.5` |
| Model | `WAV2VEC2_ASR_BASE_960H` |
| Revision | `3.4.5` |
| Checkpoint SHA-256 | `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d` |
| License | Apache-2.0 |
| Runtime | torch `2.14.1+cpu`, torchaudio `2.11.0+cpu` |
| Device | cpu |
| Elapsed | 6.939 s |
| Word count | 1 (`hello`, 0 to 102000 us) |
| Artifact SHA-256 | `63ded5959329ece3113b204ef4c1c38439641b55e40a6acab24474b26dbcf225` |

The worker returned the transcript token unchanged. This call did not write a Hero sidecar, so it is not an alignment-cache hit. Unit tests cover cache identity.

## Japanese live smoke

The first command allowed a download with `--allow-model-download` through `clipforge.hero.align_worker`. The offline rerun set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_DATASETS_OFFLINE=1`.

| Fact | Value |
| --- | --- |
| Locale | `ja` |
| Fixture | local 16 kHz sine wave, not committed |
| Provider | whisperx `3.4.5` |
| Model | `jonatasgrosman/wav2vec2-large-xlsr-53-japanese` |
| Revision | `cf031e020336460d15a417eba710bbc5bb43be9a` |
| Checkpoint SHA-256 | `4f6821dcd79770fcd4c11487c4ee5c040b3a7e1863425224014ba5ea8fbc1b67` |
| License | Apache-2.0 |
| Runtime | torch `2.14.1+cpu`, torchaudio `2.11.0+cpu` |
| Device | cpu |
| First elapsed | 399.598 s, including the weight download |
| Offline elapsed | 7.737 s from the local cache |
| Provider pieces | 2 (`説` 0–20000 us, `明` 20000–41000 us) |
| Collapsed transcript word | `説明`, 0–41000 us |
| Artifact SHA-256 | `406b18a938179d143a52244192c9ef7c04b62e5139974a67cc96ba9bb2118c75` |

The aligner splits the Japanese word into characters. Clipforge groups those pieces back onto the transcript word and does not rewrite the stored text. The fixture is a generated tone, not a Japanese speech recording.

## French live smoke

The command allowed one download through `clipforge.hero.align_worker` for `language_code=fr` and model `jonatasgrosman/wav2vec2-large-xlsr-53-french`.

| Fact | Value |
| --- | --- |
| Locale | `fr` |
| Fixture | local 16 kHz sine wave, not committed |
| Provider | whisperx `3.4.5` |
| Model | `jonatasgrosman/wav2vec2-large-xlsr-53-french` |
| Revision | `7c79e105a6525d38e1e69f640b974b4a679723cc` |
| Checkpoint SHA-256 | `2fc4760bab7bf7d0d6c06e9b7f829a27a3e66eefee3733f53c88dbedf6607f2e` |
| License | Apache-2.0 |
| Runtime | torch `2.14.1+cpu`, torchaudio `2.11.0+cpu` |
| Device | cpu |
| Elapsed | 487.017 s, including the weight download |
| Word count | 1 (`bonjour`, 0 to 224000 us) |
| Artifact SHA-256 | `6ef426bec2a17ac939e9667b443920066a38de2d28834b7461bb338533ca7887` |

The returned token matched the transcript word. The fixture is a generated tone, not a French speech recording.

## Not smoked

Spanish and German stay `model_missing`. Arabic stays `alignment_not_claimed`. No narration smoke was run for those locales. KittenTTS remains en-US only.

CI stays offline. It does not download models.

## Local validation

`./scripts/validate.sh` passed on this tree: ruff, mypy (258 source files), pytest `665 passed, 2 skipped`, schema check, renderer lint, typecheck, and Vitest `33 passed`, and `clipforge doctor` `10 pass, 0 warn, 0 fail`. SQLite schema stays 6.
