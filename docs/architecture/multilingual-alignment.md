# Multilingual alignment and narration

en-US, fr-FR, and ja alignment are `verified_live` only when the stored speech record matches the measured model. en-US KittenTTS remains the only verified narration. en-GB alignment has no speech record. See [ADR 0061](../adr/0061-multilingual-alignment-and-narration.md) and [ADR 0066](../adr/0066-multilingual-alignment-production.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`. The new records are sidecars.

## Capability matrix

| Language | Alignment | Narration |
| --- | --- | --- |
| en-US | `whisperx`, `verified_live` when the speech manifest matches | KittenTTS `verified_live` |
| en-GB | same English checkpoint, `available_not_smoked` | `locale_not_smoked` |
| fr-FR | `verified_live` when the speech manifest matches | `unsupported_language` |
| es-ES, de-DE | Apache-2.0 wav2vec2 catalog, evidence `model_missing` | `unsupported_language` |
| ar | `alignment_not_claimed`, RTL captions | `unsupported_language` |
| ja | `verified_live` when the speech manifest matches, character wrap | `unsupported_language` |
| zh-CN | `unsupported_language` | `unsupported_language` |

`clipforge language doctor` prints this matrix. It also prints `full_source_runtime: not_configured`, `whop_live: not_configured`, and `publishing: deferred`.

A fake aligner may be used in tests. Its document status is `available_not_smoked`. The model rejects `verified_live` when the provider id is `fake`.

## Alignment

```text
clipforge language doctor
clipforge language list
clipforge language check
clipforge language align SOURCE_ID --language LANG --transcript FILE --project PROJECT_ID
clipforge language verify ALIGNMENT_ID
clipforge language show ALIGNMENT_ID
```

`language align` fails before inserting a job when the language is unsupported or the provider is not `verified_live`. Full-source WhisperX stays `not_configured` and does not emit even spans. Selected-clip `hero align` is the production path. A normal align sets `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, and `HF_DATASETS_OFFLINE`. Only `--allow-model-download` may fetch weights.

The cache identity is the source asset id, source or ASR SHA-256, transcript SHA-256, transcript language, locale, normalized language, TimeMap SHA-256, provider, provider version, model, revision, checkpoint SHA-256, and alignment recipe. A hit returns the same alignment id only when every component matches and the producer job succeeded. Changed source bytes, transcript bytes, locale, model revision, checkpoint, provider version, TimeMap, or candidate window are a miss. `verify` and `show` do not write.

Locale spellings normalize for lookup only: `en-US` and `en-GB` to `en`, `fr-FR` to `fr`, `es-ES` to `es`, `de-DE` to `de`, `ja` and `ja-JP` to `ja`, `ar` to `ar`, `zh-CN` to `zh`. The stored document keeps the original locale. A non-English request does not load `WAV2VEC2_ASR_BASE_960H`. WhisperX's default French, Spanish, and German torchaudio bundles are `VOXPOPULI_ASR_BASE_10K_*` and are refused. The catalog names the Apache-2.0 Hugging Face wav2vec2 models as expected identity. A matching local snapshot stays `available_not_smoked` until `speech_evidence.json` records a multi-word spoken run whose manifest matches the files on disk. Spanish and German stay `model_missing` when their snapshots are absent. Full-source alignment does not run WhisperX and does not emit even spans.

Each word stores Unicode text, positive source and output durations, half-open frames, and the source and transcript ids. Words are monotonic. The service does not invent times when alignment is refused.

Hero binding accepts `verified_live` WhisperX output whose revision, checkpoint, and manifest match the measured runtime for that locale. A fake or `available_not_smoked` document is not substituted. Selected-clip alignment is the production path. Full-source alignment is `not_configured`.

## Narration

```text
clipforge voice doctor
clipforge voice capabilities
clipforge voice languages
clipforge voice generate
clipforge voice verify
clipforge voice list
```

Disabled VoiceStudio does not open a socket. KittenTTS is English-only unless a future capability response proves another language. Commercial use requires an explicit allowed license. `k2-fsa/` models are refused. Requested unsupported narration fails before a job. `narration_not_requested` does not block a campaign.

Narration cache identity is the locale, script SHA-256, source SHA-256, transcript SHA-256, provider, engine, model, revision, voice, and license. A changed script or hash is a new id. English KittenTTS is not used for Arabic, Japanese, French, Spanish, or German. Narration does not approve a candidate or a Hero.

## Captions

Arabic layout is `rtl` and does not reverse characters, transliterate, or rewrite Arabic-Indic digits. Japanese layout wraps by Unicode character, does not insert spaces, and does not leave `。` or similar closing marks at the start of a line. Latin captions wrap on spaces and keep tokens such as `$12.50` intact. Plates use React text nodes. The safe area is the 64-pixel margin of a 1080×1920 frame. There is no `innerHTML`, remote font, or CDN request.

## Board

```text
GET /api/languages
GET /api/sources/<source_id>/alignments
GET /api/sources/<source_id>/narration
GET /api/campaign-productions/<run_id>/language
```

Responses use ids, hashes, and relative paths. They do not include credentials or absolute paths.

## Limits

This round does not crawl Whop, publish to a platform, translate a transcript, attribute a speaker, or recognize a face. Arabic alignment is not claimed. Japanese, French, Spanish, and German alignment models are named and licensed in the catalog, and they stay `model_missing` until a live smoke. A fake provider cannot be `verified_live`.
