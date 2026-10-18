# Tarteel campaign hard rules

These rules are delivery gates, not creative preferences.

- Use only official Tarteel playlist footage and cleared campaign CTA and
  watermark assets.
- Add exactly one official animated CTA video. Remove its green background;
  never replace it with a still image. The CTA is muted and may not add music,
  SFX, or narration.
- Render the original source picture over a blurred copy with a restrained
  zoom. Both the CTA and the optional watermark belong to that original
  foreground picture. Keep the CTA small (`cta_width_permille <= 600`) in the
  `foreground_attention_v1` region. It must declare
  `faces_and_captions_clear_v1` and must not intersect a face region, captions,
  or source branding. A missing clearance proof fails delivery.
- Keep the official watermark fully visible inside the source picture when a
  reviewed source-logo annotation says `overlay_required_v1`. If the source
  logo is clearly visible, record `source_visible_v1` and omit the added
  watermark.
- Caption the exact spoken words with measured alignment. Quran text must be
  checked against canonical text before styling; do not trust raw ASR. A
  canonical-match verification may correct ASR spelling while retaining its
  measured timing; canonical-matched display words may use the agreed green
  active-word treatment, but this is not a pronunciation claim. Human
  pronunciation review remains stronger evidence. Ordinary dialogue remains
  separate from Quran styling. Leading/trailing whitespace, punctuation,
  Arabic joining, and `هههه` reactions must be preserved or corrected from
  hashed campaign subtitle evidence.
- Keep the lower timed caption lane separate from one optional upper context
  line in the blurred background. The context line is one short, source-related
  sentence with an allowlisted emoji (`📖`, `💡`, `🎯`, `✨`, `⚡`, `🧠`, `✅`,
  `🔎`, or `🕌`). It must be bound to reviewed transcript evidence, cover the
  full approved output, fit on one line inside the upper safe lane, and not
  duplicate a caption phrase. A human-reviewed summary must record its reviewer
  and review note; otherwise the wording must equal the bound evidence exactly.
  If no defensible line exists, the render is blocked rather than filled with
  invented copy.
- The upper context line must be a reviewed, catchy, source-grounded summary
  of the actual moment, not a verbatim filler fragment. It must explain the
  challenge or payoff in one readable line, use only an allowlisted emoji, and
  pass a semantic review for meaning, relevance, and non-duplication before
  planning. A generic or context-free sentence blocks the render.
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

The policy evaluator, typed overlay contract, renderer preflight, QA, and
human final review must all carry the evidence. A technically encoded MP4 is
not a campaign pass when any rule is unproven.
