# Tarteel campaign hard rules

These rules are delivery gates, not creative preferences.

- Use only official Tarteel playlist footage and cleared campaign CTA and
  watermark assets.
- Add exactly one official animated CTA video. Remove its green background;
  never replace it with a still image. The CTA is muted and may not add music,
  SFX, or narration.
- Render the original source picture in a rounded, aspect-correct foreground
  card with a restrained zoom. New Tarteel plans use
  `auto-source-palette-v1`: the deterministic analyzer samples the authorized
  proxy, records its dominant colour, and selects the reviewed olive, sage, or
  charcoal frame family. The selected palette is source-hash bound and changes
  the render/cache identity. Both the CTA and the optional watermark belong to
  that original foreground picture. Keep the CTA small (`cta_width_permille <= 600`) in the
  `foreground_attention_v1` region. It must declare
  `faces_and_captions_clear_v1` and must not intersect a face region, captions,
  or source branding. A missing clearance proof fails delivery.
- The framed Tarteel card uses `platform-bleed-v1`: for a 1280x720 source it
  occupies the full 1080px output width and a proportional 608px height,
  centered vertically. Do not restore the 90% horizontal scale for this
  treatment. Validate the complete frame at 1080x1920 and in the reviewed
  platform crop masks before delivery.
- When a reviewed shot needs a larger visual presence, expand the frame body
  vertically into the surrounding background while keeping its horizontal
  bounds exactly `x=0..1080`. Never let a scaled frame extend past the left or
  right canvas edge. Preserve the source 16:9 ratio inside the frame; added
  frame body is padding/background, not a stretched video and not a crop of
  the source. A scale that would remove a child, the Sheikh, the tablet,
  source-native text, or the logo is rejected even if the frame looks larger.
- Zoom is shot-specific, not a campaign-wide percentage. The current reviewed
  shot uses 115% frame-body expansion while preserving the complete source;
  150–175% is not a valid default and must fail visual review when it removes
  important content. The frame geometry is recalculated after the chosen zoom,
  before CTA, watermark, caption, and safe-area placement.
- If the reviewed backdrop variant is source blur, apply the fixed darkening
  layer outside the foreground card so the source picture remains bright and
  the blurred background provides contrast. Do not darken the foreground
  video, captions, CTA, or watermark.
- Use `platform-resilient-portrait-v1` when reviewed source content or
  branding is close to a horizontal edge: keep the important foreground
  inside the shared inner band. With `auto-source-palette-v1`, the backdrop is
  a restrained palette gradient rather than source blur, so TikTok/Instagram
  lateral crop cannot be mistaken for accidental letterboxing. Legacy plans
  may retain the recorded blurred backdrop. This is one 1080x1920 asset for both TikTok and
  Instagram, not separate platform crops. If edge content is reviewed as
  nonessential, `portrait-safe-v1` may remain in use. The selected region is
  recorded in the direction, Advanced plan, render input, QA, and delivery
  evidence; it is never inferred by silently cropping.
- For this region, the upper context preset is persistent: 64px centered Arabic
  title, at most two lines, and a `y=280` anchor below top-feed search/header
  chrome. Future plans must consume these settings rather than choosing a new
  title position ad hoc.
- Keep the official watermark fully visible inside the source picture when a
  reviewed source-logo annotation says `overlay_required_v1`. If the source
  logo is clearly visible, record `source_visible_v1` and omit the added
  watermark.
- If zoom or reframing removes the source-native logo, add exactly one cleared
  official watermark asset. Measure it against the reviewed source logo and
  keep it human-readable without dominating the composition. It may occupy
  the reviewed upper slot below the context sentence or the lower slot above
  captions, but never both. The slot must leave a measured gap from the
  sentence, frame, captions, faces, and tablet; a default top-right duplicate
  is forbidden. The current reviewed upper treatment uses the larger readable
  watermark sample and remains a draft until the full video is inspected.
- Caption the exact spoken words with measured alignment. Quran text must be
  checked against canonical text before styling; do not trust raw ASR. A
  canonical-match verification may correct ASR spelling while retaining its
  measured timing; canonical-matched display words may use the agreed green
  active-word treatment, but this is not a pronunciation claim. Human
  pronunciation review remains stronger evidence. Ordinary dialogue remains
  separate from Quran styling. Leading/trailing whitespace, punctuation,
  Arabic joining, and `هههه` reactions must be preserved or corrected from
  hashed campaign subtitle evidence.
- Keep raw ASR and transcript artifacts immutable. An ordinary-Arabic spelling
  correction requires a source-bound reviewed record containing the original
  text, corrected text, source word/window, locale, reviewer, and listening or
  context evidence; it cannot silently change alignment timing.
- Inventory every retained audible interval as dialogue, recitation, reaction,
  nasheed, silence, or uncertain. Captioned audible speech needs reviewed
  observed text. A cut interval must be marked `reviewed_excluded`. Decoded
  caption frames and ASR words alone never prove that all audible speech is
  covered.
- When a `speech-review.json` inventory is supplied, the production service
  binds its source, ASR, and transcript hashes and requires coverage of every
  retained source range before marking caption coverage complete. Missing
  inventory is insufficient evidence; stale, duplicate, malformed, or gapped
  inventory blocks the render.
- New clean Tarteel plans require that inventory. It must match the actual
  retained, corrected caption words, not merely cover their time range.
  Retained reactions/nasheed cannot be labeled excluded, uncertain speech
  cannot be delivered, and silence cannot hide aligned speech. Derive ordinary
  corrections and canonical Quran text without modifying raw alignment or
  upgrading provider/live evidence. Every word's timing, visible text and
  verification treatment must agree with the derived caption alignment.
- Keep the lower timed caption lane separate from one optional upper context
  line in the blurred background. The context line is one short, source-related
  sentence with an allowlisted emoji (`📖`, `💡`, `🎯`, `✨`, `⚡`, `🧠`, `✅`,
  `🔎`, or `🕌`). It must be bound to reviewed transcript evidence, cover the
  full approved output, fit in no more than two centered lines inside the upper
  safe lane, and not duplicate a caption phrase. A human-reviewed summary must
  record its reviewer
  and review note; otherwise the wording must equal the bound evidence exactly.
  If no defensible line exists, the render is blocked rather than filled with
  invented copy.
- The upper context line must be a reviewed, catchy, source-grounded summary
  of the actual moment, not a verbatim filler fragment. It must explain the
  challenge or payoff in one or two readable lines, use only an allowlisted emoji, and
  pass a semantic review for meaning, relevance, and non-duplication before
  planning. A generic or context-free sentence blocks the render.
- The public-readable Quran preset uses centered, enlarged lower captions and
  a larger centered upper context line. Word emphasis is bound by forced
  `word_id`, not by matching visible strings, so repeated Arabic words and
  Uthmani marks cannot silently lose their active color. Each video must bind
  its own reviewed hook/body/punch arc and opening boundary. For the current
  approved candidate only, that boundary is `احنا اليوم بإذن الله` and the
  arc retains the reviewed readiness exchange before the recitation; this is
  not a campaign-wide opening requirement.
- Before reporting a render, inspect the encoded MP4 and a contact sheet. The
  check must confirm caption accuracy against the source evidence, active-word
  styling, source-logo visibility after reframing, CTA placement after the
  final scale, portrait fill, and absence of duplicate or meaningless text.
- Keep the exact post-caption first line:
  `اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic`.
- Do not portray children negatively, invent claims, use clickbait, or add
  unrelated footage.
- Prefer 40–45 seconds for a complete story. A reviewed multi-moment edit must
  contain source-grounded hook, body, and punch beats in that order. Cuts stay
  on forced-word boundaries and use the shortest boundary padding that avoids
  silence or repeated speech.
- New Tarteel directions use the shared `direction-v2` contract. The upper
  context sentence is mandatory, scene-specific, reviewed, and full-duration.
  Every timed spoken caption is one readable RTL line; the planner regroups
  complete words before rendering and never lets Remotion wrap a caption as a
  fallback. The platform-resilient safe band reserves 96px left, 160px right,
  270px top, and 360px bottom for search/header, side rails, descriptions,
  actions, and device variation. The context, lower captions, official logo,
  and CTA must remain inside their measured lanes; any animated-bound
  collision blocks the render.

The policy evaluator, typed overlay contract, renderer preflight, QA, and
human final review must all carry the evidence. A technically encoded MP4 is
not a campaign pass when any rule is unproven.

Human playback is recorded at final review, after objective QA, and bound to
the exact MP4. Never edit the immutable viewer-evidence bundle to insert a
watch. Both audio and muted playback, observations, reviewer and player are
mandatory for clean approval. A changed or rejected artifact has no effective
approval. ASR proposals, model judgements and contact sheets alone cannot claim
that a reviewer listened or accepted the video.
