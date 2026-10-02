# ADR 0003: Remotion for rendering

- Status: Accepted
- Date: 2026-10-02

## Context

Hero edits need motion graphics, kinetic type, charts, mockups, and captions in a 9:16 frame. Those are component compositions, not a bag of ffmpeg filters. The team also wants a later review player.

## Decision

Remotion (React, TypeScript) is the renderer. It lives in `apps/renderer`. Round 1 creates a strict TypeScript project and does not define a reel composition. The app may depend on the `remotion` package so the version is locked, but no `Composition` is registered and no render command exists.

Call Remotion through its own CLI and libraries. Do not add a community MCP wrapper around it.

Captions and graphics take output-timeline microseconds from the exported time map. They do not re-derive jump cuts.

## Alternatives considered

- ffmpeg-only rendering. Rejected for Hero work because reusable motion components would become unreadable filter graphs. ffmpeg remains the media foundation (ADR 0005) for probe, proxy, and encode steps.
- DaVinci Resolve or another GUI NLE as the engine. Rejected because the pipeline has to be repeatable from a job record.
- A third-party "AI captions" renderer. Rejected because it would own timing and publishing outside our contracts.

## Consequences

- Round 1 locks Remotion 4.0.532, React 19.3.0, and TypeScript 5.9.3. TypeScript 7 is available but `typescript-eslint` 8.71 rejects it, so the scaffold stays on TypeScript 5.9.
- CI typechecks the scaffold without a GPU and without rendering frames.
- A real composition is a later round. Adding one in secret, with a fake success command, is a bug.
- Node 22 LTS is the minimum. The development machine may run a newer Current release. The scaffold records the floor in `package.json` `engines`.
