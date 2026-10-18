# Tarteel campaign hard rules

These rules are delivery gates, not creative preferences.

- Use only official Tarteel playlist footage and cleared campaign CTA and
  watermark assets.
- Add exactly one official animated CTA video. Remove its green background;
  never replace it with a still image. The CTA is muted and may not add music,
  SFX, or narration.
- Keep the CTA small (`cta_width_permille <= 600`) in the reserved
  `top_left_brand_rail_v1`. It must declare `faces_and_captions_clear_v1` and
  must not intersect a face region, the caption lane, or source branding. A
  missing clearance proof fails delivery.
- Keep the official watermark fully visible after reframing.
- Caption the exact spoken words with measured alignment. Quran text must be
  checked against canonical text before styling; do not trust raw ASR. Reviewed
  correct Quran words may be green, reviewed incorrect words red, and ordinary
  dialogue remains separate from Quran styling. Leading/trailing whitespace,
  punctuation, Arabic joining, and `هههه` reactions must be preserved or
  corrected from the source evidence.
- Keep the exact post-caption first line:
  `اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic`.
- Do not portray children negatively, invent claims, use clickbait, or add
  unrelated footage.

The policy evaluator, typed overlay contract, renderer preflight, QA, and
human final review must all carry the evidence. A technically encoded MP4 is
not a campaign pass when any rule is unproven.
