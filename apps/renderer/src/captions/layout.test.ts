import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { layoutCaption, plateInsideSafeArea, wrapCjk } from "./layout.js";

const here = dirname(fileURLToPath(import.meta.url));

describe("multilingual caption plates", () => {
  it("keeps Arabic right to left without reversing characters", () => {
    const text = "مرحبا، 12!";
    const layout = layoutCaption(text, "ar");
    expect(layout.direction).toBe("rtl");
    expect(layout.text).toBe(text);
    expect(layout.lines).toEqual([text]);
    expect([...layout.text]).toEqual([...text]);
    expect(plateInsideSafeArea(layout)).toBe(true);
  });

  it("wraps Japanese without inserting spaces or splitting punctuation", () => {
    const text = "説明です。12";
    const lines = wrapCjk(text, 4);
    expect(lines.join("")).toBe(text);
    expect(lines.join("")).not.toContain(" ");
    expect(lines.some((line) => line.startsWith("。"))).toBe(false);
    const layout = layoutCaption(text, "ja", 4);
    expect(layout.direction).toBe("ltr");
    expect(layout.lines.join("")).toBe(text);
    expect(plateInsideSafeArea(layout)).toBe(true);
  });

  it("keeps mixed numbers and a long CJK line inside the safe area", () => {
    const text = "価格は１２３円です。";
    const layout = layoutCaption(text, "ja", 5);
    expect(layout.lines.join("")).toBe(text);
    expect(layout.safe.left).toBe(64);
    expect(layout.safe.right).toBe(1016);
    expect(layout.lines.some((line) => line.startsWith("。"))).toBe(false);
  });

  it("refuses markup and keeps the plate source free of remote execution", () => {
    expect(() => layoutCaption("<b>説明</b>", "ja")).toThrow(/html/);
    const source = ["layout.ts", "CaptionPlate.tsx"]
      .map((name) => readFileSync(resolve(here, name), "utf8"))
      .join("\n");
    expect(source).not.toContain("innerHTML");
    expect(source).not.toContain("eval(");
    expect(source).not.toContain("https://");
    expect(source).not.toContain("http://");
    expect(source).not.toContain("autoplay");
    expect(source).toContain("{line}");
  });
});
