# ADR 0055: Commercial narration engine selection

- Status: Accepted
- Date: 2026-10-05

## Context

VoiceStudio's default weight, `k2-fsa/OmniVoice`, is not commercially permitted for this project. The speech route also names the engine in the `model` field. A hard-coded engine id sends the wrong engine or a non-commercial weight.

## Decision

A live narration plan records the engine, model, revision, voice, sample rate, channel count, license evidence, and consent that the operator selected. Clipforge does not substitute `omnivoice` or placeholder ids. Commercial output requires `model_license=allowed`, `commercial_use=allowed`, and a model id that does not start with `k2-fsa/`. Those checks run before any HTTP call, so a prohibited model is not loaded.

The request body follows the advertised `POST /v1/audio/speech` schema: `model` is the engine id, `voice` is the selected voice, `response_format` is `wav`. The returned audio must match the plan's sample rate and channel count. Cache identity includes the engine, model, revision, voice, license, commercial-use state, and conversion recipe.

The English smoke engine is KittenTTS. The catalogue reports 24000 Hz mono and no cloning. The model card for `KittenML/kitten-tts-mini-0.8` is Apache-2.0. Arabic and Japanese alignment stay unclaimed. Narration does not approve a Hero or publish externally.

## Alternatives considered

- Keep using OmniVoice for internal smoke and label it commercial. Rejected. The model rights are not commercially permitted.
- Install PocketTTS without a recorded license acceptance. Rejected. Availability is not permission.

## Consequences

Fake plans still use the existing placeholders. A VoiceStudio plan that omits the discovered identity fails before the network. A voiceover may be shorter than the Hero. It may not run past the edit.
