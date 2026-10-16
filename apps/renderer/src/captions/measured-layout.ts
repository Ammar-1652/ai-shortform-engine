/** Pixel-measured line breaks; measurement is injected for deterministic tests. */
export type TextMeasure = (text: string, fontSize: number) => number;

const CLOSE = /^[。、「」』！？）\u3001.,!?:;％%]/u;
const OPEN = /[（「『(]$/u;

function tokens(text: string, language: string): { parts: string[]; separator: string } {
  if (!language.toLowerCase().startsWith("ja")) return { parts: text.split(/\s+/u), separator: " " };
  const graphemes = [...new Intl.Segmenter("ja", { granularity: "grapheme" }).segment(text)].map((part) => part.segment);
  const parts: string[] = [];
  for (const grapheme of graphemes) {
    const previous = parts.at(-1);
    if (previous !== undefined && (CLOSE.test(grapheme) || OPEN.test(previous))) parts[parts.length - 1] += grapheme;
    else parts.push(grapheme);
  }
  return { parts, separator: "" };
}

export function measuredLines(
  text: string,
  language: string,
  width: number,
  preferredSize: number,
  measure: TextMeasure,
  maxLines = 3,
): { lines: readonly string[]; fontSize: number; textWidth: number } {
  if (!Number.isFinite(width) || width < 100 || !Number.isFinite(preferredSize) || preferredSize < 24) {
    throw new Error("caption measured geometry is invalid");
  }
  const { parts, separator } = tokens(text, language);
  for (let size = preferredSize; size >= 32; size -= 2) {
    const lines: string[] = [];
    let current = "";
    let oversized = false;
    for (const part of parts) {
      if (measure(part, size) > width) oversized = true;
      const next = current ? current + separator + part : part;
      if (current && measure(next, size) > width) { lines.push(current); current = part; }
      else current = next;
    }
    if (current) lines.push(current);
    if (!oversized && lines.length > 0 && lines.length <= maxLines) {
      return { lines, fontSize: size, textWidth: Math.ceil(Math.max(...lines.map((line) => measure(line, size)))) };
    }
  }
  throw new Error("caption cannot fit the safe width and readable line budget; regroup the cue");
}
