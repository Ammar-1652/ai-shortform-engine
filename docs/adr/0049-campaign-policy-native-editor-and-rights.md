# ADR 0049: Campaign policy, native editing, and source rights

- Status: Accepted
- Date: 2026-10-05

## Context

The Antoine Sallis guide says "No AI edits" and "No AI subtitles." Read as a ban on outsourced black-box editors such as Opus Clips, that rule would also ban Clipforge, which is the editing system for this repository. Drive folder membership is not rights evidence. The guide is also ambiguous about newest-footage priority.

## Decision

Policy evaluation has four implementation modes:

- `external_black_box_ai_tool` is blocked.
- `clipforge_native_editor` is allowed. Native trims, candidates, Remotion, typography, captions, diagrams, transitions, mixing, and QA stay in scope.
- `human_supplied_asset` is allowed only with campaign-guide evidence and an operator confirmation. Outside stock is blocked for this campaign.
- `voice_narration_provider` needs an explicit operator decision.

Native captions are allowed only when the text is clean and a person has reviewed it. Aura, glow, skull, and emoji effects are blocked. A model caption is not an approval. Candidate and Hero approval stay human reviews.

The newest-footage rule returns `needs_operator_clarification`. Round 18 acquires only the two selected files under 200 MB. The other three catalogue files stay `not_selected_for_round_18`.

External platform publishing stays deferred and does not block technical readiness. SQLite stays at schema version 6. Campaign records are JSON artifacts, not a new migration.

## Consequences

- Operators can show the policy hash, the inventory, and an acquisition plan without downloading.
- A disabled Drive connector reports `provider_unavailable` and does not claim a download.
- Credentials, cookies, and tokens are not campaign fields.

## Non-goals

No password scraping, no unattended Whop login, and no external upload.
