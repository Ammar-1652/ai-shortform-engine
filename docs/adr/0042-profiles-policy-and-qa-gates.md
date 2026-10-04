# ADR 0042: Profiles, policy, and QA gates

- Status: Accepted
- Date: 2026-10-04

## Context

Organic and paid campaigns share one production core. The repository already has `CampaignProfile`, `ComplianceRule`, `QAResult`, and `Project.profile_id`, but nothing resolved a profile from disk or blocked a later approval on technical and campaign evidence. Round 10 already renders local B-roll and SFX. Music stays prohibited.

## Decision

Profiles and policies are JSON files under `configs/`. The loader checks paths before resolving them and hashes the canonical JSON. A profile with a missing policy does not pass. The evaluator registry is a fixed Python map. JSON cannot choose an importer.

`policy-source-rights` checks the source license. `policy-asset-rights` checks every non-source asset on the current advanced plan. Unknown policies are `insufficient_evidence`.

QA is a derived artifact `qa_set_json` bound to the current `advanced_hero_draft_set_json`, the profile hash, and each policy hash. Technical QA and campaign QA are separate `QAResult` values. The aggregate status is the worst status. Empty checks cannot pass. `clipforge qa gate` succeeds only when both results pass and the live hashes still match.

The QA lock is exclusive and is taken after shared locks on prepare, transcription, vision, candidates, preview, Hero, and advanced Hero. Symlinks fail before a QA job row is inserted. ffprobe is not inside a SQLite write transaction. A failed sidecar publish removes the new artifact row and leaves the previous sidecar current. Cancellation marks the QA job `cancelled` when the row already exists.

No database migration is required. `projects.profile_id` already exists and may stay null. QA documents live in the work root and the existing artifact and job tables.

Publishing, Envato, analytics, and automatic approval stay out of this round. A later final approval must call the QA gate first.

## Consequences

- Paid and organic projects differ by policy list, not by a second renderer.
- A project with no profile cannot receive a passing QA result.
- Review pages may show the QA status. They do not show filesystem paths and they do not approve automatically.
