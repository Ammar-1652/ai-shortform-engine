# Voice provider integration

Narration is optional. Clipforge works when VoiceStudio is not installed.

## Architecture

`VoiceProvider` exposes `doctor`, `capabilities`, `generate`, and `verify_audio`. `FakeVoiceProvider` writes deterministic PCM silence and is what tests use. `VoiceStudioProvider` talks to a separate local process over HTTP. Clipforge does not copy VoiceStudio source, vendor it, or depend on its Python package.

Discovery is `GET /.well-known/voicestudio-speech`. The accepted protocol id is `voicestudio.speech.v1`. An enabled `clipforge voice doctor` also calls `GET /health` and reports the discovery endpoint names and service version. A disabled doctor reports `health: not_called` and `capabilities: not_called` and does not open a socket. Synthesis is `POST /v1/audio/speech` with the engine id, voice profile id, explicit script, the ISO 639-1 language, and `response_format=wav`. That route is VoiceStudio's documented OpenAI-compatible speech endpoint. The discovery document itself advertises transcription and MCP transports. Clipforge does not call a model download route.

## Configuration

```text
CLIPFORGE_VOICESTUDIO_URL=http://127.0.0.1:3900
CLIPFORGE_VOICESTUDIO_ENABLED=0
CLIPFORGE_VOICESTUDIO_TIMEOUT_S=300
CLIPFORGE_VOICESTUDIO_ALLOW_REMOTE=0
CLIPFORGE_VOICESTUDIO_LIVE_SMOKE=1
```

The provider is disabled by default. A disabled doctor returns pass and makes no request, because the core product does not require narration. An enabled provider that does not answer fails. Only `http://127.0.0.1` is accepted by default. Another host must be HTTPS and `CLIPFORGE_VOICESTUDIO_ALLOW_REMOTE=1`. URLs with user info, queries, or embedded secrets are refused. The live smoke is skipped unless `CLIPFORGE_VOICESTUDIO_LIVE_SMOKE=1`, and a skip is unavailable, not a pass.

## Rights

A narration request carries a voice profile: provider, engine, model id and revision, voice type, consent record, commercial-use state, model-license state, and clone permission. Unknown or prohibited rights fail closed. A cloned voice requires `clone_permission`. Commercial output requires both commercial use and model license to be `allowed`. `cc_by_nc` is rejected for commercial output. A model id that starts with `k2-fsa/` is the default VoiceStudio weight family and is not treated as commercially permitted. Application license and model license stay separate. Reference audio and voice embeddings are not stored.

The script is explicit text with a SHA-256. A raw transcript is not converted into narration. Markup, URLs, filesystem paths, and secret-like tokens are rejected.

## Timing and cache

Canonical duration stays integer microseconds. Policies are `preserve_duration`, `bounded_time_stretch`, and `reject_if_out_of_range`. Audio outside the policy is rejected. Clipforge does not silently change the source duration and does not apply an unbounded stretch. ffprobe checks codec, sample rate, channels, and duration when it is installed. The WAV header is the fallback.

Cache identity includes project, source, candidate or Hero id, provider version, engine, model id and revision, voice profile, script hash, language, sample rate, channels, timing policy, target duration, output format, consent id, and license evidence id. A hit rechecks the audio hash, size, succeeded job, and lineage, and does not call the provider. A missing, changed, or symlinked file is a miss.

## Advanced Hero

`render` accepts `--narration` only through `narration_artifact_id` on the service. The asset is verified before the advanced job is inserted. The staged name is `narration.wav`. The job payload stores the audio hash. The render input has no absolute path. When narration is omitted, the render input does not mention narration and the previous cache behavior stays in place. SFX rules and the music prohibition are unchanged. Narration does not replace the source audio track by itself and does not approve the Hero.

## Commands

```text
clipforge voice doctor --provider voicestudio
clipforge voice capabilities --provider fake
clipforge voice generate --request REQUEST.json --provider fake
clipforge voice verify ARTIFACT_ID
clipforge voice list PROJECT_ID
```

`verify` and `list` do not generate audio.
