/** Verify and stage the pinned local fonts before bundling a production render. */
import { createHash } from "node:crypto";
import { copyFileSync, constants, existsSync, lstatSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const bundledFontDirectory = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../assets/fonts");

const coreFonts = [
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

// The Concat repository's Rust/WGSL effects are AGPL-3.0 and coupled to its
// native compositor, so they are not copied into this Remotion renderer. Its
// independently licensed fonts are safe to bundle and are selected by an
// explicit, fingerprinted motion style.
const concatEditorialFonts = [
  {
    name: "HankenGrotesk-SemiBold.ttf",
    sha256: "4f70ae1dd1c951e80603732344f18507d6a6932a3df9f7f6d8a91d4495d41e17",
    bundledName: "concat/HankenGrotesk-SemiBold.ttf",
    candidates: [],
  },
  {
    name: "Anton-Regular.ttf",
    sha256: "a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab",
    bundledName: "concat/Anton-Regular.ttf",
    candidates: [],
  },
  {
    name: "SpaceGrotesk-Bold.ttf",
    sha256: "42c2abe5fddba9a6da76fabab653246fcf48daa3ae3fc6251e61f8215fdda006",
    bundledName: "concat/SpaceGrotesk-Bold.ttf",
    candidates: [],
  },
  {
    name: "NotoSansArabicUI-Concat.ttf",
    sha256: "9187fa244db5f50201cfb0ede30ae7269651d090290f164c0703403fd0fab1b2",
    bundledName: "concat/NotoSansArabicUI-Concat.ttf",
    candidates: [],
  },
];

const quranEditorialFonts = [
  ...coreFonts,
  {
    name: "AmiriQuran.ttf",
    sha256: "8fa95faaf7bd18b71789f6f57312003e30c5029218a035e5baf613a0222ab82d",
    candidates: [],
  },
];

const packs = [coreFonts, concatEditorialFonts, quranEditorialFonts];

export function stageCaptionFonts(stagingDir, expected, sourceDirectory = process.env.CLIPFORGE_CAPTION_FONT_DIR) {
  const selectedPack = packs.find((pack) =>
    Array.isArray(expected) &&
    expected.length === pack.length &&
    pack.every((font, index) => font.sha256 === expected[index]),
  );
  if (!selectedPack) {
    throw new Error("caption font dependencies differ from the pinned recipe");
  }
  const fonts = selectedPack === concatEditorialFonts ? [...coreFonts, ...concatEditorialFonts] : selectedPack;
  for (const font of fonts) {
    const quranSourceDirectory = process.env.CLIPFORGE_QURAN_FONT_DIR;
    const candidates = font.name === "AmiriQuran.ttf"
      ? [
        path.join(stagingDir, font.name),
        ...(quranSourceDirectory ? [path.join(quranSourceDirectory, font.name)] : []),
        path.join(bundledFontDirectory, font.bundledName ?? font.name),
        ...font.candidates,
      ]
      : sourceDirectory
        ? [path.join(sourceDirectory, font.name)]
        : [path.join(bundledFontDirectory, font.bundledName ?? font.name), ...font.candidates];
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
