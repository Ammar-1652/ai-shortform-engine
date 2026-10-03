# ADR 0033: Deterministic Remotion rough-preview contract

- Status: Accepted
- Date: 2026-10-03

## Context

The repository already selected Remotion as the compositor. Round 6 needs a vertical review file, not a Hero edit. FFmpeg drawtext would be a second caption compositor. A browser is required to render, and this machine must not download one during a normal run.

## Decision

Python plans the candidate and writes `render-input.json`. Node renders it. The composition id is `RoughPreview`. The canvas is 720×1280 at 30/1. `duration_in_frames` is the integer Python computed from the TimeMap and `FrameRate(30, 1)`. TypeScript does not recompute that duration from floating seconds.

The picture uses `object-fit: contain` on a neutral dark plate (`#111111`). Landscape and square footage stay fully visible. There is no face crop, pan, or zoom. The proxy video is muted. Speech comes from the staged ASR FLAC, trimmed with the same `media_trim_frame`.

One preview set bundles Remotion once, then renders candidates in rank order at concurrency 1. The renderer script is invoked as an argv list. `shell=True` is not used. Remote `http(s)` media URLs are rejected. Caption text is a React text node.

The browser is `CLIPFORGE_BROWSER_EXECUTABLE` or the first regular executable among `google-chrome-stable`, `google-chrome`, `chromium`, and `chromium-browser`. Nothing is downloaded. OpenGL is `swangle`, so this round does not claim GPU rendering. CI may install a distro Chromium package. The product code does not call a package manager.

Remotion, `@remotion/renderer`, and `@remotion/bundler` stay on 4.0.532.

## Alternatives considered

- FFmpeg drawtext. Rejected. Remotion remains the compositor.
- A bundle per candidate. Rejected. It repeats the same work for every file in the set.
- A hidden browser download. Rejected. A missing browser is an actionable failure.

## Consequences

`preview doctor` reports the resolved browser and does not launch it. A render without a browser fails before a job row is inserted. Output is review quality at 720×1280, not a 1080×1920 master.
