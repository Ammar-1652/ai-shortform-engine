/** Verify and stage the pinned local fonts before bundling a production render. */
import { createHash } from "node:crypto";
import { copyFileSync, constants, existsSync, lstatSync, readFileSync } from "node:fs";
import path from "node:path";

const fonts = [
  {
    name: "clipforge-dejavu-bold.ttf",
    sha256: "b5d64817b6331723b5e59eaaa6db90057cbed58e9733f65687f110638192359f",
    candidates: ["/usr/share/fonts/TTF/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
  },
  {
    name: "clipforge-noto-cjk-bold.ttc",
    sha256: "faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb",
    candidates: ["/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
  },
  {
    name: "clipforge-noto-arabic-bold.ttf",
    sha256: "4e5462d2e8be880317b9f49b5b2da109ddb6a3563d91cc604b67f3535832a555",
    candidates: ["/usr/share/fonts/noto/NotoSansArabic-Bold.ttf"],
  },
];

export function stageCaptionFonts(stagingDir, expected, sourceDirectory = process.env.CLIPFORGE_CAPTION_FONT_DIR) {
  if (!Array.isArray(expected) || expected.length !== fonts.length || fonts.some((font, index) => font.sha256 !== expected[index])) {
    throw new Error("caption font dependencies differ from the pinned recipe");
  }
  for (const font of fonts) {
    const candidates = sourceDirectory ? [path.join(sourceDirectory, font.name)] : font.candidates;
    const source = candidates.find((candidate) => existsSync(candidate));
    if (!source || lstatSync(source).isSymbolicLink() || !lstatSync(source).isFile()) {
      throw new Error(`caption font unavailable: ${font.name}; install the pinned font or set CLIPFORGE_CAPTION_FONT_DIR`);
    }
    if (createHash("sha256").update(readFileSync(source)).digest("hex") !== font.sha256) {
      throw new Error(`caption font hash changed: ${font.name}; use a new reviewed font recipe`);
    }
    const target = path.join(stagingDir, font.name);
    if (existsSync(target)) {
      if (lstatSync(target).isSymbolicLink() || !lstatSync(target).isFile() || createHash("sha256").update(readFileSync(target)).digest("hex") !== font.sha256) {
        throw new Error(`staged caption font is unsafe or changed: ${font.name}`);
      }
    } else {
      copyFileSync(source, target, constants.COPYFILE_EXCL);
    }
  }
}
