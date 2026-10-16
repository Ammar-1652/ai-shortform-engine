import { layoutCaption } from "./layout.js";
import { CAPTION_FONT_FAMILY } from "./fonts.js";
import { measuredLines } from "./measured-layout.js";

/** Caption plate. The line is a React text node, not HTML. */

export type CaptionVariant = "body" | "hook" | "punch" | "typography";

type CaptionPlateProps = {
  text: string;
  language: string;
  variant?: CaptionVariant;
  emphasisText?: string;
  x?: number;
  y?: number;
  fontSize?: number;
  style?: CaptionStyle;
  layoutVersion?: "caption-layout-v1" | "caption-layout-v2";
};

export type CaptionStyle = Readonly<{
  contrast?: string;
  font_identity?: string;
  safe_left?: number;
  safe_right?: number;
  safe_top?: number;
  safe_bottom?: number;
  accent?: string;
  max_simultaneous_emphasis?: number;
  max_travel_px?: number;
  max_scale_permille?: number;
}>;

function tokenKey(value: string): string {
  return value.trim().toLocaleLowerCase().replace(/[\u2000-\u206f\u2e00-\u2e7f'"`]/g, "");
}

export function CaptionPlate({ text, language, variant = "body", emphasisText, x, y, fontSize, style, layoutVersion = "caption-layout-v1" }: CaptionPlateProps) {
  const modern = layoutVersion === "caption-layout-v2";
  const safeMargins = {
    left: style?.safe_left ?? 64,
    right: style?.safe_right ?? 64,
    top: style?.safe_top ?? (modern ? 120 : 64),
    bottom: style?.safe_bottom ?? (modern ? 300 : 64),
  };
  const layout = layoutCaption(text, language, modern ? 22 : 12, safeMargins);
  const emphasis = (style?.max_simultaneous_emphasis ?? 1) > 0 ? tokenKey(emphasisText ?? "") : "";
  const typography = variant === "typography";
  const hook = variant === "hook";
  const punch = variant === "punch";
  const preferredSize = fontSize ?? (typography ? 82 : hook || punch ? 68 : 54);
  const horizontalInset = modern ? Math.ceil((style?.max_travel_px ?? 0) + (1080 * ((style?.max_scale_permille ?? 1000) / 1000 - 1)) / 2) + 8 : 0;
  const availableWidth = Math.min(layout.safe.right - layout.safe.left, 1080 - (x ?? layout.safe.left) - safeMargins.right) - horizontalInset * 2 - 60;
  const context = modern ? document.createElement("canvas").getContext("2d") : undefined;
  if (modern && !context) throw new Error("caption font metrics unavailable");
  const measured = modern ? measuredLines(layout.text, language, availableWidth, preferredSize, (value, size) => {
    if (!context) throw new Error("caption font metrics unavailable");
    context.font = `700 ${size}px ${CAPTION_FONT_FAMILY}`;
    return context.measureText(value).width;
  }) : { lines: layout.lines, fontSize: preferredSize, textWidth: 0 };
  const lines = measured.lines;
  const plateHeight = Math.ceil(lines.length * measured.fontSize * (typography || hook || punch ? 1.08 : 1.25) + 56);
  if (modern && y !== undefined && (y < layout.safe.top || y + plateHeight > layout.safe.bottom)) {
    throw new Error("caption card exceeds configured safe region; move or regroup it");
  }
  let highlightedTokenUsed = false;
  return (
    <div
      style={{
        position: "absolute",
        left:
          hook || punch || typography
            ? layout.direction === "rtl" && x === undefined
              ? undefined
              : x ?? layout.safe.left
            : layout.safe.left + horizontalInset,
        right:
          hook || punch || typography
            ? layout.direction === "rtl" && x === undefined
              ? safeMargins.right
              : modern ? safeMargins.right + horizontalInset : undefined
            : 1080 - layout.safe.right + horizontalInset,
        // Designed cards use their declarative y coordinate in the final
        // portrait space.  Punch cards previously ignored y and were always
        // pinned from the bottom, which made a valid punch collide with the
        // final caption.  Keep the legacy default when y is absent while
        // honoring an explicit safe-area placement.
        top:
          hook || punch || typography
            ? y ?? (modern ? hook ? layout.safe.top : layout.safe.bottom - plateHeight : hook ? 220 : 1420)
            : undefined,
        bottom: hook || punch || typography ? undefined : modern ? 1920 - layout.safe.bottom + (style?.max_travel_px ?? 0) + 32 : 220,
        direction: layout.direction,
        color: "#ffffff",
        fontFamily: modern
          ? CAPTION_FONT_FAMILY
          : typography || hook || punch
            ? "'Arial Black', 'Liberation Sans Narrow', 'DejaVu Sans', sans-serif"
            : "'DejaVu Sans', 'Arial', sans-serif",
        fontWeight: modern ? 700 : typography || hook || punch ? 900 : 750,
        fontSize: measured.fontSize,
        lineHeight: typography || hook || punch ? 1.08 : 1.25,
        letterSpacing: modern ? 0 : typography || hook ? 1.2 : 0,
        textTransform: !modern && typography ? "uppercase" : undefined,
        textAlign: hook ? "left" : layout.direction === "rtl" ? "right" : "center",
        padding: 0,
      }}
    >
      <div
        style={{
          display: "inline-block",
          width: undefined,
          marginLeft: layout.direction === "rtl" ? "auto" : undefined,
          boxSizing: "border-box",
          padding: typography ? "26px 30px" : hook ? "26px 30px 28px 28px" : punch ? "24px 26px" : "14px 22px",
          borderRadius: typography || hook || punch ? 24 : 18,
          background: typography
            ? "linear-gradient(135deg, rgba(11,18,32,0.94), rgba(24,35,62,0.88))"
            : hook
              ? "linear-gradient(100deg, rgba(9,13,24,0.96), rgba(9,13,24,0.68))"
              : punch
                ? "linear-gradient(135deg, rgba(13,20,38,0.95), rgba(15,49,63,0.88))"
                : style?.contrast === "minimal_outline"
                  ? "rgba(7,10,18,0.18)"
                  : style?.contrast === "soft_backplate"
                    ? "rgba(7,10,18,0.68)"
                    : "rgba(7,10,18,0.82)",
          border: typography || punch || style?.contrast === "minimal_outline" ? "2px solid rgba(255,205,82,0.88)" : "none",
          borderLeft: hook ? "10px solid #ffcf4a" : undefined,
          boxShadow: typography || hook || punch || style?.contrast === "outline_shadow_backplate"
            ? "0 12px 34px rgba(0,0,0,0.34)"
            : "0 5px 18px rgba(0,0,0,0.28)",
        }}
      >
        {lines.map((line, lineIndex) => {
          // Keep RTL and CJK as whole shaped runs. Splitting their characters
          // into independently styled spans can change joining, grapheme
          // shaping, or punctuation placement in the browser.
          if (layout.direction === "rtl" || /[\u3040-\u30ff\u4e00-\u9fff]/u.test(line)) {
            return <div key={`${line}-${lineIndex}`}>{line}</div>;
          }
          return (
            <div key={`${line}-${lineIndex}`}>
              {line.split(/(\s+)/).map((part, partIndex) => {
                const highlighted = Boolean(emphasis) && !highlightedTokenUsed && tokenKey(part) === emphasis;
                if (highlighted) highlightedTokenUsed = true;
                return highlighted ? (
                  <span
                    key={`${part}-${partIndex}`}
                    style={{ color: style?.accent ?? "#ffcf4a", textShadow: "0 2px 5px rgba(0,0,0,0.7)" }}
                  >
                    {part}
                  </span>
                ) : (
                  <span key={`${part}-${partIndex}`}>{part}</span>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
