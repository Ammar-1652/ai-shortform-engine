# ADR 0053: Real-source validation and optional VoiceStudio narration

- Status: Accepted
- Date: 2026-10-05

## Context

A synthetic benchmark can exercise the local chain and still say nothing about the authorized campaign files. Narration is optional, and the VoiceStudio process is a separate local service whose speech contract is documented by that project.

## Decision

`clipforge benchmark run --fixture real_source` records the operator's fixture label. Readiness does not treat that label as verification. `real_source_verified` stays `unavailable` until a local delivery stage was executed and verified for a real-source fixture. `evidence_class` is `synthetic_only` for the deterministic fixture and `real_source` only when the fixture label is `real_source`. Synthetic warnings stay on the synthetic fixture. `technical_result` and `local_delivery_result` use the names `technical_pass` and `local_delivery_pass` when those rollups pass. External publishing stays `external_publishing_deferred`.

VoiceStudio stays disabled unless `CLIPFORGE_VOICESTUDIO_ENABLED=1`. A disabled doctor does not open a socket and reports health and capabilities as `not_called`. An enabled doctor calls `GET /health` and `GET /.well-known/voicestudio-speech`, and it accepts only protocol `voicestudio.speech.v1` with a public service version and an endpoint map. Synthesis remains `POST /v1/audio/speech` with the engine id, voice id, explicit script, ISO 639-1 language, and `response_format=wav`. That speech route is VoiceStudio's OpenAI-compatible TTS endpoint. The discovery document advertises transcription and MCP transports; Clipforge does not treat those as a substitute for the speech route, and it does not invent a second synthesis API.

The narration artifact records language and provider version from the explicit request. Cache identity already includes the script hash, language, voice, model, provider version, and the project and source. A changed script or provider version is a miss. Unknown, prohibited, and non-commercial model rights still fail closed.

Caption proofs for Arabic and Japanese keep the source characters, use provisional timing, and set `alignment_status` to `alignment_not_claimed`. English WhisperX alignment is claimed only when the installed aligner actually runs. Provisional word times are not labeled as WhisperX.

## Consequences

- A green synthetic test cannot satisfy real-source readiness.
- Operators select the local VoiceStudio URL with `CLIPFORGE_VOICESTUDIO_URL`. The default remains off.
- Campaign renders do not gain outside stock while campaign policy blocks it.

## Non-goals

No external platform upload, no automatic review approval, and no silent model download.
