# ADR 0089: Tarteel foreground composition and editorial window policy

## Status

Accepted for new Tarteel drafts. Existing rendered artifacts keep their
recorded recipes and are not reinterpreted.

## Context

The campaign output was using a portrait canvas as the coordinate system for
the CTA and watermark. With a landscape source this put brand layers on the
blurred background or over a child. Candidate mining also used the generic
duration profile, so a source moment could be rendered as a short isolated
window without enough context for a reviewed hook, body, and punch.

## Decision

Tarteel production uses one explicit composition: a blurred full-canvas copy,
the original source picture contained in a mildly enlarged foreground
rectangle, and captions in the portrait caption lane. The CTA and optional
watermark are children of the foreground rectangle. Their permille geometry is
relative to that rectangle and the renderer rejects canvas-coordinate campaign
overlays. The CTA remains a real muted alpha video. A reviewed source-native
logo annotation can set `source_visible_v1`, in which case the optional
watermark is omitted; otherwise the cleared watermark asset is used.

The Tarteel candidate profile prefers 40–45 second windows, permits 25–55
seconds, and uses a shorter 120 ms boundary pad. Production directions must
carry a source-grounded hook/body/punch arc before a multi-moment recut is
rendered. Forced-word boundaries remain authoritative and a changed arc or
profile changes the cache fingerprint.

CTA timing is selected from deterministic candidate beats and minimizes overlap
with caption intervals. It is still a declarative plan fact and remains subject
to human frame review and the existing QA and approval gates.

## Consequences

- Review and delivery no longer disagree about the location of the source
  picture or campaign layers.
- A crop or zoom change invalidates the render input and dependent evidence.
- A source logo decision must be recorded in the direction evidence; the
  renderer cannot infer brand visibility from a missing annotation.
- The generic candidate miner remains unchanged for other campaigns.
