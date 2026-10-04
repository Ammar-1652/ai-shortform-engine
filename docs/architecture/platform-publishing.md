# Platform publishing boundary

Local delivery and external upload are different. A verified directory is not a post on a platform.

## Adapters

`clipforge platform doctor` reports:

```text
platform_adapter: available
external_upload: not_configured
```

`FakePublisher` and `DryRunPublisher` validate a request and never open a socket. They accept only the `fake` platform, public visibility, and no schedule. `clipforge publish submit` refuses to upload unless `CLIPFORGE_PLATFORM_LIVE_SMOKE=1` and a real adapter is configured. No production adapter ships in this round, so live smoke still does not upload.

## Commands

```text
clipforge platform doctor
clipforge platform capabilities
clipforge publish dry-run SOURCE_ID CANDIDATE_ID --target TARGET_JSON
clipforge publish submit SOURCE_ID CANDIDATE_ID --target TARGET_JSON
clipforge publish status SOURCE_ID ATTEMPT_ID
clipforge publish cancel SOURCE_ID ATTEMPT_ID
```

`publish plan`, `publish export`, `publish list`, `publish show`, and `publish verify` still serve local delivery. `show`, `verify`, and `recover` accept an attempt id when the id is not a delivery id. Output separates the two:

```text
local delivery: passed
external platform: not_configured
```

or, after a dry run:

```text
local delivery: passed
external platform: dry_run_passed
```

`published` is printed only after a provider returns a receipt whose manifest hash matches the local package.

## What is stored

An attempt binds the project, source hash, candidate, delivery id, manifest hash, Advanced Hero hash, QA set, approval review, campaign profile, platform, account label, and idempotency key. It does not store tokens, cookies, passwords, or authorization headers. Account labels are public names, not provider account ids.

States are `planned`, `dry_run_passed`, `queued`, `uploading`, `published`, `failed`, `cancelled`, and `unknown`. A timeout or a recovered stale upload is `unknown`. Status on an unknown attempt does not submit again. The same idempotency key and manifest do not create a second upload. `--force` can record another attempt. A failed upload leaves the local package bytes in place.

## Benchmark

`platform_dry_run` and `platform_submit` are optional and do not call a remote platform. When a verified local package already exists, the dry-run stage uses `DryRunPublisher` and records `executed_stage` once. A later run with the same manifest is `cache_hit`. `platform_submit` stays `not_run`. A normal synthetic run is `synthetic_only`. `--execute` may prepare media that is missing and may export the local package when preflight passes. It does not treat an existing artifact as proof that WhisperX, vision, Remotion, QA, or publishing ran, and it does not approve a candidate. `real_source_verified` stays `unavailable` with reason `no authorized source supplied` unless that execute path exported a verified package for `real_authorized`.
