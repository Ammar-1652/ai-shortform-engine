# ADR 0010: Single Python distribution

- Status: Accepted
- Date: 2026-10-02

## Context

The suggested tree split Python into `apps/core`, `packages/schemas`, `packages/media`, and `packages/storage`. That split matches the planes, but Round 1 has one consumer and one release. Separate distributions would need a workspace lock, three version numbers, and install instructions before any plane can be imported alone.

## Decision

Python ships as one distribution, `clipforge`, in `src/clipforge`, with modules `cli`, `schemas`, `timeline`, `storage`, and `doctor`.

TypeScript stays out of that package. The renderer is `apps/renderer` with its own `package.json`.

Example profiles and policies live in `configs/` as JSON that the contract models can parse. They are not a plugin loader.

Empty `packages/` directories were not created.

## Alternatives considered

- A uv workspace with three internal packages. Rejected for Round 1. Revisit when something outside this repo needs to import schemas without the CLI, or when the media stack grows heavy optional dependencies (ASR, OpenCV) that should not install with the control plane.
- Putting the CLI in `apps/core` and the library in `src/`. Rejected as two layouts for one import path.

## Consequences

- `uv sync` installs one project.
- A later split is a new ADR. It should move modules without changing JSON Schema titles.
- Optional ML libraries, when they arrive, should be an extra dependency group so `uv sync` on the foundation stays small.
