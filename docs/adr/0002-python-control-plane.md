# ADR 0002: Python control plane

- Status: Accepted
- Date: 2026-10-02

## Context

The control plane creates projects, stores jobs, validates contracts, and will later shell out to ffmpeg and ASR. Those libraries are Python-first. The render stack is TypeScript. One language for both would either fight Remotion or fight faster-whisper.

## Decision

Python 3.11 is the control-plane language. Typer exposes the CLI. Pydantic v2 is the contract layer. The package name is `clipforge`. The interpreter for this repo is pinned with uv (`.python-version`), not whatever `python3` happens to be on `PATH`.

Coding agents may orchestrate the pipeline during development. They call the CLI and the libraries. They are not a hidden runtime inside a render.

## Alternatives considered

- Node for the whole control plane. Rejected because the ASR and vision libraries we already selected are Python.
- A second Python package per plane in Round 1. Rejected in ADR 0010.

## Consequences

- Media processing code imports `clipforge` rather than shelling into an untyped script.
- The renderer consumes exported JSON Schema instead of importing Python.
- System Python 3.14 on the current development machine is not the project interpreter.
