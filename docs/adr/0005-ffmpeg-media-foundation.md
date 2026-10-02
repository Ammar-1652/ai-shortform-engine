# ADR 0005: FFmpeg as the media foundation

- Status: Accepted
- Date: 2026-10-02

## Context

Probe, proxy, audio extraction, and final encode need a tool that already understands containers, time bases, and hardware decode. Writing that from scratch is out of scope.

## Decision

ffmpeg and ffprobe are the media foundation. Install them from the OS package manager. Do not vendor a binary and do not download a build from an unrelated website.

Round 1 does not invoke them for work. `clipforge doctor` reports `PASS` with the version line when they run, `WARN` when they are absent, and `FAIL` when the binary exists but exits non-zero. Absence is a warning because the foundation CLI still runs. Round 2 must treat a missing binary as a failed ingest, not as a warning inside the job.

Decode and encode flags (including NVDEC and NVENC, when the local build has them) are an ffmpeg concern. The time map does not use ffmpeg time bases. Probe results that enter our contracts are converted to integer microseconds and a rational frame rate first.

## Alternatives considered

- PyAV as the only media API. Rejected as the foundation. It can wrap ffmpeg later for specific calls, but the supported dependency is the ffmpeg CLI the operator can also run by hand.
- GStreamer. Rejected. The team would be maintaining a second media graph.

## Consequences

- CI does not need ffmpeg to test the mapper, the database, or the contracts.
- A machine without ffmpeg cannot start Round 2. Doctor says so.
- Hardware decode is optional. A missing NVIDIA encoder is not a contract failure.
