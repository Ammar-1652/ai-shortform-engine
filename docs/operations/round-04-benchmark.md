# Round 4 benchmark

Synthetic only. This is not a podcast throughput number.

## Machine

EndeavourOS, Intel i7-12700H, about 15.3 GiB RAM, no swap. RTX 3060 Laptop is present and unused. Round 4 does not call CUDA.

## Input

FFmpeg color bars, 320×180, 30 fps, 6.000 s, hard cuts at 2 s and 4 s (red, blue, green). Ingested as an owned local file, then `media prepare` wrote the analysis proxy. No audio.

## First analysis

`clipforge vision analyze` on that proxy, CPU, official BlazeFace short-range model already fetched.

- scene count: 3
- representative frames: 9
- face-sampled frames: 18
- face detections: 0 (solid color; not an accuracy claim)
- runtime: 0.593 s
- analysis JSON: 18,097 bytes
- representative JPEGs: 14,310 bytes
- contact sheet: 20,220 bytes

Scene detection, decode, metrics, and face inference are inside that 0.593 s. They were not timed as separate phases on this run.

## Cache hit

The same command again: cache hit, same job id, 0.119 s. That interval is lock, hash, and SQLite checks. It does not construct the face detector.

## Model smoke, separate from the color video

Blank 64×64 RGB image.

- model load: 0.634 s
- one detect call: 0.005 s
- detections: 0

## Notes

A 6-second synthetic proxy with no faces does not predict a long talking-head source. The face model is about 230 KiB. Evidence for this clip is tens of kilobytes because the proxy is 320×180 and JPEGs are not upscaled.
