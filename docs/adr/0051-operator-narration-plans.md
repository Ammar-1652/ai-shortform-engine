# ADR 0051: Operator narration plans

- Status: Accepted
- Date: 2026-10-05

## Context

VoiceStudio can clarify a short. It can also replace the speaker, use a non-commercial model, or run when the operator did not ask for it. ADR 0046 already keeps the sidecar optional.

## Decision

`clipforge voice plan` records whether narration is enabled, the operator reason, the campaign decision, the language, the voice, the model license, and the script hash. `voice render` generates audio only when that plan is enabled and the policy decision is `allowed`. A disabled plan verifies as `PASS narration disabled` and does not call the provider. The no-narration Advanced Hero path stays the default.

The live sidecar still requires `CLIPFORGE_VOICESTUDIO_URL` and `CLIPFORGE_VOICESTUDIO_LIVE_SMOKE=1`. Models are not downloaded. Unknown, prohibited, and CC-BY-NC rights fail closed.

## Consequences

- Cache identity stays on the existing narration artifact: script, provider, model, voice, and audio hash.
- A changed script is rejected instead of being mixed into an old take.

## Non-goals

VoiceStudio is not vendored. Narration does not approve a Hero and does not claim speaker identity.
