import { layoutCaption } from "./layout.js";

/** Caption plate. The line is a React text node, not HTML. */

export function CaptionPlate({ text, language }: { text: string; language: string }) {
  const layout = layoutCaption(text, language);
  return (
    <div
      style={{
        position: "absolute",
        left: layout.safe.left,
        right: 1080 - layout.safe.right,
        bottom: 280,
        direction: layout.direction,
        color: "#ffffff",
        fontFamily: "sans-serif",
        fontWeight: 700,
        fontSize: 54,
        lineHeight: 1.25,
        textAlign: layout.direction === "rtl" ? "right" : "center",
      }}
    >
      {layout.lines.map((line) => (
        <div key={line}>{line}</div>
      ))}
    </div>
  );
}
