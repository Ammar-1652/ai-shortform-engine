# Caption font dependencies

The clean Hero and Advanced Hero recipes use only locally staged, pinned font
files. The renderer never requests a remote font. Before a production bundle,
the Node staging step copies these files into that run's public staging
directory and verifies the SHA-256 listed here; a missing file, symlink, or
changed hash fails the render.

| Staged file | Purpose | SHA-256 | License evidence |
|---|---|---|---|
| `clipforge-dejavu-bold.ttf` | Latin and general fallback | `b5d64817b6331723b5e59eaaa6db90057cbed58e9733f65687f110638192359f` | `/usr/share/licenses/ttf-dejavu/LICENSE` (Bitstream Vera / DejaVu license) |
| `clipforge-noto-cjk-bold.ttc` | Japanese/CJK glyph coverage | `faa5f3656a78b2e2d450d27fe8382c778bc2b6bb5ea29c986664a6a435056ceb` | `/usr/share/licenses/noto-fonts-cjk/LICENSE` (SIL Open Font License) |
| `clipforge-noto-arabic-bold.ttf` | Arabic shaping and glyph coverage | `4e5462d2e8be880317b9f49b5b2da109ddb6a3563d91cc604b67f3535832a555` | `/usr/share/licenses/noto-fonts/LICENSE` (SIL Open Font License) |

`CLIPFORGE_CAPTION_FONT_DIR` may point to a directory containing files with
these exact staged names for a controlled local installation. It cannot bypass
hash verification. The three hashes are carried in the render input/profile
fingerprint, so changing a font creates a new artifact identity and invalidates
old QA, final review, and delivery evidence.

The opt-in `concat-editorial-v1` motion style stages an additional local pack
of Hanken Grotesk, Anton, Space Grotesk, and Noto Sans Arabic UI files. Their
individual licenses, upstream commit, and hashes are recorded in
[the Concat motion asset provenance note](concat-motion-assets.md). The style
does not copy or execute Concat's AGPL Rust/WGSL effects.
