# ADR 0015: Derived media recipes and cache

- Status: Accepted
- Date: 2026-10-02

## Context

The analysis proxy and the ASR audio file are inputs to later rounds. A second `media prepare` on an unchanged source must not transcode again, and a damaged file must not be treated as a hit because it is sitting at the expected path.

FFmpeg can run for a long time. Holding `BEGIN IMMEDIATE` across that work would block every other writer.

## Decision

Two recipes are defined. Their version is part of cache identity. The creation timestamp is not.

- `analysis-proxy` version `1`: libx264, preset `veryfast`, CRF 28, `yuv420p`, no GPU, long edge at most 1280, no upscale, aspect preserved, even dimensions, display rotation baked in, `fps_mode passthrough`. Audio, when the source has it, is AAC at 48 kHz, 96 kb/s, mono, aligned to canonical video time. No loudness normalization.
- `asr-audio` version `1`: FLAC, mono, 16 kHz, s16, aligned to canonical video time. No denoise, enhancement, silence removal, time stretch, or pitch change. Video without audio does not get a fake speech track.

A cache hit requires the source file, the registered SHA-256, the recipe name and version, the selected stream indexes, the artifact size, the artifact SHA-256, and a fresh ffprobe validation. Any miss regenerates that artifact. A changed source hash is not a cache miss. It is the hard failure in ADR 0014.

Files are written to `name.partial.<id>.<ext>`, validated, hashed, fsynced, then renamed. A failure deletes the partial and does not leave a final file in its place. SIGINT marks the job `cancelled`. A non-zero ffmpeg exit marks it `failed`. A later prepare marks a job that is still `running` as `failed` before it starts a new one.

The job row is committed as `running` and the connection is closed before ffmpeg starts. Artifact rows and the final status are a second short transaction. SQLite is not locked for the duration of the encode.

The normalized probe in `source_manifests.probe_json` is what the application reads. The raw ffprobe JSON is a debugging artifact.

## Alternatives considered

- Key the cache on the wall-clock time. Rejected. Two identical runs would never hit.
- Trust the file because the path exists. Rejected. A truncated or edited file would be reused.
- One database transaction around ffmpeg. Rejected. It locks the project database for the whole encode.

## Consequences

Changing CRF, the scale rule, or the audio rate requires a recipe version bump. Forgetting the bump reuses old files. Round 3 transcription is not part of either recipe.
