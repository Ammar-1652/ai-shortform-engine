# Round 30 validation

Branch `round-30-multilingual-alignment-production`, started from `4d9254f52891284a702334e20b762a50ae9b0d2a`.

## Result

Sine-wave runs and tone runs are not speech-alignment evidence and are withdrawn. `verified_live` requires the current external speech file and the current measured model. `validate_current_alignment_evidence` is the shared check for Hero plan, Hero render, Hero verify, advanced Hero planning, publish plan, publish export, publish verify, final review, campaign production, campaign resume, campaign cache validation, and delivery verification. A stored alignment JSON cannot authorize a new approval or a package after the speech file or the model changes. Missing evidence is `speech_evidence_missing`. A changed file or WAV fact is `speech_evidence_changed`. A changed model, revision, manifest, WhisperX version, locale, transcript hash, ASR hash, or TimeMap hash is `stale_alignment`. The previous package stays in place when verification fails. A missing root, a missing file, a JSON row, a catalog constant, a tone, a sine wave, noise, or silence stays non-live. en-US, fr-FR, and ja are `verified_live` only when their own eSpeak NG 1.52.0 files and measured models both match. en-GB uses the English checkpoint and has no speech record, so it stays `available_not_smoked`. Full-source alignment is `not_configured`. Selected-clip `hero align` is the production path. Spanish and German stay `model_missing`. Arabic stays `alignment_not_claimed`. Tesseract is not installed on this machine, so OCR was not run for Arabic, Japanese, French, or English. Those four caption windows were checked from decoded HeroDraft and AdvancedHeroDraft frames: safe-area bounds, caption-band ink, and a variance check that rejects a blank plate or a flat rectangle. Arabic ink sits on the right side of the caption band. This is raster proof only. It is not OCR proof.

## Languages

| Locale | Alignment status | Model | License |
| --- | --- | --- | --- |
| en-US | `verified_live` only when `en-speech.wav` matches the packaged record and the measured English model | `WAV2VEC2_ASR_BASE_960H` revision `3.4.5` | Apache-2.0 |
| en-GB | `available_not_smoked` | same English checkpoint, no separate speech record | Apache-2.0 |
| ja, ja-JP | `verified_live` only when `ja-speech.wav` matches the packaged record and the measured snapshot; otherwise `available_not_smoked` or `model_missing` | `jonatasgrosman/wav2vec2-large-xlsr-53-japanese` revision `cf031e020336460d15a417eba710bbc5bb43be9a` | Apache-2.0 |
| fr-FR | `verified_live` only when `fr-speech.wav` matches the packaged record and the measured snapshot; otherwise `available_not_smoked` or `model_missing` | `jonatasgrosman/wav2vec2-large-xlsr-53-french` revision `7c79e105a6525d38e1e69f640b974b4a679723cc` | Apache-2.0 |
| es-ES | `model_missing` | `jonatasgrosman/wav2vec2-large-xlsr-53-spanish` revision `96d7e9b4e4a78af515a3c6d3cee7c0826045d276` | Apache-2.0 |
| de-DE | `model_missing` | `jonatasgrosman/wav2vec2-large-xlsr-53-german` revision `4b8a02957378d0f2da2ef74091156b032c485a89` | Apache-2.0 |
| ar | `alignment_not_claimed` | none | not applicable |
| zh-CN | `unsupported_language` | none | not applicable |

English checkpoint SHA-256 remains `488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d`. The Japanese checkpoint SHA-256 is `4f6821dcd79770fcd4c11487c4ee5c040b3a7e1863425224014ba5ea8fbc1b67`. The French checkpoint SHA-256 is `2fc4760bab7bf7d0d6c06e9b7f829a27a3e66eefee3733f53c88dbedf6607f2e`. `VOXPOPULI_ASR_BASE_10K_*` is refused.

Narration stays en-US KittenTTS `KittenML/kitten-tts-mini-0.8`, revision `c02725660cea441db4c383af69f1f26f5cd00947`, voice `expr-voice-2-f`, license `Apache-2.0`. Other locales fail before a job.

## Behavior

A cache hit requires the source hash, ASR hash, transcript hash, candidate id, TimeMap digest, locale, model id, revision, checkpoint manifest, provider version, and alignment recipe. A changed value invalidates the alignment, Hero plan, QA, final approval, and delivery. One source with an unsupported or missing model fails alone. Resume retries that source. Final approval stays human. Local delivery stays blocked without an effective final approval.

Caption fixtures keep Arabic order, Japanese characters, and Latin currency tokens. They are fixtures, not live alignment evidence. The production Hero compositions render `CaptionPlate`. Whop MCP and external publishing stay deferred. SQLite schema stays 6. Contract `schema_version` stays `1.0.0`.

## Spoken production smoke

The audio is eSpeak NG 1.52.0 synthetic speech, 22050 Hz mono, kept outside the repository under `CLIPFORGE_SPEECH_EVIDENCE_ROOT`. The packaged index stores the relative filename only. It is not a tone, noise, or silence. A machine without those files reports a non-live status. The operator restores live evidence by placing the measured WAV files in that directory and exporting `CLIPFORGE_SPEECH_EVIDENCE_ROOT`. Do not commit the WAV files. The production commands were `clipforge hero doctor`, `clipforge hero align SOURCE CANDIDATE --language LOCALE`, `clipforge hero plan`, `clipforge hero render`, and `clipforge hero verify`. The offline rerun set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_DATASETS_OFFLINE=1`, did not pass `--allow-model-download`, and a repeated align returned the same alignment id. English duration is 1,685,260 microseconds from the bytes after the data header. The declared data-chunk size in these files is a placeholder.

| Locale | Transcript | Tokens | Audio SHA-256 | Manifest SHA-256 | Alignment SHA-256 |
| --- | --- | --- | --- | --- | --- |
| en-US | hello world this is a test | 6 | `3df575324d82909d4314bf67364f4fa3cc58a9e0838b20257166b2d0bb2ab57c` | `9aa509c3864875cedd4e787a1c2065617ab3385aeac49bc2d17982aec79146c9` | `66b11af77a6869c90878af3473edb82669621bf0df7bc5589f0a2df395b8e256` |
| fr-FR | bonjour le monde ceci est un test | 7 | `a3e9c785cf7a4a84c6af80e944b134eab161d3459d86153249d6d8a02682e254` | `a335fa7cef1be2b74b408940a8a9e16ec89bce5c2d0267832cba739b88c31cc1` | `aece0c6accc98004794c59c1298d39c8b5e1b7d963655cc4ada508d94fa63af6` |
| ja | これはテストです | 4 | `7cefeb57a7ecdec014512b351d6e668893ee42ca8fcf052c067ee8dab5379934` | `db223cabb82fce1f671fc98f89c507006a29f4dc22ec429ec28d61cac16127ad` | `abbffd62cb5daba50d5b2ea1bdda801ecac0432cbdb6b6b0277cac1d3e251145` |

WhisperX is 3.4.5 on CPU. Word intervals are positive, ordered on the output clock, and different from the provisional transcript times. The stored locale is the requested locale. The repair rerun used the external files, set `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and `HF_DATASETS_OFFLINE=1`, and did not pass `--allow-model-download`. A repeated align returned the same alignment id for each locale: en-US `e388a740-1015-486c-83aa-93d309ea9857`, fr-FR `66e901d9-137b-435d-8a63-7f597bf33c95`, and ja `684c95a6-1aee-4ef2-a6f1-942d4f08bbf3`. `hero plan`, `hero render`, and `hero verify` passed. The English render was a cache hit. The French and Japanese renders wrote new hero sets and verified. The renders stayed outside the repository. Earlier sine-wave numbers are not evidence.

## Not smoked

Spanish and German stay `model_missing`. Arabic stays `alignment_not_claimed`. en-GB alignment has no speech record. No narration smoke was run for those locales. KittenTTS remains en-US only. Full-source WhisperX stays `not_configured` and does not emit even spans.

CI stays offline. It does not download models. A machine without the cached weights reports `model_missing` even when this speech record is present.

## Local validation

`./scripts/validate.sh` passed: ruff, mypy on 260 source files, pytest `710 passed, 2 skipped`, schema check, renderer lint, typecheck, Vitest `33 passed`, and `clipforge doctor` `10 pass, 0 warn, 0 fail`. Tesseract was not installed, so the caption browser smoke checked decoded pixels and did not claim OCR. SQLite schema stays 6. No model download was requested. No WAV, model weight, render, database, or secret was committed.
