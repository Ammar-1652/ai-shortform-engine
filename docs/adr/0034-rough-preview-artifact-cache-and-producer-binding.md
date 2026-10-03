# ADR 0034: Rough-preview artifact, cache, and producer binding

- Status: Accepted
- Date: 2026-10-03

## Context

Round 7 needs one current entry point for every review file of a source. One database row per candidate would multiply artifact kinds without helping that review. The preview is also only meaningful for one candidate set, one transcript, one visual analysis, one proxy, and one ASR file.

## Decision

SQLite stays at schema version 4. One current artifact per source uses kind `rough_preview_set_json`. It points at `previews/runs/<preview_set_id>/manifest.json`. The manifest lists every selected candidate in rank order, with the MP4 hash, the render-input hash, and the TimeMap hash. Per-candidate files live under that run and are not separate artifact kinds.

`preview_input_sha256` is the SHA-256 of the sorted compact JSON of the source hash, candidate-set hash, transcript hash, visual-analysis hash, proxy hash, ASR hash, and profile fingerprint. The same digest is stored on the document, the sidecar, the job payload, and `ArtifactProvenance.inputs_sha256`.

The profile fingerprint hashes every output-changing setting, including CRF. `created_at` is not identity. The sidecar is `metadata/rough-preview.recipe.json`.

A cache hit requires that identity plus a succeeded job, a matching artifact row, a matching producer payload, and every listed MP4 and render-input file at the recorded hash and size. One missing or corrupt preview is a miss. A hit does not launch Node or Chromium. `--force` revalidates, allocates a new `preview_set_id`, and leaves the previous run in place.

The job kind is `rough_preview_render`. Its payload records the bound hashes, the profile fingerprint, the recipe versions, and `cache=miss`. `preview_set_id` is added when the job succeeds. A hit returns the existing job and does not insert another row.

## Alternatives considered

- One artifact kind per candidate MP4. Rejected. Round 7 should open one current set.
- Cache on paths or mtimes. Rejected. Those change without the bytes changing, and the reverse is also true.

## Consequences

The rendered count equals the selected count, including zero. An empty set is a valid manifest and does not call the renderer. Scores may be copied onto the manifest for display. They are not render inputs and they are not cache identity.
