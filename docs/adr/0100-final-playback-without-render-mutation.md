# ADR 0100: Record playback in final review without mutating render artifacts

- Status: Accepted
- Date: 2026-10-22

## Context

The viewer-evidence bundle is hashed into an immutable Advanced manifest.
Its producer intentionally cannot create a human watch record. Requiring that
record inside the bundle before technical QA passed made final review
unreachable: editing the bundle invalidated its hash, while the final review
page required QA. It also failed to distinguish a watch requesting changes
from acceptance.

## Decision

Technical QA validates objective viewer evidence, speech/caption evidence,
geometry and campaign facts. It does not require human observations inside the
render producer's immutable bundle. This is not publication authorization.

For non-legacy Advanced artifacts, the existing final-review gate requires a
typed `HumanPlaybackReview` before an approved decision can be appended. It
names the exact project/source/candidate, source hash, Advanced artifact,
manifest, plan and encoded MP4 hashes. It contains explicit audio and muted
playback observations, reviewer, player, timestamp and a human acceptance
decision. Its reviewer must match the final reviewer; future dates and stale
bindings fail closed. Automated decisions remain prohibited.

The observation lives inside the existing append-only final-review sidecar,
not the render bundle. Its canonical digest participates in the existing
review evidence digest stored with `ReviewDecision`. Verification reloads
and revalidates it. A later rejection/changes request still supersedes the
approval. Rejection does not require a completed watch; an unsafe draft can
always be rejected. Historical legacy artifacts retain their recorded rules.

The loopback final-review page provides explicit checkboxes and observation
fields. `final review watch-target` prints current identity facts only;
`final review decide --watch-record FILE` accepts a strict declarative record.
Neither command invents observations or infers a watch from playback metrics.

## Consequences

QA can finish before a human watches, but clean delivery cannot. No second
approval gate or database migration is introduced. Changed render bytes,
evidence or QA invalidate effective approval through the established binding.
Final sidecars are published without replacing an existing review id; a failed
write rolls back its decision row. Independent human acceptance remains a
required external action, not an automated test result.
