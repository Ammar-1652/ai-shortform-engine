# ADR 0088: Tarteel animated CTA alpha video and safe rail

## Status

Accepted for the Tarteel campaign overlay contract.

## Context

The first Tarteel integration extracted one chroma-keyed PNG and held it for
the CTA interval. That discarded the campaign-provided animation and allowed
the placement to be treated as an arbitrary lower-third layer. It also made
it difficult to prove that the CTA was a video overlay with no audio of its
own or that it stayed out of the caption lane.

## Decision

The overlay staging step converts the official green-screen CTA into an
audio-free VP9/WebM video with an alpha channel. The exact source hash and the
staged video hash are included in the render dependency digest. Remotion uses
its in-browser `Video` layer with `muted`, so every CTA frame is animated and
the CTA audio stream cannot compete with campaign speech.

Tarteel uses the explicit `top_left_brand_rail_v1` safe region. Its normalized
left, top, and width values are part of `CampaignOverlaySpec`; the renderer
does not choose a different location. The CTA width is capped at 600 permille
and the contract declares `faces_and_captions_clear_v1`. The rail is above the
caption lane and is separated from the watermark. A plan that omits the rail,
clearance declaration, or uses a static sequence is rejected by the campaign
policy and renderer input validation. Face/caption clearance is a hard
delivery gate, not a visual suggestion.

The PNG sequence mode remains readable only for old review fixtures. It is not
eligible for Tarteel compliance or delivery. The CTA remains a campaign asset
with a rights record, and the existing human review, QA, provenance, and stale
artifact gates are unchanged.

## Consequences

- The shipped renderer must be able to decode VP9 alpha WebM frames.
- A changed CTA video, chroma-key recipe, or safe-rail geometry changes the
  render input and invalidates dependent QA and approval artifacts.
- A safe rail is a deterministic collision contract, not evidence that a face
  detector has identified a speaker. Campaign-specific visual review remains
  required before delivery.
- The campaign continues to forbid added music, SFX, and narration.
