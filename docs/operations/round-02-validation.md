# Round 2 validation

Local validation on 2026-10-02. The draft pull request is https://github.com/Ammar-1652/ai-shortform-engine/pull/2.

CI on the branch head after the ffmpeg 6 early-audio fixture fix:

- Push run: `36987833568` — https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/36987833568 — success
- Pull request run: `36987839888` — https://github.com/Ammar-1652/ai-shortform-engine/actions/runs/36987839888 — success

Python, media integration on `ubuntu-24.04`, and the renderer job passed in both. An annotation says `ubuntu-latest` moves to Ubuntu 26 on 2026-10-19. The media job stays pinned to `ubuntu-24.04` so apt's ffmpeg stays reproducible. The other jobs were not moved.

## Baseline

- Required main SHA: `ff38583ed55e0b2ccffa05485074bfedfea8db9f`
- Verified starting SHA: `ff38583ed55e0b2ccffa05485074bfedfea8db9f`
- Branch: `round-02-media-ingest`
- Starting schema: 3
- Ending schema: 4
- New migration: `source_manifests`
- Migrations 1–3: not edited (the migration file grew by the version 4 statement only)

## Environment

- OS: EndeavourOS, kernel 7.2.3-arch1-3, x86_64
- Python: CPython 3.11.15 from `uv` (`.venv`)
- ffmpeg: `n9.0.1`
- ffprobe: `n9.0.1`
- SQLite library: 3.50.4
- Node: 26.8.1 local, CI floor 22
- pnpm: 10.34.6
- Root filesystem free at benchmark: 26,418,618,368 bytes
- `/tmp` is a 7.6 GiB tmpfs. Media tests set `CLIPFORGE_DISK_RESERVE_GB=1` so a tiny fixture can run there. The default reserve stays 10 GiB. There is no ignore flag.

## Commands

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run clipforge schema check
uv run clipforge doctor
pnpm lint && pnpm typecheck && pnpm test    # apps/renderer
```

`pytest` includes the ffmpeg integration tests. They passed on this machine.

## Results

| Check | Result |
| --- | --- |
| pytest total | 105 passed |
| media integration (`pytest -m media`) | 14 passed |
| media unit tests | 16 passed, inside the 105 |
| ruff | pass |
| ruff format | pass |
| mypy | pass, 45 source files |
| schema check | pass, 45 schema files |
| doctor | 10 pass, 0 warn, 0 fail |
| renderer lint, typecheck, vitest | pass, 3 tests |
| `shell=True` under `src/` | none |

No test in this run was skipped.

## Media behavior

- Source inspect and ingest use ffprobe JSON (`-show_format -show_streams -show_chapters`). The normalized probe is the authority. Raw JSON is stored as an artifact.
- Rights: ingest refuses to run without `--confirm-rights`. `unknown` and `prohibited` fail `require_rights_cleared` before ffmpeg. Evidence is required. The record is an operator assertion.
- Hash: streaming SHA-256. Same-project duplicate returns the existing source. A second project gets its own row. The file is not copied (`storage_mode=referenced`).
- Mutation: a changed hash fails prepare and the stored digest stays. Size and mtime alone do not count as identity.
- Streams: default disposition, then lowest index. Invalid overrides fail with no fallback. No-audio video ingests, skips ASR FLAC, and verify calls that expected.
- Clock: canonical `t=0` is the selected video's first presentation timestamp. Delayed-audio integration passed (`volumedetect` on the first 0.35 s versus a later window). Early-audio integration passed (200 Hz lead-in removed, 2000 Hz remains at the start of the FLAC).
- Proxy: H.264, even dimensions, aspect preserved, no upscale below 1280. Rotation fixture (`-display_rotation 90`) produced a 90x160 proxy from a 160x90 encode. HDR (`smpte2084`) is detected and proxy generation stops before ffmpeg.
- VFR: unequal `avg_frame_rate` and `r_frame_rate` classify as `vfr_possible` in unit tests. The synthetic file is not rejected. Packet-level VFR detection is not done.
- Storage: unit tests cover 100, 20, 12, 8, and 5 GiB free against a 10 GiB reserve. The runner is not called when the estimate would cross the reserve. The 10 second benchmark estimated 61,842,912 bytes and was allowed.
- Atomic writes: a synthetic ffmpeg failure left the job `failed`, deleted the partial, and did not create `analysis.mp4`.
- Cache: the second prepare on the benchmark added zero transcodes. Corrupt bytes, a missing file, and a recipe version bump each regenerated in the integration test.
- Database: version 2 files still upgrade, now through version 4. A manifest whose project does not match its source is rejected. `health_check` runs `quick_check` and `foreign_key_check`.

## Benchmark

See [round-02-benchmark.md](round-02-benchmark.md).

## Known limitations

- Transcription is not implemented.
- HDR is detected and refused. It is not converted and not claimed as supported.
- Frame-timing class uses the two ffprobe rates only.
- Rotation other than 0, 90, 180, and 270 fails the proxy instead of resampling.
- Even H.264 dimensions can drop one pixel per side. That is not a picture crop.
- Sources are referenced in place. Moving the file breaks later prepares.
- The disk check uses the filesystem of the work root. A tmpfs work root is smaller than the root filesystem.

## Round 3

Not started. Faster-whisper remains the next round, after this branch is reviewed. The ASR FLAC is aligned to canonical video time so that round can put words on the same clock.
