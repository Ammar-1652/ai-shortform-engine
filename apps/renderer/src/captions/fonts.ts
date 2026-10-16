import { useEffect, useState } from "react";
import { cancelRender, continueRender, delayRender, staticFile } from "remotion";

export const PINNED_CAPTION_FONT_HASHES = [
  "b5d64817b6331723b5e59eaaa6db90057cbed58e9733f65687f110638192359f",
  "faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb",
  "4e5462d2e8be880317b9f49b5b2da109ddb6a3563d91cc604b67f3535832a555",
] as const;
export const CAPTION_FONT_FAMILY = "'Clipforge DejaVu', 'Clipforge Noto CJK', 'Clipforge Noto Arabic'";

let pending: Promise<void> | undefined;

function loadPinnedFonts(): Promise<void> {
  pending ??= Promise.all([
    ["Clipforge DejaVu", "clipforge-dejavu-bold.ttf"],
    ["Clipforge Noto CJK", "clipforge-noto-cjk-bold.ttc"],
    ["Clipforge Noto Arabic", "clipforge-noto-arabic-bold.ttf"],
  ].map(async ([family, file]) => {
    const face = new FontFace(family ?? "", `url(${JSON.stringify(staticFile(file ?? ""))})`, { weight: "700" });
    document.fonts.add(await face.load());
  })).then(() => undefined);
  return pending;
}

/** All frame workers wait for the same measured local font files. */
export function useCaptionFonts(enabled: boolean): boolean {
  const [handle] = useState(() => enabled ? delayRender("Loading pinned caption fonts", { timeoutInMilliseconds: 10_000 }) : undefined);
  const [ready, setReady] = useState(!enabled);
  useEffect(() => {
    if (handle === undefined) return;
    void loadPinnedFonts().then(() => setReady(true)).catch((error: unknown) => cancelRender(error));
  }, [handle]);
  useEffect(() => { if (ready && handle !== undefined) continueRender(handle); }, [ready, handle]);
  return ready;
}
