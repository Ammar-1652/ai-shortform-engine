# ADR 0029: Candidate artifact, cache, and producer binding

- Status: Accepted
- Date: 2026-10-02

## Context

Rounds 3 and 4 showed that a new JSON file must not become current until the artifact row, the succeeded job, and the sidecar name the same run. Candidate mining has the same crash window, and it also depends on two upstream hashes. A source-hash match is not enough if the transcript or the visual analysis changed.

## Decision

One artifact row per project and source uses kind `candidate_set_json`. The file is `candidates/runs/<mining_id>/candidates.json`. The sidecar is `metadata/candidate-mining.recipe.json`. The job kind is `candidate_mine`. SQLite stays at schema version 4. There is no candidate table.

The job payload stores source, transcript, and visual identities, the combined digest, the recipe version, and the profile fingerprint. After success it also stores `mining_id` and `selected_count`. It does not store the candidate JSON.

Publication writes the JSON through a partial file, validates it, hashes it, and renames it. The log is written first. One transaction then points the artifact at that file and marks the job succeeded. The sidecar is replaced after that commit. A sidecar failure restores the previous artifact row when one existed and marks the new job failed.

Cache identity is the source hash, both upstream hashes and ids, the combined digest, recipe, profile fingerprint, and the candidate file hash. `created_at` is not identity. A second identical mine revalidates the upstream pair and returns the existing succeeded job. `--force` starts a new run and does not bypass rights, mutation, or path checks. A changed transcript or visual hash is a cache miss and a verify failure.

## Alternatives considered

- One database row per candidate. Rejected. Review rows in a later round do not need that foreign key yet, and the set is one document.
- Treat a succeeded `candidate_mine` job as proof of whatever file is on disk. Rejected. The payload `mining_id` has to match the document.

## Consequences

Mismatched document, sidecar, artifact, and job combinations fail verify and miss the cache. The previous current set stays current when a forced run fails before the sidecar is published.
