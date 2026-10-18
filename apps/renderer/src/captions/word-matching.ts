/** Match caption runs to timed words without collapsing repeated or unverified words. */

export type CaptionWordLike = Readonly<{ text?: string; word_id?: string }>;

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
    // Uthmani pause marks belong to the preceding timed word, but are a
    // separate whitespace run in the rendered line. Match its spoken run
    // without deleting the mark from the displayed canonical text.
    const spokenRun = (words[index]?.text ?? "").trim().split(/\s+/u)[0] ?? "";
    if (captionTokenKey(spokenRun) === target) {
      return { word: words[index], nextCursor: index + 1 };
    }
  }
  return { word: undefined, nextCursor: cursor };
}

export function captionWordIsActive(
  word: CaptionWordLike | undefined,
  activeWordId: string | undefined,
  part: string,
  emphasisText: string,
  fallbackAlreadyUsed: boolean,
): boolean {
  if (activeWordId !== undefined) return word?.word_id === activeWordId;
  return !fallbackAlreadyUsed && Boolean(emphasisText) && captionTokenKey(part) === emphasisText;
}
