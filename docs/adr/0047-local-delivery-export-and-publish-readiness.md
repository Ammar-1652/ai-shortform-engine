# ADR 0047: Local delivery export and publish readiness

- Status: Accepted
- Date: 2026-10-04

## Context

Round 15 is merged on main as `67ae3c3126aa8046da9cb0f6b8becb4603801395`. The benchmark can record the local chain, and an approved Advanced Hero can be rendered, but nothing copies that approved file into a portable delivery package. Calling that gap "publishing" would hide the difference between a local package and an upload to TikTok, Instagram, or YouTube.

SQLite is still schema version 6. Jobs and artifacts already store kind, status, and lineage, so a delivery package does not need a new migration.

## Decision

`clipforge publish export` copies the verified Advanced Hero MP4 into `deliveries/<delivery_id>/`. The copy is byte-for-byte. Export does not call Remotion and does not re-encode. One preflight is shared by plan, export, verify, the benchmark `publish_export` stage, and readiness. It fails closed. A failure inserts no job.

The package manifest is `publish_package_json`. The job kind is `publish_export`. The profile id is `local-delivery-v1`. Public manifests use work-root-relative paths and omit absolute paths, secrets, bearer tokens, viewer ids, credentials, remote URLs, and raw reviewer ids.

Cache identity is the input binding: source hash, candidate, candidate set, Advanced Hero set and artifact, plan, alignment, QA, approval, profile fingerprint, and destination. A hit also re-hashes every output file. A hit does not copy, does not call ffmpeg, and does not insert a job. `--force` allocates a new delivery id and leaves the previous directory in place.

Promotion writes a staging directory, validates the manifest, commits the job and artifact, renames the package into place, and then publishes `deliveries/current/<source_id>.json`. A failure restores that sidecar and does not delete an older delivery directory. Recovery marks a stale running job failed and never marks it succeeded.

Readiness keeps separate axes. `local_delivery` is `passed` only after the package verifies. `platform_publishing` is `not_implemented`. `real_source_verified` stays `unavailable` with reason `no authorized source supplied` unless an authorized source was actually supplied. A synthetic analytics fixture exercises the benchmark analytics stage and is labeled synthetic. It is not a viewer metric and does not approve or publish.

VoiceStudio stays optional. Narration is checked only when the export asks for it. Commercial output rejects unknown, prohibited, and CC-BY-NC model rights. No model is downloaded.

An unsupported destination fails with: `External platform publishing is not implemented; local delivery export is available.`

## Consequences

- Operators can hand a verified local package to a person. They still cannot upload it from Clipforge.
- A green local package is not platform publish readiness and is not real-source verification.
- The benchmark stage order ends in analytics, then `publish_export`.

## Non-goals

No TikTok, Instagram, or YouTube client. No upload route. No viewer tracking. No platform analytics ingestion. No automatic publishing. No model download.
