/** Language-aware caption lines. Text stays a string. Markup is refused. */

export type CaptionDirection = "ltr" | "rtl";

export type CaptionLayout = {
  readonly text: string;
  readonly direction: CaptionDirection;
  readonly lines: readonly string[];
  readonly safe: { readonly left: number; readonly right: number; readonly top: number; readonly bottom: number };
};

const FRAME_WIDTH = 1080;
const FRAME_HEIGHT = 1920;
const DEFAULT_SAFE = { left: 64, right: 64, top: 64, bottom: 64 };
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

export type CaptionSafeMargins = Readonly<{
  left: number;
  right: number;
  top: number;
  bottom: number;
}>;

function safeCoordinates(margins: CaptionSafeMargins): CaptionLayout["safe"] {
  if (
    !Number.isInteger(margins.left) ||
    !Number.isInteger(margins.right) ||
    !Number.isInteger(margins.top) ||
    !Number.isInteger(margins.bottom) ||
    margins.left < 0 ||
    margins.right < 0 ||
    margins.top < 0 ||
    margins.bottom < 0 ||
    margins.left + margins.right >= FRAME_WIDTH ||
    margins.top + margins.bottom >= FRAME_HEIGHT
  ) {
    throw new Error("caption safe margins are invalid");
  }
  return {
    left: margins.left,
    right: FRAME_WIDTH - margins.right,
    top: margins.top,
    bottom: FRAME_HEIGHT - margins.bottom,
  };
}

export function layoutCaption(
  text: string,
  language: string,
  maxChars = 12,
  safeMargins: CaptionSafeMargins = DEFAULT_SAFE,
): CaptionLayout {
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
    safe: safeCoordinates(safeMargins),
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
    layout.safe.left >= 0 &&
    layout.safe.right <= FRAME_WIDTH &&
    layout.safe.top >= 0 &&
    layout.safe.bottom <= FRAME_HEIGHT &&
    layout.lines.every((line) => line.length > 0)
  );
}
