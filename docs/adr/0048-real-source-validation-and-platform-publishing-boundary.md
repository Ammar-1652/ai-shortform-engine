# ADR 0048: Real-source validation and platform publishing boundary

- Status: Accepted
- Date: 2026-10-04

## Context

Round 16 is merged on main as `dcbd18ac10826cfc684c893b8b9a14e9baed1200`. Local delivery export copies an approved Advanced Hero into a directory. The benchmark can record that a package is missing, but it can also look like a tool ran when it only found an old artifact. A long pytest run also hit one Remotion `Page crashed` that passed alone. Chrome profiles and Remotion asset directories were created in the shared system temp directory, and a Node exit did not always reap the browser process group.

External upload is still not a product feature. An interface that returns `published` without a provider receipt would be a false claim.

## Decision

Each Remotion render gets a private directory under `/tmp` named `cfb` plus random characters. That directory is `TMPDIR` before Remotion is imported, and it is removed when the render returns. Nesting it under the work directory isolated the files but made Chrome abort: the singleton socket must fit in 108 bytes, and a pytest work path does not. The directory is refused when the socket path would be too long. Renders take a file lock so two browser smokes cannot overlap. After Node exits, Clipforge signals that process group before `wait()` so a leftover Chrome process is killed while the pid is still the zombie leader. The renderer log is appended, refused if the path is a symlink, and included in the failure text. There is no retry.

`clipforge benchmark run --fixture-kind real_authorized --execute` may call a missing stage. An artifact that already exists is `recorded_evidence`, not `executed_stage`. Human approval is never inserted. Transcript execution stays `unavailable` when the model is not already present, and nothing is downloaded. Without an executed, rights-cleared, verified local delivery, the report stays:

```text
real_source_verified: unavailable
reason: no authorized source supplied
```

A synthetic run adds the warning `synthetic_only`.

Platform publishing is a separate boundary. `FakePublisher` and `DryRunPublisher` do not open sockets. `clipforge publish submit` does not upload unless `CLIPFORGE_PLATFORM_LIVE_SMOKE=1` and a configured adapter exist. No production adapter is registered in this round. Attempts are append-only rows. `published` requires a receipt whose manifest hash matches. A timeout or a stale uploading job becomes `unknown`, not success. The same idempotency key and manifest return the existing attempt. Secrets are rejected before they are stored. SQLite stays at schema version 6.

## Consequences

- Local delivery can pass while external upload is `not_configured`. Overall readiness for external publishing stays `blocked_for_external_publish`.
- Operators can dry-run a target against a verified package without contacting a platform.
- Browser smokes no longer share one Chrome profile or one Remotion asset directory. The private directory stays short enough for Chrome's socket.

## Non-goals

No viewer tracking, automatic approval, EditPlan changes, analytics optimization, credential storage, or a live TikTok, Instagram, or YouTube client.
