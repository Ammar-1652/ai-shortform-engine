# Profiles, policy, and QA

Organic and paid work use one production core. A profile selects compliance policies. It does not select a second editor.

## Configuration

`clipforge profile doctor`, `list`, `show`, and `verify` read `configs/profiles/` and `configs/policies/`. The files are JSON contracts. They are not executed. The loader rejects malformed JSON, unknown keys, missing `schema_version`, duplicate ids, missing policies, absolute paths, `..`, symlinks, and symlinked parent directories. Profile and policy ids are sorted before the canonical SHA-256 is computed.

`profile-organic` selects `policy-source-rights`. `profile-paid-campaign` selects `policy-source-rights` and `policy-asset-rights`. Unknown profiles and unknown policies fail closed.

`clipforge project create NAME --profile-id PROFILE_ID` validates the profile before inserting the row. `clipforge project set-profile PROJECT_ID PROFILE_ID` does the same for an existing project. A null `profile_id` stays readable. QA does not assign the organic profile by itself.

## Policy engine

The evaluator registry maps known policy ids to Python functions. A policy file cannot name a module, a shell command, or a model. `policy-source-rights` reads the current source `AssetLicenseRecord`. `policy-asset-rights` reads every non-source asset on the current advanced plan. Cleared statuses are `owned`, `licensed`, and `campaign_provided`, and each one needs evidence. `unknown`, `prohibited`, a missing record, a hash mismatch, a symlink, and a remote URL are not passes. An unknown policy id is `insufficient_evidence`.

## QA set

`clipforge qa run SOURCE_ID` evaluates the current `advanced_hero_draft_set_json`. It does not fall back to a rough preview and it does not render. Technical checks cover the artifact row, provenance, producer hashes, manifest, media files, ffprobe, intervals, reframing, remote URLs, and asset rights. Campaign checks are one check per resolved policy.

The `qa_set_json` artifact stores a `QASetDocument`. Aggregate status is the worst of the technical and campaign results. A pass cannot hide a failed or incomplete check. The sidecar `qa-set.recipe.json` becomes current only after the manifest and the artifact row are written. A sidecar failure deletes the new artifact row and leaves the previous sidecar in place.

`qa verify` and `qa gate` re-read the live profile, policies, artifact, and producers. They do not rewrite the set. The gate succeeds only when both kinds are `pass` and the hashes still match. That gate is the prerequisite for any later publishing work. This round does not publish.

Lock order for a QA run is prepare shared, transcribe shared, vision shared, candidate shared, preview shared, hero shared, advanced shared, then QA exclusive. ffprobe runs after the QA job row is inserted and outside the SQLite write transaction. A symlink in the advanced media path is rejected before that job row is inserted.

SQLite schema version stays 4. The project `profile_id` column already existed.
