# ADR 0001: Local-first runtime

- Status: Accepted
- Date: 2026-10-02

## Context

The engine has to run on a developer machine, keep source footage on that machine, and stay usable without an account on a clipping product. Hosted orchestrators and hosted GPUs add cost and a second place where media can leak.

## Decision

Round 1 and the planned V1 run locally. The control plane is a Python process. State is a SQLite file. Media tools are local binaries and libraries. The renderer is a local Remotion project.

The following are out of scope until a later ADR shows a measurement that the local design cannot meet: n8n, Redis, Postgres, Docker, Kubernetes, cloud render workers, and hosted clipping APIs (Vizard, OpusClip, and similar).

## Alternatives considered

- A hosted workflow tool (n8n or a custom queue) from day one. Rejected because there is no multi-user workload yet and it splits job state away from the repo.
- Docker as the only supported install. Rejected because the target machine already has Python, ffmpeg, and Node, and a container would hide GPU setup rather than make the foundation clearer.

## Consequences

- Doctor checks the local machine instead of a cluster.
- CI does not need a GPU or a model download.
- A future server mode has to be an explicit ADR. Agents must not add one as a convenience dependency.
