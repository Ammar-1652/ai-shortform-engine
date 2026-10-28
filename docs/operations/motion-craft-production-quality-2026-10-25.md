# Motion-craft production quality checkpoint

This checkpoint records the source-grounded motion pass for the Tarteel Advanced Hero draft. It is an operator record, not a publication approval.

## Decision

The source arc begins at the reviewed phrase `احنا اليوم بإذن الله`. The earlier flash-forward segment (`وشوف يكملون ولا لا`) is retained in the campaign work root as history and is omitted from this production arc. The current arc is append-only and is bound by `editorial-arc-opening-v1.json`, its Codex operator review, and the Advanced Hero plan hash.

The Quran challenge illustration is a short communication beat, not a permanent card. The Remotion component now renders a deterministic sequence:

1. spring entrance;
2. page opening;
3. progressive line reveal;
4. completion check and pulse;
5. fade to zero opacity after the bounded 72-frame visual budget.

The event remains source-bound to the reviewed punch interval, while the visual budget prevents it from covering the rest of the closing recitation. The current direction places the 300x180 illustration at `(690, 500)` in the upper safe lane, above the foreground picture and outside the CTA rectangle. The graphic contains no copied Quran text; the spoken Quran caption remains the canonical source-bound caption layer.

The renderer uses Remotion `useCurrentFrame`, `spring`, and integer frame boundaries. It does not use timers, random values, network assets, or operator-supplied JSX. The native motion reference hash is recorded in `configs/editorial/motion-recipes.json`; a changed component invalidates the motion catalog fingerprint and downstream plans.

## Evidence and output

The latest real production draft was rendered through Remotion with the Tarteel CTA and watermark, the corrected opening arc, current direction plan, and a fresh overlay-exclusion proof generated from the current TimeMap. The draft is under the ignored work root:

`var/work/projects/3865ea49-98ce-446e-ae4a-c4f384b0c9fe/sources/bdafcfaf-73c4-4584-8503-ba6ffb869711/advanced-hero/review-drafts/runs/5c91045f-bb39-4a78-aa65-7e88a0f552d0/candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/advanced.mp4`

Its companion decoded contact sheet is:

`var/work/projects/3865ea49-98ce-446e-ae4a-c4f384b0c9fe/sources/bdafcfaf-73c4-4584-8503-ba6ffb869711/advanced-hero/review-drafts/runs/5c91045f-bb39-4a78-aa65-7e88a0f552d0/candidates/89a5a2fa-ce33-5527-b78d-46a685696c9b/inspect/contact-sheet.png`

The current output probes at 1080x1920, 30 fps, 41.666667 seconds, with H.264 video and 48 kHz stereo AAC. The first frame contains the source's own warm light effect; the decoded caption is `احنا اليوم بإذن الله`, confirming that the warm flash is source-native rather than an unwanted pre-arc shot. The motion graphic is visible during its reviewed beat and absent in the later decoded frame.

## Upstream adaptation

The motion vocabulary was reviewed against the pinned local provenance and the inspected Remotion/iart/Shotcraft references. The implementation adopts the useful principles only: one focal point, a small number of motion layers, frame-driven animation, purpose-bound choreography, safe-area placement, and a verify-after-render loop. It does not download upstream instructions at render time or execute unreviewed code.

The source study material is retained under the ignored resource library. The project motion catalog remains the only production authority.

## Validation

The renderer suite passes 64 tests. The targeted Python arc, overlay, and Advanced Hero tests pass. `clipforge editorial motion verify` passes 21 recipes. Full repository validation and CI still need to be run after this checkpoint's final commit; human audio/muted playback remains the final review gate.
