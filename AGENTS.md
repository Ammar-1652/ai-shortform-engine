# Agent instructions

These rules apply to every coding agent that changes this repository. Round scope in a user prompt can add tasks. It cannot delete a rule below. A change to a rule is itself an architecture decision and needs an ADR.

## Project purpose

Clipforge is a local-first short-form production engine. It will ingest authorized long-form video, find candidate moments, rough-cut the promising ones, and spend real editorial effort only on clips a human promotes. Organic and paid work use the same core. Profiles, policies, and asset rights express the difference.

The product is not an auto-caption wrapper and it does not publish by itself.

## Non-negotiable architecture

Read [ARCHITECTURE.md](ARCHITECTURE.md) before changing boundaries between the control plane, media plane, AI decision plane, asset plane, or review plane. Read the ADRs in `docs/adr/` that touch the area you are editing.

- One production core. Do not fork a second editor for paid campaigns.
- Two editing stages. Candidate mining stays cheap. Hero edits are where motion graphics, B-roll, SFX, and precise captions belong. Do not hard-code a fixed promotion count such as "top 5".
- Compliance, rights, and user content bans are hard gates. Do not add them into a weighted score.
- A detected face is not an active speaker.
- Transcript text is not video understanding. A candidate cannot be marked ready for review on transcript evidence alone.
- First-pass ASR timestamps stay marked `approximate` until a later alignment pass on a selected clip.
- Motion graphics need a purpose from the `MotionPurpose` enum. Do not add random transition events.
- Humans approve publication. `ReviewDecision.automated` cannot be true.
- Local tools are called directly. Do not wrap ffmpeg, SQLite, or Remotion in an MCP server. Envato MCP is the planned exception because it is an external service, and it is not in scope until its round.
- Do not add n8n, Redis, Postgres, Docker, Kubernetes, a cloud renderer, or a third-party clipping SaaS unless an ADR records a measured need.
- Prefer deterministic media tools over an LLM that shells out ad-hoc ffmpeg.

Material architecture changes need a new numbered ADR. Update `ARCHITECTURE.md` in the same change. Do not bypass a typed contract with a dict or a raw SQL blob that the models would reject.

## Definition of done

A change is done when:

- The behavior is implemented without stub success paths.
- Tests cover the new behavior, including at least one failure case for anything that can be skipped or mis-timed.
- `./scripts/validate.sh` passes, or you state which command failed and why it could not be run.
- Docs that describe the behavior are updated. That includes the README when a command or a limitation changes.
- JSON Schema is regenerated and `clipforge schema check` passes when a contract changed.
- A migration is added when SQLite shape changes, and old files get an explicit error or an explicit migration. No silent rewrite.
- The diff contains no secrets, source media, model weights, rendered video, or database files.

## Media safety rules

- Do not invent a second clock. Program time is the output timeline. Source time stays on the source. B-roll in-points use `broll_source_in_us`.
- Do not call ffmpeg until the round that owns ingest. When you do, a non-zero exit, a missing binary, or a short output is a failed job with `error_message` set.
- Do not drop a transcript span, a scene, or a caption because a parser was unsure. Fail the job and keep the input.
- Do not mark a render succeeded when the output file is missing, zero bytes, or the wrong duration.
- Proxies, extracts, and renders go under the work root, which is gitignored.

## Rights and campaign compliance rules

- Every asset used in an edit needs a persisted `AssetLicenseRecord` and a non-empty evidence URI before editorial use. `unknown` and `prohibited` block use. A migration placeholder with status `unknown` is not clearance.
- `require_compliance_cleared` is the gate. An empty result list is not a pass. `insufficient_evidence` is not a pass.
- Do not treat an LLM sentence that says "PASS" as compliance truth. Store the model text as evidence only, and keep the status at `insufficient_evidence` until a deterministic rule or a human review records a pass.
- Do not download Envato or other third-party media without provenance fields and a license record.
- Campaign-provided files are still assets. They need a `campaign_provided` rights record, not an implicit allow.

## Timing and synchronization rules

- Canonical persisted time is an integer number of microseconds. Do not store canonical times as binary floats, milliseconds, or frame numbers.
- Frame rates are rational. `29.97` means `30000/1001`. Do not pass a Python float into the mapper.
- The only source-to-output conversion is `clipforge.timeline.TimeMap`, built from a `TimeMapDocument`.
- Segment list order is output order. Do not sort by source time.
- At an interior cut, `output_to_source` returns the next segment's source start. Read `docs/architecture/time-mapping.md` before changing that.
- Edit plans store `time_map_sha256`. Recompute it when the map changes. Do not update captions in place against a new map without a failing test if the digest is stale.
- Frame `n` owns `[frame_start_us(n), frame_start_us(n + 1))`. The frame that starts at the exact output endpoint is out of range.

## Dependency policy

- Python dependencies are declared in `pyproject.toml` and locked with `uv.lock`. The project interpreter is CPython 3.11.
- JavaScript dependencies live in `apps/renderer` and are locked with `pnpm-lock.yaml`. Use pnpm. Node 22 LTS is the floor.
- Do not download ASR weights, CUDA wheels, or unofficial ffmpeg builds in a foundation change.
- Add a dependency only when this repo calls it. Prefer the standard library for file and process work.

## Testing policy

- pytest for Python. Vitest for the renderer scaffold.
- Ruff formats and lints Python. mypy is strict on `clipforge`.
- TypeScript `strict` stays on.
- Tests that talk to SQLite use a temporary file, never a shared developer database.
- Do not weaken a test, skip it, or convert an error into a warning to make CI green.
- Timeline changes need cases for a single range, jump cuts, exact boundaries, overlaps, non-integer microsecond values, and 24, 25, 29.97, 30, and 60 fps.

## Git policy

- Each implementation round uses a dedicated `round-XX-*` branch. Do not commit that work directly on `main`.
- Each round ends in a draft pull request targeting `main`. Stop after the draft PR and green CI.
- Independent review happens before merge. Do not merge your own round.
- Fixes for that round stay on the same branch and the same pull request.
- Do not force-push. Do not rewrite published history.
- Run the validation script before a commit that claims the suite is green.
- Commit messages use a conventional prefix (`feat`, `fix`, `docs`, `test`, `chore`) and say what changed.
- Do not commit generated media, `.venv`, `node_modules`, or `var/`.

## Secrets policy

- No API keys, tokens, cookies, or `.env` files in git. `.env.example` values stay empty.
- Do not print `GITHUB_TOKEN`, `GH_TOKEN`, or Envato credentials in logs, docs, or doctor output.
- GitHub auth belongs to the GitHub CLI on the developer machine, outside this repo.

## Artifact provenance policy

- Derived records include `ArtifactProvenance` and at least one `source_asset_id`.
- `Scene.source_asset_id` and `FaceObservation.source_asset_id` must appear in their own provenance. A face observation stays `speaker_attribution = unknown`.
- If an artifact row sets `source_asset_id`, provenance must list that same id. If the row sets `job_id`, `provenance.job_id` must be the same id.
- Provenance names the tool and version that wrote the record.
- A missing parent is a validation error. Do not invent a placeholder source id.
- Hashes are sha256 hex when present. Do not store a hash you did not compute.

## No-silent-failures policy

- Mapper lookups raise. They do not return `None`.
- Database code raises `StorageError` with the path and the next command when a file is missing, newer than this build, or corrupt.
- A corrupt JSON column fails the read. Do not skip the row.
- CLI commands exit non-zero and print the error to stderr.
- Doctor uses `FAIL` for a broken foundation check. Do not relabel a failure as `WARN` because CI lacks a GPU. GPU absence is a `WARN` only because Round 1 does not run inference.

## Backward-compatibility policy

- Contract documents carry `schema_version`. Breaking a stored shape bumps that version and adds a reader or an explicit "too new / too old" error.
- SQLite changes are numbered migrations in `clipforge.storage.migrations`. Do not edit an applied migration in place after it has shipped. Add the next version.
- JSON Schema in `schemas/generated/` is generated. Hand-editing it is a bug. Export and commit.
- Keep the Python public names `source_to_output`, `output_to_source`, `output_frame_to_source`, `source_to_output_frame`, and `total_output_duration` stable. `total_output_duration` returns microseconds.
