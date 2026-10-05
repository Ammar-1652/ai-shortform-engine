# ADR 0050: Multilingual transcripts and captions

- Status: Accepted
- Date: 2026-10-05

## Context

Campaigns need captions in more than one language. A translation must not overwrite the canonical source words, and WhisperX must not be described as supporting every language.

## Decision

`LanguageProfile` records the BCP-47 tag, ISO code, script, direction, caption locale, and the campaign-policy status. The tested set is `en-US`, `en-GB`, `fr-FR`, `es-ES`, `de-DE`, `ar`, and `ja`. Arabic is RTL. A translation is a separate `TranslatedTranscript`. Alignment capability for WhisperX is `optional` for English and `not_claimed` otherwise. An unknown tag fails before a render job is inserted.

For Antoine Sallis, English is allowed. Any other tested language is `needs_operator_confirmation` until the policy is extended.

## Consequences

- Unicode, names, punctuation, and currency stay in the source field.
- Caption profiles still require human review.

## Non-goals

No automatic translation service and no claim that every language has a local aligner.
