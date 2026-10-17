# Multilingual alignment and narration

en-US, fr-FR, and ja alignment are `verified_live` only when an external speech file discovered from the explicit `CLIPFORGE_SPEECH_EVIDENCE_ROOT` or the installed `~/.local/clipforge-speech-evidence` directory matches the packaged record and the measured model. Clipforge checks the artifact SHA-256 and the WAV facts. Model identity and speech identity are both required. A missing file, a tone, a sine wave, a catalog constant, or a metadata-only row stays non-live. en-GB is not verified unless it has its own speech record. en-US KittenTTS remains the only verified narration. See [ADR 0061](../adr/0061-multilingual-alignment-and-narration.md), [ADR 0066](../adr/0066-multilingual-alignment-production.md), and [ADR 0074](../adr/0074-shared-speech-evidence-discovery.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`. The new records are sidecars.

## Capability matrix

| Language | Alignment | Narration |
| --- | --- | --- |
| en-US | `whisperx`, `verified_live` only with its own external speech file and the measured English model | KittenTTS `verified_live` |
| en-GB | same English checkpoint, `available_not_smoked` until it has its own speech record | `locale_not_smoked` |
| fr-FR | `verified_live` only with its own external speech file and the measured French model | `unsupported_language` |
| es-ES, de-DE | Apache-2.0 wav2vec2 catalog, evidence `model_missing` | `unsupported_language` |
| ar | `alignment_not_claimed`, RTL captions | `unsupported_language` |
| ja | `verified_live` only with its own external speech file and the measured Japanese model, character wrap | `unsupported_language` |
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

Locale spellings normalize for lookup only: `en-US` and `en-GB` to `en`, `fr-FR` to `fr`, `es-ES` to `es`, `de-DE` to `de`, `ja` and `ja-JP` to `ja`, `ar` to `ar`, `zh-CN` to `zh`. The stored document keeps the original locale. A non-English request does not load `WAV2VEC2_ASR_BASE_960H`. WhisperX's default French, Spanish, and German torchaudio bundles are `VOXPOPULI_ASR_BASE_10K_*` and are refused. The catalog names the Apache-2.0 Hugging Face wav2vec2 models as expected identity. A matching local snapshot stays `available_not_smoked` until the external speech file for that locale matches the packaged record and the measured model. `speech_evidence.json` is the index. It is not evidence by itself. The audio bytes stay outside the repository, under `CLIPFORGE_SPEECH_EVIDENCE_ROOT`, and the filename is one relative path segment. Spanish and German stay `model_missing` when their snapshots are absent. Full-source alignment does not run WhisperX and does not emit even spans. Selected-clip `hero align` remains the production path.

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

Arabic layout is `rtl` and does not reverse characters, transliterate, or rewrite Arabic-Indic digits. Japanese layout wraps by Unicode character, does not insert spaces, and does not leave `。` or similar closing marks at the start of a line. Latin captions wrap on spaces and keep tokens such as `$12.50` intact. Plates use React text nodes. Advanced styles provide explicit safe margins (the clean defaults are 64px left/right, 120px top, and 300px bottom) and the renderer consumes those values. The clean recipe stages hashed local DejaVu, Noto CJK, and Noto Arabic fonts; their license evidence is [caption-fonts.md](caption-fonts.md). There is no `innerHTML`, remote font, or CDN request.

Forced caption words may carry an explicit review status: `unverified`,
`correct`, or `incorrect`. An active reviewed-correct word is green and returns
to white after its interval; a reviewed-incorrect word stays red. Unverified
words receive only the style accent while active and never claim correctness.
Arabic words are split only at word boundaries when this status data is
present; characters are never manually reversed or split into independent
glyphs. Rough Preview remains phrase-only because its ASR timing is
provisional; word-by-word motion is only emitted from the forced selected-clip
alignment used by Hero and Advanced Hero.

## Board

```text
GET /api/languages
GET /api/sources/<source_id>/alignments
GET /api/sources/<source_id>/narration
GET /api/campaign-productions/<run_id>/language
```

Responses use ids, hashes, and relative paths. They do not include credentials or absolute paths.

## Limits

This round does not crawl Whop, publish to a platform, translate a transcript, attribute a speaker, or recognize a face. Arabic alignment is not claimed. Spanish and German stay `model_missing`. Japanese and French are `verified_live` only when their external speech files and measured models match. en-GB is not verified from the English file. A fake provider cannot be `verified_live`. Full-source alignment stays `not_configured`.
