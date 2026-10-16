# Tarteel campaign short-form style library

This is an editorial routing reference for source-grounded Tarteel clips. It
was derived from the 22 operator-supplied reference MP4s in
`../campaigns/Tarteel` and official platform guidance. The references did not
include verified view, retention, or posting data, so these are observed craft
patterns, not causal performance claims.

## Selection order

Campaign policy and rights come first. Then select a style by the source
evidence that actually exists:

1. Find the strongest complete spoken moment or reaction.
2. Check whether the preceding source material supplies setup and the later
   material supplies a resolution or proof.
3. Check for a visible Tarteel/app screen, child reaction, interviewer volley,
   correction, or challenge result.
4. Choose one primary style. Add a secondary treatment only when it clarifies
   the same story; do not stack unrelated templates.
5. If no style has a defensible hook and payoff, return `needs_review` instead
   of inventing a headline or claim.

Rank evidence in this order: semantic hook clarity, emotional or curiosity
strength, complete-arc availability, visual proof, captionability, portrait
framing quality, and source/rights confidence. This score chooses among valid
options; it is not a virality prediction.

## Proven styles for the supplied material

### 1. Flash-forward payoff hook

Use a strong line, answer, mistake, or reaction from the middle as the opening,
then return to the setup and let the full moment play. This is the campaign
style requested by the operator.

- Shape: `hook_flashforward → setup → escalation → payoff`.
- Hook: usually 0.6–2.5 seconds; preserve a complete phrase or reaction.
- Repeat policy: the hook range may recur once when the full story reaches it;
  the repeat must be explicit in the editorial arc and must not become an
  accidental loop.
- Captions: each output occurrence gets a unique cue id while retaining the
  same source word ids and evidence.
- Reject when the hook needs missing context, changes the speaker's meaning,
  or leaves the body with no setup before the repeated moment.

The current QA contract treats arbitrary repeated source ranges as a failure.
This style therefore requires a distinct `flashforward_hook` occurrence type,
not a duplicated segment hidden in a generic list.

### 2. Challenge/question reveal

Open with a question or visible challenge, then show the participant trying to
answer and finish on the result or reaction.

- Good evidence: a question from the interviewer, a visible prompt on the
  Tarteel screen, a child beginning a recitation, and a clear result.
- Remotion: a restrained question card or progress marker can appear only when
  its wording is copied from source evidence.
- Do not promise a result the source does not show.

### 3. Mistake → correction → confidence

Use a detected mistake or uncertainty as the hook, then show the correction and
the participant's successful recovery.

- Keep the original error understandable; do not manufacture a wrong answer.
- Use a single visual state change (`wrong → corrected`) only when the source
  or app screen proves both states.
- The correction is the payoff; avoid a generic celebratory graphic if no
  source reaction exists.

### 4. Reaction-first emotional ladder

Start on the strongest facial or group reaction, then reveal what caused it and
end on the emotional resolution.

- Use face-follow only as framing evidence; never infer speaker identity from a
  detected face.
- Keep the reaction's original audio aligned. Do not cover an important face
  with a title or caption plate.
- A short pause can remain when it carries anticipation; remove only empty
  silence that does not change meaning.

### 5. App-proof / screen-inset explainer

Use the Tarteel interface or recitation display as visual proof of what is being
said, alternating it with the participant and interviewer.

- Crop the screen to the meaningful region and preserve legibility.
- Use a typed inset, highlight, or pointer only for text/controls visible in the
  source; no invented scores, counters, or performance claims.
- Keep the main face and app proof from competing for the same safe-area lane.

### 6. Interview volley / answer reveal

Cut between interviewer question, participant answer, and the reaction or
follow-up. This works when the source contains a real conversational exchange.

- Preserve question-before-answer order unless a flash-forward hook is chosen.
- Each cut must start and end on complete spoken words; use the canonical
  TimeMap rather than re-timing audio by eye.
- Avoid turning a calm exchange into arbitrary jump cuts. One purposeful
  punch-in or angle change is enough when the source has no natural coverage.

### 7. Participant montage / quiz ladder

Use several distinct participants or attempts to build a single challenge arc,
then resolve with a final result or reaction.

- Every insert needs a source interval, a reason for inclusion, and a clear
  relation to the same challenge.
- Vary faces, screen proof, and reaction shots; do not repeat one 20-second
  clip to fill a minute.
- Use a counter only when the source gives an actual count. Otherwise use
  neutral progress language or omit the counter.

### 8. Quote-card / context-first documentary

Use a short source-grounded headline to orient the viewer, then let a clean
conversation or recitation carry the body.

- The headline must be copied from a transcript span, source-native text, or a
  reviewed campaign fact.
- Keep the card short, high-contrast, and outside the caption lane; it should
  disappear once the story is understood.
- This is preferable to a flashy graphic when the source is already visually
  compelling.

## Optional styles only when the source supports them

These patterns are valid general short-form structures, but they are not
automatically appropriate for Tarteel:

- `how_it_works`: a real step sequence with a visible beginning, middle, and
  result;
- `before_after`: two truthful states with a meaningful change, not a fabricated
  transformation;
- `participant_journey`: arrival, attempt, and outcome when the source contains
  all three;
- `behind_the_scene`: genuine preparation or candid context that adds meaning;
- `single_quote_with_reaction`: one complete sentence followed by a real
  response.

Do not use trend-audio choreography, generic listicles, fake reaction inserts,
arbitrary memes, music beds, or unrelated Envato B-roll for this campaign unless
the campaign policy explicitly allows and the source-grounded direction proves
their editorial purpose. External content cannot replace a weak source moment.

## Shared visual and audio rules

- Fill the portrait canvas with a reviewed crop, face-follow trajectory, or a
  deliberate blurred/background treatment. Accidental black bars are a defect.
- Use Arabic-aware, RTL-safe phrase captions. Keep a top hook/card lane and a
  lower caption lane; never duplicate source-native text as a new title.
- Use Remotion graphics to clarify a source fact: question, result, app state,
  or reviewed campaign identity. Omission is better than decoration.
- SFX are optional accents, not a continuous soundtrack. Use the existing
  bounded gain/envelope policy and keep speech intelligibility dominant.
- Preserve source order and word alignment unless the selected style explicitly
  declares a flash-forward arc. Every output segment keeps integer-microsecond
  source evidence and its own caption/audio occurrence.
- Validate the encoded MP4, not just the plan: hook visibility, full caption
  coverage, no unintended bars, no debug graphics, sync at every cut, safe-area
  bounds, and audio loudness/true peak.

## Evidence and platform references

Use these as high-level guidance, not as campaign policy or performance
guarantees:

- TikTok's official creative guide recommends a fast hook, a coherent
  problem/solution story, captions, vertical/mobile-first composition, and
  testing multiple creative versions:
  https://ads.tiktok.com/business/en/guides/what-is-ad-creative-guide
- TikTok's Creative Accelerator describes hook → key message → CTA as one
  practical structure and emphasizes that sound should be planned rather than
  ignored:
  https://ads.tiktok.com/business/creativecenter/quicktok/online/tiktok_creative_accelerator/pc/en
- YouTube says text can guide viewers through fast edits and help them follow a
  spoken story, and its timeline controls should be checked for exact text
  timing:
  https://support.google.com/youtube/answer/13380879
- YouTube explicitly says Shorts are not ranked by one preferred format; viewer
  choice, average view duration, percentage viewed, and satisfaction signals
  matter. Do not convert these style suggestions into guaranteed virality:
  https://support.google.com/youtube/answer/11914225
- Meta describes Reels retention charts, replay measurement, text styles, and
  timing tools as ways to test and inspect what resonates:
  https://about.fb.com/news/2023/11/new-ways-to-create-content-on-instagram/
  https://about.fb.com/news/2024/10/best-practices-education-hub-creators-instagram/

## Required direction output

The selected style must be named in the direction brief and explain why it fits
the evidence. The brief must include:

- style id and fallback style;
- hook, body, and punch beats;
- source ranges and forced-word evidence for every beat;
- whether a flash-forward occurrence is used;
- caption lane and collision notes;
- any Remotion graphic and its source fact;
- any local asset placement and relevance note;
- validation expectations and a reason for omitting optional treatments.

If the rules document is unavailable, mark the direction `needs_review` and do
not claim campaign compliance.
