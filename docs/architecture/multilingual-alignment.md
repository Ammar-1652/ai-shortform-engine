# Multilingual alignment and narration

English WhisperX and en-US KittenTTS remain the live claims. Other languages stay explicit about what has not been run. See [ADR 0061](../adr/0061-multilingual-alignment-and-narration.md).

SQLite schema version stays 6. Contract `schema_version` stays `1.0.0`. The new records are sidecars.

## Capability matrix

| Language | Alignment | Narration |
| --- | --- | --- |
| en-US | `whisperx`, evidence `verified_live` | KittenTTS `verified_live` |
| en-GB | same English checkpoint | `locale_not_smoked` |
| fr-FR, es-ES, de-DE | `alignment_not_claimed` | `unsupported_language` |
| ar | `alignment_not_claimed`, RTL captions | `unsupported_language` |
| ja | `alignment_not_claimed`, character wrap | `unsupported_language` |
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

`align` fails before inserting a job when the language is unsupported, the provider does not claim that language, or WhisperX is not being smoked. `CLIPFORGE_ALIGNMENT_LIVE_SMOKE=1` is required before a full-source WhisperX attempt, and that attempt sets `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, and `HF_DATASETS_OFFLINE`. A missing install is `not_configured`.

The cache identity is the source SHA-256, transcript SHA-256, language, provider, model, revision, checkpoint SHA-256, runtime version, and device. A hit returns the same alignment id only when the artifact hash still matches and the producer job succeeded. Changed source or transcript bytes are a new id. `verify` and `show` do not write.

Each word stores Unicode text, positive source and output durations, half-open frames, and the source and transcript ids. Words are monotonic. The service does not invent times when alignment is refused.

Hero binding accepts only `verified_live` WhisperX output whose revision and checkpoint match the English runtime already smoked. A fake or `available_not_smoked` document is not substituted. Selected-clip alignment remains the existing Hero path.

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

Narration cache identity is the script SHA-256 plus provider, engine, model, revision, and voice. A changed script is a new id. Narration does not approve a candidate or a Hero.

## Captions

Arabic layout is `rtl` and does not reverse characters. Japanese layout wraps by Unicode character, does not insert spaces, and does not leave `。` or similar closing marks at the start of a line. Plates use React text nodes. The safe area is the 64-pixel margin of a 1080×1920 frame. There is no `innerHTML`, remote font, or CDN request.

## Board

```text
GET /api/languages
GET /api/sources/<source_id>/alignments
GET /api/sources/<source_id>/narration
GET /api/campaign-productions/<run_id>/language
```

Responses use ids, hashes, and relative paths. They do not include credentials or absolute paths.

## Limits

This round does not crawl Whop, publish to a platform, or translate a transcript by default. A full-source Arabic or Japanese aligner is not installed. Those languages stay `alignment_not_claimed` until a real provider runs.
