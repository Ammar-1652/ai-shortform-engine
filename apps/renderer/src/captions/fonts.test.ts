import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  CAPTION_FONT_FAMILY,
  CONCAT_EDITORIAL_FONT_FAMILY,
  CONCAT_EDITORIAL_FONT_HASHES,
  captionFontFamily,
} from "./fonts.js";

describe("Concat editorial font pack", () => {
  it("uses the audited local stack only when the style requests it", () => {
    expect(captionFontFamily("concat-editorial-local-v1")).toBe(CONCAT_EDITORIAL_FONT_FAMILY);
    expect(captionFontFamily("concat-editorial-local-v1", "hook")).toContain("Clipforge Anton");
    expect(captionFontFamily("dejavu-noto-local-v1")).toBe(CAPTION_FONT_FAMILY);
    expect(CONCAT_EDITORIAL_FONT_HASHES).toHaveLength(4);
  });

  it("keeps the bundled font bytes bound to their pinned hashes", () => {
    const root = resolve(dirname(fileURLToPath(import.meta.url)), "../../assets/fonts/concat");
    const files = [
      "HankenGrotesk-SemiBold.ttf",
      "Anton-Regular.ttf",
      "SpaceGrotesk-Bold.ttf",
      "NotoSansArabicUI-Concat.ttf",
    ];
    for (const [index, file] of files.entries()) {
      const digest = createHash("sha256").update(readFileSync(resolve(root, file))).digest("hex");
      expect(digest).toBe(CONCAT_EDITORIAL_FONT_HASHES[index]);
    }
  });
});
