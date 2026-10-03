# ADR 0040: Hero review binding and approval

- Status: Accepted
- Date: 2026-10-03

## Context

Round 8 writes a separate Hero draft set and can append a `subject_kind = hero` review row. That row was not tied to the plan and alignment the reviewer actually saw, and the rough-preview page was not a complete Hero review surface. A replaced Hero render must not receive a decision for the previous file.

## Decision

`clipforge hero review open` binds only to `127.0.0.1`. Other hosts are refused before a socket is created. The page opens only after the current Hero draft set passes integrity checks. No current Hero draft is an empty page, not a successful render.

`hero_id` in the Hero routes is the candidate id inside the current manifest. The routes are:

```text
GET  /api/hero-review
GET  /api/hero-review/hero/<candidate_id>
GET  /media/hero/<candidate_id>
POST /api/review/decisions
```

Media is the `hero.mp4` named by the current manifest. Traversal, absolute paths, symlinks, and files from a previous Hero run are refused. Paths stay under the work root.

A Hero decision is a new `ReviewDecision` with `subject_kind = hero`, the candidate id, the current Hero artifact id, `automated = false`, and a server timestamp. The request must repeat the source id, source SHA-256, project id, candidate id, Hero artifact id, Hero set id, manifest SHA-256, plan id, plan SHA-256, alignment id, and alignment SHA-256 loaded by the page. A mismatch returns:

```text
The Hero set changed while this review page was open; reload before saving.
```

The effective decision is the newest row for that candidate and the current Hero artifact, ordered by `created_at` then `review_id`. Older artifact rows stay in history and are not effective. Approval does not render, publish, or change the source.

The manifest does not store an alignment checkpoint SHA, an alignment language, or an audio sample rate. The page shows those as unavailable.

## Alternatives considered

- Reuse the rough-preview page as the only Hero review surface. Rejected. A broken Hero set must not block candidate review, and a Hero page must fail closed on its own integrity checks.
- Store the decision by updating the previous row. Rejected. Review history is append-only.

## Consequences

SQLite schema stays 4. `ReviewDecision` is unchanged. Candidate review commands stay on their current routes. Hero approval is evidence only.
