import { useEffect, useState } from "react";
import { cancelRender, continueRender, delayRender, staticFile } from "remotion";

export const PINNED_CAPTION_FONT_HASHES = [
  "b5d64817b6331723b5e59eaaa6db90057cbed58e9733f65687f110638192359f",
  "faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb",
  "4e5462d2e8be880317b9f49b5b2da109ddb6a3563d91cc604b67f3535832a555",
] as const;
export const CAPTION_FONT_FAMILY = "'Clipforge DejaVu', 'Clipforge Noto CJK', 'Clipforge Noto Arabic'";
export const CONCAT_EDITORIAL_FONT_HASHES = [
  "4f70ae1dd1c951e80603732344f18507d6a6932a3df9f7f6d8a91d4495d41e17",
  "a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab",
  "42c2abe5fddba9a6da76fabab653246fcf48daa3ae3fc6251e61f8215fdda006",
  "9187fa244db5f50201cfb0ede30ae7269651d090290f164c0703403fd0fab1b2",
] as const;
const CONCAT_ARABIC_FALLBACK = "'Clipforge Noto Arabic Concat', 'DejaVu Sans', sans-serif";
export const CONCAT_EDITORIAL_FONT_FAMILY = `'Clipforge Hanken', ${CONCAT_ARABIC_FALLBACK}`;
export const QURAN_FONT_FAMILY = "'Clipforge Amiri Quran', 'Clipforge Noto Arabic', serif";
const CONCAT_DISPLAY_FONT_FAMILY = `'Clipforge Anton', ${CONCAT_ARABIC_FALLBACK}`;
const CONCAT_LABEL_FONT_FAMILY = `'Clipforge Space', ${CONCAT_ARABIC_FALLBACK}`;

export function captionFontFamily(
  fontIdentity: string | undefined,
  variant: "body" | "hook" | "punch" | "typography" = "body",
): string {
  if (fontIdentity === "amiri-quran-local-v1") return QURAN_FONT_FAMILY;
  if (fontIdentity !== "concat-editorial-local-v1") return CAPTION_FONT_FAMILY;
  if (variant === "hook" || variant === "punch") return CONCAT_DISPLAY_FONT_FAMILY;
  if (variant === "typography") return CONCAT_LABEL_FONT_FAMILY;
  return CONCAT_EDITORIAL_FONT_FAMILY;
}

const pending = new Map<string, Promise<void>>();

function loadPinnedFonts(fontIdentity: string | undefined): Promise<void> {
  const pack = fontIdentity === "concat-editorial-local-v1" ? "concat" : fontIdentity === "amiri-quran-local-v1" ? "quran" : "core";
  const cached = pending.get(pack);
  if (cached) return cached;
  const files = [
    ["Clipforge DejaVu", "clipforge-dejavu-bold.ttf", "700"],
    ["Clipforge Noto CJK", "clipforge-noto-cjk-bold.ttc", "700"],
    ["Clipforge Noto Arabic", "clipforge-noto-arabic-bold.ttf", "700"],
  ];
  if (pack === "concat") {
    files.push(
      ["Clipforge Hanken", "HankenGrotesk-SemiBold.ttf", "600"],
      ["Clipforge Anton", "Anton-Regular.ttf", "400"],
      ["Clipforge Space", "SpaceGrotesk-Bold.ttf", "700"],
      ["Clipforge Noto Arabic Concat", "NotoSansArabicUI-Concat.ttf", "400"],
    );
  }
  if (pack === "quran") files.push(["Clipforge Amiri Quran", "AmiriQuran.ttf", "400"]);
  const loading = Promise.all(files.map(async ([family, file, weight]) => {
    const face = new FontFace(family ?? "", `url(${JSON.stringify(staticFile(file ?? ""))})`, { weight: weight ?? "700" });
    document.fonts.add(await face.load());
  })).then(() => undefined);
  pending.set(pack, loading);
  return loading;
}

/** All frame workers wait for the same measured local font files. */
export function useCaptionFonts(enabled: boolean, fontIdentity?: string): boolean {
  const [handle] = useState(() => enabled ? delayRender("Loading pinned caption fonts", { timeoutInMilliseconds: 10_000 }) : undefined);
  const [ready, setReady] = useState(!enabled);
  useEffect(() => {
    if (handle === undefined) return;
    void loadPinnedFonts(fontIdentity).then(() => setReady(true)).catch((error: unknown) => cancelRender(error));
  }, [fontIdentity, handle]);
  useEffect(() => { if (ready && handle !== undefined) continueRender(handle); }, [ready, handle]);
  return ready;
}
