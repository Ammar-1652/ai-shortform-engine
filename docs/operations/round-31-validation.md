# Round 31 validation — portrait production repair

Date: 2026-10-07. This repair branch starts from the merged PR #31 baseline on
`origin/main` (`989bf5d6ec27878d46505dc09becedfc848cd749`).

## Production behavior

Advanced Hero render input now records the selected fit policy. `contain` keeps
the source aspect ratio inside a deliberate full-frame blurred treatment;
`center_crop` uses the stored portrait crop; and `face_follow` uses the stored
trajectory and TimeMap. The foreground video is clipped to the measured source
aspect ratio, so the video element cannot paint accidental black bars over the
background. B-roll is a deliberate full-frame crop. Unsupported strategies and
invalid face-follow evidence fail before rendering.

Grouped forced captions are separate from typography cards. Whitespace is
normalized, punctuation remains in the phrase, and captions are laid out in the
final 1080×1920 coordinate system. English, French, Japanese, and Arabic/RTL
families are accepted; an unsupported locale fails closed. A missing offline
fixture locale uses the existing `missing` sentinel fallback for layout only and
does not create language evidence.

Production Advanced Hero inputs reject `debug_overlays` and diagnostic event
ids. The previous magenta/cyan fixture panels are no longer a production
component. Numeric comparison diagrams are emitted only when the plan contains
numeric emphasis evidence.

Audio is normalized after the Remotion render to `-16 LUFS` integrated, `-1.5
dBTP` true peak, and `11 LU` LRA. Narration ducks source audio by `-12 dB`, must
match the declared edit window within 100 ms, and near-silent output is
rejected. Audio policy is part of the profile and delivery cache identity.

## Validation

The complete repository validation command passed:

```text
./scripts/validate.sh
710 passed, 2 skipped in 632.87s (0:10:32)
Schemas match schemas/generated
renderer lint: passed
renderer typecheck: passed
renderer Vitest: 6 files, 34 tests passed
clipforge doctor: 10 pass, 0 warn, 0 fail
```

Additional checks passed during the repair:

```text
uv run mypy                         # 260 source files, no issues
uv run clipforge schema check      # generated schemas match
uv run ruff check .
pnpm --dir apps/renderer typecheck
pnpm --dir apps/renderer test -- --runInBand
```

The complete suite included the real Chrome/Remotion Hero and Advanced Hero
smokes. Tesseract is not installed, so caption proof is raster/geometry proof,
not OCR proof.

## Decoded output proof

The latest real Advanced Hero smoke output was decoded and inspected at:

```text
/tmp/pytest-of-pakka/pytest-219/test_chrome_advanced_render_sh0/stack/work/projects/project-1/sources/source-1/advanced-hero/runs/2bdccee6-041b-4fdc-9dad-fea8e6c575b3/candidates/2c88a32c-c817-552f-96f8-f36f9781d195/advanced.mp4
```

The decoded 1080×1920 frame shows the source filling the portrait canvas, a
neutral diagram card, and a grouped readable caption with no magenta/cyan
diagnostic panel. `ffprobe` reports H.264, 1080×1920, 30/1, yuvj420p, AAC, and
1.216 seconds. `ffmpeg ebur128` reports `-16.0 LUFS` integrated and `-13.3 dBFS`
true peak for that short synthetic smoke clip.

Decoded proof frames and reports are kept outside the repository under:

```text
/tmp/clipforge-repair-proof/
```

They are disposable review artifacts and are not committed.

## Known limitations

Live WhisperX/VoiceStudio evidence, external asset acquisition, Whop, Envato,
and publishing remain intentionally deferred. This round does not claim those
integrations. OCR wording proof remains unavailable until a language pack is
installed; the browser tests therefore use deterministic decoded-frame geometry
and raster checks.
