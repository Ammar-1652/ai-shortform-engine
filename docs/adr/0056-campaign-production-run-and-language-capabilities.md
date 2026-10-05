# ADR 0056: Campaign production run and language capabilities

- Status: Accepted
- Date: 2026-10-05

## Context

Round 19 proved one authorized source path at a time: ingest, alignment, Hero, QA, optional KittenTTS narration, and a local delivery. The next step is to repeat that path as one campaign over both selected sources without claiming a language, aligner, TTS engine, or stock license that this install has not verified.

ADR 0055 already records commercial narration engine selection. This decision does not replace it. The campaign layer needed its own number.

SQLite is at schema 6. The campaign record can point at existing job and artifact rows. A new table would not make the hash bindings stronger.

## Decision

A campaign run is a versioned JSON sidecar, schema version `1.0.0`, plus one `campaign_production` job and one `campaign_production_run_json` artifact. There is no migration. Unknown JSON keys are rejected. The document refuses absolute paths, `file:` URIs, and secret-like tokens.

The language capability registry is the only place that may say a language is verified live, tested only with a fake provider, or unavailable. English WhisperX and `en-US` KittenTTS are the verified live claims. Arabic and Japanese alignment stay `alignment_not_claimed`. `zh-CN` is unsupported. `FakeForcedAlignment` remains a unit-test double and is not a production backend.

An allowed `CampaignSource` proceeds without another confirmation. Prohibited, unknown, missing, symlinked, remote, and hash-mismatched sources fail closed. Cache identity includes source and artifact hashes. A cache hit does not insert another stage job, does not copy the delivery, and does not call the narration provider. `--force` creates a new run and keeps the old one. Resume retries incomplete or invalidated sources only.

Envato stays discovery-only. A blocked or unlicensed hit cannot become render media. External publishing stays deferred and is not a gate for this round.

## Alternatives considered

- Add a `campaign_runs` table. Rejected. The sidecar and the existing artifact row already bind the hashes, and a migration is not required for that.
- Mark Arabic and Japanese alignment passed because captions can be drawn. Rejected. Drawing text is not forced alignment.
- Reuse the newest narration artifact. Rejected. Later cache-miss rows use a different script, voice, or revision. The run must select the verified identity.
- Treat a VoiceStudio timeout as a permanent provider failure. Rejected. A cold start is retryable and must not be stored as audio.

## Consequences

`clipforge campaign plan`, `run`, `show`, `verify`, and `resume` sit beside the existing catalogue commands. `show` and `verify` keep the catalogue id `antoine-sallis` on the old path and treat any other id as a run id. Operators can see, per source, which stages were reused and which capability was actually claimed. A campaign can succeed locally while Arabic alignment, Japanese alignment, and external publishing remain honestly unavailable.
