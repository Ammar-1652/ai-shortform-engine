import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const source = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), "AdvancedHeroDraft.tsx"), "utf8");

describe("advanced hero composition", () => {
  it("keeps text as React children and stays local", () => {
    expect(source).not.toContain("innerHTML");
    expect(source).not.toContain("dangerouslySetInnerHTML");
    expect(source).not.toContain("eval(");
    expect(source).not.toContain("http://");
    expect(source).not.toContain("https://");
    expect(source).toContain("{typeText}");
    expect(source).toContain("diagram.payload?.left_label");
    expect(source).toContain("staticFile(brollName)");
  });
});
