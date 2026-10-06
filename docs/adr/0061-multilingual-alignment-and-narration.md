# ADR 0061: Multilingual alignment and narration capability

- Status: Accepted
- Date: 2026-10-06

## Context

English WhisperX alignment and en-US KittenTTS narration are the only live claims. Arabic and Japanese captions already keep their characters, and their alignment is still `alignment_not_claimed`. A later round must not treat a test double as a live provider. Live Whop crawling needs an authenticated account and stays out of this round.

## Decision

The capability registry remains the only place that may say a language is `verified_live`. Full-source alignment is a separate optional artifact, `MultilingualAlignmentDocument`, stored under `languages/alignments/<id>/`. Its cache identity is the source hash, transcript hash, language, provider, model, revision, checkpoint, and runtime. A fake aligner may produce `available_not_smoked` timings for tests. It cannot set `verified_live`. WhisperX full-source execution stays behind `CLIPFORGE_ALIGNMENT_LIVE_SMOKE=1` and fails closed, before a job, when the runtime is absent. Normal runs set the offline hub variables only when that smoke is actually attempted.

Hero planning may bind an alignment only when its status is `verified_live`, its provider is WhisperX, and its checkpoint is the English checkpoint this install has already run. Anything else stays provisional. Selected-clip Hero alignment is unchanged.

Narration stays optional. `narration_not_requested` does not block a campaign. A requested language that is not `verified_live` fails before a render job. KittenTTS remains the English-only live narrator. A `k2-fsa/` model is not commercially permitted. Narration cache identity includes the script hash and the provider, engine, model, revision, and voice.

Caption layout keeps Unicode text as React text. Arabic is RTL. Japanese wraps by character and keeps closing punctuation with the previous glyph. No remote fonts, HTML, or CDN.

Campaign selections record an optional alignment requirement, a narration request, and the capability fingerprint. External publishing and live Whop stay `deferred` and `not_configured`.

## Alternatives considered

- Mark Arabic and Japanese verified because a fake aligner returned times. Rejected. That would report a test as a live provider.
- Translate source text by default. Rejected. The transcript stays unchanged unless a profile explicitly requests a separate translation.
- Crawl Whop while adding languages. Rejected. That work needs account credentials and is a different round.

## Consequences

Operators can see which languages are live, unsmoked, or unsupported. English campaigns keep their current claims. A missing aligner or an unsupported narration request stops before a job. Publishing and live Whop are still not implemented.
