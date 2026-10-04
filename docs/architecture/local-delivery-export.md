# Local delivery export

`clipforge publish` copies an approved Advanced Hero into a directory another person can carry. It does not upload that directory.

## Statuses

These are different claims:

| Status | Meaning |
| --- | --- |
| `technical_ready` | The measured local chain is present. |
| `local_delivery_ready` | A package verified: hashes, checksums, and the preflight bindings. |
| `real_source_verified` | An authorized source was supplied and checked. A synthetic fixture never sets this. |
| `platform_publish_ready` | A real platform adapter uploaded the package. None exists. |

`platform_publishing` on a readiness report is `not_implemented`. A local package does not change that.

## Preflight

`publish plan`, `publish export`, `publish verify`, the benchmark delivery stage, and readiness all call one preflight. It fails closed. Export inserts a job only after that preflight succeeds. A cache hit returns the existing succeeded package and skips ffmpeg, copying, and a new job.

The preflight requires a current source whose bytes match the stored manifest, cleared rights on the source and on every B-roll and SFX asset, a current Advanced Hero whose MP4 matches the manifest, ffprobe of `1080×1920`, H.264, AAC, and `30/1`, an effective `approved` review bound to that artifact, and a current QA set whose status is `pass` and whose bindings match. `rejected`, `changes_requested`, an approval of an older artifact, stale QA, unknown rights, prohibited rights, and CC-BY-NC narration rights for commercial output all block. Symlinks, traversal, backslashes, paths outside the work root, and remote URLs fail. Captions are written only from alignment words that already have times. Otherwise the package records `caption_mode: embedded_or_unavailable` and omits SRT and VTT.

## Package

```text
deliveries/<delivery_id>/
  manifest.json
  checksums.sha256
  candidates/<candidate_id>/
    video.mp4
    metadata.json
    captions.srt      # only with authoritative timing
    captions.vtt      # only with authoritative timing
    narration.wav     # only when narration was requested and verified
```

`video.mp4` is a byte copy of the Advanced Hero output. Paths inside `manifest.json` are relative to the work root. The current sidecar is `deliveries/current/<source_id>.json` and stores hashes, not paths.

## Commands

```text
clipforge publish doctor
clipforge publish plan SOURCE_ID CANDIDATE_ID
clipforge publish export SOURCE_ID CANDIDATE_ID
clipforge publish list SOURCE_ID
clipforge publish show SOURCE_ID DELIVERY_ID
clipforge publish verify SOURCE_ID DELIVERY_ID
clipforge publish recover SOURCE_ID DELIVERY_ID
clipforge publish resume SOURCE_ID DELIVERY_ID
```

`plan`, `list`, `show`, and `verify` do not write a job. `export --force` creates a new delivery id and keeps the old directory. `recover` marks a stale running job failed. `resume` starts a new attempt only when the previous attempt is not a verified success. Any failure exits non-zero. `blocked`, `failed`, `cancelled`, `succeeded`, and `cache_hit` stay distinct.

`--destination` other than `local` exits with: `External platform publishing is not implemented; local delivery export is available.`

## VoiceStudio

Narration is optional. Export does not require VoiceStudio unless `--narration-artifact` is set, and it does not download a model. The default `k2-fsa/` model family is not treated as commercially permitted.

## Analytics

A deterministic synthetic benchmark writes `benchmarks/fixtures/synthetic-analytics.json` and labels the analytics stage `synthetic_fixture`. That file says viewer metrics are absent. It does not approve, optimize, or publish.
