import { describe, expect, it } from "vitest";

import { captionTokenKey, nextCaptionWord } from "./word-matching.js";

describe("caption word matching", () => {
  it("matches every repeated/unverified word in order", () => {
    const words = [{ text: " hello" }, { text: " hello" }, { text: "world." }];
    const first = nextCaptionWord("hello", words, 0);
    const second = nextCaptionWord("hello", words, first.nextCursor);
    const third = nextCaptionWord("world", words, second.nextCursor);
    expect([first.word?.text, second.word?.text, third.word?.text]).toEqual([" hello", " hello", "world."]);
  });

  it("preserves Arabic diacritics and Quran pause marks while normalizing punctuation", () => {
    expect(captionTokenKey("وَنَحْنُ،")).toBe("وَنَحْنُ");
    expect(captionTokenKey("نَفْسُهُ ۖ")).toBe("نَفْسُهُ ۖ");
  });

  it("keeps active-word identity stable when visible Arabic text repeats", () => {
    const words = [{ word_id: "first", text: " الله" }, { word_id: "second", text: " الله" }];
    const first = nextCaptionWord("الله", words, 0);
    const second = nextCaptionWord("الله", words, first.nextCursor);
    expect([first.word?.word_id, second.word?.word_id]).toEqual(["first", "second"]);
  });
});
