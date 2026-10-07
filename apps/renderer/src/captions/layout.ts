/** Language-aware caption lines. Text stays a string. Markup is refused. */

export type CaptionDirection = "ltr" | "rtl";

export type CaptionLayout = {
  readonly text: string;
  readonly direction: CaptionDirection;
  readonly lines: readonly string[];
  readonly safe: { readonly left: number; readonly right: number; readonly top: number; readonly bottom: number };
};

const SAFE_MARGIN = 64;
const FRAME_WIDTH = 1080;
const FRAME_HEIGHT = 1920;
const FORBIDDEN_START = new Set(["。", "、", "！", "？", "」", "）", "』"]);
const FORBIDDEN_END = new Set(["（", "「", "『"]);

function localeFamily(language: string): "en" | "fr" | "ja" | "ar" {
  const normalized = language.trim().toLowerCase();
  if (normalized === "en" || normalized.startsWith("en-")) return "en";
  if (normalized === "fr" || normalized.startsWith("fr-")) return "fr";
  if (normalized === "ja" || normalized.startsWith("ja-")) return "ja";
  if (normalized === "ar" || normalized.startsWith("ar-")) return "ar";
  throw new Error(`unsupported caption locale: ${language}`);
}

export function layoutCaption(text: string, language: string, maxChars = 12): CaptionLayout {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) {
    throw new Error("caption text is empty");
  }
  if (normalized.includes("<") || normalized.includes(">")) {
    throw new Error("caption text is not html");
  }
  const family = localeFamily(language);
  const direction: CaptionDirection = family === "ar" ? "rtl" : "ltr";
  const cjk = family === "ja";
  const lines = cjk ? wrapCjk(normalized, maxChars) : wrapWords(normalized, maxChars);
  return {
    text: normalized,
    direction,
    lines,
    safe: {
      left: SAFE_MARGIN,
      right: FRAME_WIDTH - SAFE_MARGIN,
      top: SAFE_MARGIN,
      bottom: FRAME_HEIGHT - SAFE_MARGIN,
    },
  };
}

export function wrapWords(text: string, width: number): string[] {
  if (width < 1) {
    throw new Error("caption width must be positive");
  }
  const words = text.trim().split(/\s+/);
  if (words.some((word) => word.length === 0)) {
    throw new Error("caption text is empty");
  }
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    if (current.length === 0) {
      current = word;
      continue;
    }
    const joined = `${current} ${word}`;
    if (joined.length > width) {
      lines.push(current);
      current = word;
    } else {
      current = joined;
    }
  }
  if (current.length > 0) {
    lines.push(current);
  }
  return lines;
}

export function wrapCjk(text: string, width: number): string[] {
  if (width < 1) {
    throw new Error("caption width must be positive");
  }
  const lines: string[] = [];
  let current = "";
  for (const character of text) {
    if (current.length >= width && !FORBIDDEN_START.has(character)) {
      let carry = "";
      if (current.length > 0 && FORBIDDEN_END.has(current[current.length - 1] ?? "")) {
        carry = current[current.length - 1] ?? "";
        current = current.slice(0, -1);
      }
      if (current.length > 0) {
        lines.push(current);
      }
      current = carry + character;
    } else {
      current += character;
    }
  }
  if (current.length > 0) {
    lines.push(current);
  }
  return lines;
}

export function plateInsideSafeArea(layout: CaptionLayout): boolean {
  return (
    layout.safe.left >= SAFE_MARGIN &&
    layout.safe.right <= FRAME_WIDTH - SAFE_MARGIN &&
    layout.safe.top >= SAFE_MARGIN &&
    layout.safe.bottom <= FRAME_HEIGHT - SAFE_MARGIN &&
    layout.lines.every((line) => line.length > 0)
  );
}
