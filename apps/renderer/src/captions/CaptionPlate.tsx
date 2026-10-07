import { layoutCaption } from "./layout.js";

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
};

function tokenKey(value: string): string {
  return value.trim().toLocaleLowerCase().replace(/[\u2000-\u206f\u2e00-\u2e7f'"`]/g, "");
}

export function CaptionPlate({ text, language, variant = "body", emphasisText, x, y, fontSize }: CaptionPlateProps) {
  const layout = layoutCaption(text, language);
  const emphasis = tokenKey(emphasisText ?? "");
  const typography = variant === "typography";
  const hook = variant === "hook";
  const punch = variant === "punch";
  let highlightedTokenUsed = false;
  return (
    <div
      style={{
        position: "absolute",
        left:
          hook || punch || typography
            ? layout.direction === "rtl" && x === undefined
              ? undefined
              : x ?? 64
            : layout.safe.left,
        right:
          hook || punch || typography
            ? layout.direction === "rtl" && x === undefined
              ? 64
              : undefined
            : 1080 - layout.safe.right,
        // Designed cards use their declarative y coordinate in the final
        // portrait space.  Punch cards previously ignored y and were always
        // pinned from the bottom, which made a valid punch collide with the
        // final caption.  Keep the legacy default when y is absent while
        // honoring an explicit safe-area placement.
        top: hook || punch || typography ? y ?? (hook ? 220 : 1420) : undefined,
        bottom: hook || punch || typography ? undefined : 220,
        direction: layout.direction,
        color: "#ffffff",
        fontFamily: typography || hook || punch
          ? "'Arial Black', 'Liberation Sans Narrow', 'DejaVu Sans', sans-serif"
          : "'DejaVu Sans', 'Arial', sans-serif",
        fontWeight: typography || hook || punch ? 900 : 750,
        fontSize: fontSize ?? (typography ? 82 : hook || punch ? 68 : 54),
        lineHeight: typography || hook || punch ? 1.08 : 1.25,
        letterSpacing: typography || hook ? 1.2 : 0,
        textTransform: typography ? "uppercase" : undefined,
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
                : "rgba(7,10,18,0.82)",
          border: typography || punch ? "2px solid rgba(255,205,82,0.88)" : "none",
          borderLeft: hook ? "10px solid #ffcf4a" : undefined,
          boxShadow: typography || hook || punch ? "0 12px 34px rgba(0,0,0,0.34)" : "0 5px 18px rgba(0,0,0,0.28)",
        }}
      >
        {layout.lines.map((line, lineIndex) => {
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
                    style={{ color: "#ffcf4a", textShadow: "0 0 18px rgba(255,207,74,0.45)" }}
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
