# Round 6 benchmark

Synthetic benchmark only. One generated color field and a sine tone. This is not podcast throughput, not a render-farm measurement, and not a virality result.

## Machine

- OS: EndeavourOS, Linux x86_64
- CPU: Intel Core i7-12700H, 14 cores / 20 threads
- RAM: 15 GiB, no swap
- GPU: RTX 3060 Laptop was present and unused. Remotion was started with `gl: "swangle"`.
- Node: v26.8.1
- pnpm: 10.34.6
- Browser: Google Chrome 152.0.7977.64 at `/usr/bin/google-chrome-stable`
- Remotion, `@remotion/renderer`, `@remotion/bundler`: 4.0.532
- FFmpeg: n9.0.1

## Fixture

- Input picture: 1280×720 H.264 color field, 12 seconds, about 134 KiB
- Speech: 16 kHz FLAC sine tone, same length
- Candidate duration: 12_000_000 µs, 360 output frames at 30/1
- Preview: 720×1280, contain framing
- Captions: 5 provisional cues, including `Café` and `42`
- Profile fingerprint: `899cd8dbf23a45a76f188654ed8293a0cd2d3c9e5a586a96e587e2745a9bde1b`

## Times

| Step | Seconds |
| --- | --- |
| Remotion bundle, once | 4.582 |
| One candidate render | 37.315 |
| First run, including plan and ffprobe | 42.526 |
| `preview verify` on that set | 0.013 |
| Cache hit | 0.014 |

The cache hit did not start Node or Chrome.

## Output

- MP4: 516_734 bytes
- Manifest: 3_633 bytes
- ffprobe: H.264, 720×1280, `yuvj420p`, average frame rate 30/1, AAC, duration 12.011 s
- Duration error against the TimeMap: 11 ms

## Limits

The bundle is paid once per preview set. A 25-candidate set still renders one file after another. This number is one 12 second review on a laptop, not a batch of real episodes.
