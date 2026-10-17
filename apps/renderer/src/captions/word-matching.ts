/** Match caption runs to timed words without collapsing repeated or unverified words. */

export type CaptionWordLike = Readonly<{ text?: string }>;

/**
 * Normalize only punctuation/spacing that commonly differs between a cue and
 * its word timing. Arabic joining, diacritics, and Quran pause marks remain
 * untouched so the renderer never reshapes or rewrites the source text.
 */
export function captionTokenKey(value: string): string {
  return value
    .normalize("NFKC")
    .trim()
    .toLocaleLowerCase()
    .replace(/^[\u0021-\u002f\u003a-\u0040\u005b-\u0060\u007b-\u007e\u060c\u061b\u061f\u2000-\u206f\u2e00-\u2e7f]+|[\u0021-\u002f\u003a-\u0040\u005b-\u0060\u007b-\u007e\u060c\u061b\u061f\u2000-\u206f\u2e00-\u2e7f]+$/gu, "");
}

export function nextCaptionWord<T extends CaptionWordLike>(
  part: string,
  words: readonly T[],
  cursor: number,
): { word: T | undefined; nextCursor: number } {
  const target = captionTokenKey(part);
  if (!target) return { word: undefined, nextCursor: cursor };
  for (let index = Math.max(0, cursor); index < words.length; index += 1) {
    if (captionTokenKey(words[index]?.text ?? "") === target) {
      return { word: words[index], nextCursor: index + 1 };
    }
  }
  return { word: undefined, nextCursor: cursor };
}
