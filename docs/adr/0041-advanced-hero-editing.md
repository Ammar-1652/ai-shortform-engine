# ADR 0041: Advanced Hero editing

- Status: Accepted
- Date: 2026-10-04

## Context

Hero draft v1 force-aligns an approved candidate and renders a contained 1080×1920 draft. Round 10 adds B-roll, typography, diagrams, sound effects, semantic emphasis, and reframing. Those additions must not rewrite the Hero v1 artifact or treat a face as a speaker.

## Decision

Advanced drafts use artifact kind `advanced_hero_draft_set_json` and profile `advanced-hero-v1`. `hero-draft-v1` stays unchanged.

B-roll and SFX come from a local asset catalog plus an existing license row. The file must sit under the work root, must not be a symlink, and must match its hash. Rights must be `owned`, `licensed`, or `campaign_provided`, with evidence. `unknown`, `prohibited`, remote URLs, and Envato search or download are rejected before a render job is inserted. Overlapping B-roll is rejected. Music is not a role.

Typography and diagrams copy bounded text and numbers. HTML is not interpreted. Semantic emphasis uses forced aligned words only. Reframing strategies are explicit. A strategy without the evidence it requires fails. It does not fall back to another strategy and it does not assign a speaker.

The cache identity includes the Hero artifact, alignment, plan, visual analysis, profile, reframing digest, and asset hashes. A cache hit does not start a render. `--force` writes a new set and leaves the previous one on disk.

Approval of an advanced draft is still a `ReviewDecision`. It does not publish or render another file.

## Consequences

SQLite schema stays 4. Envato, publishing, music, speaker attribution, and face recognition stay out of this round.
