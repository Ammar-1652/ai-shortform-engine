# Media ingest and preprocessing

Round 2 reads a local video file, records its rights and fingerprint, and builds two derived files. It does not transcribe, detect scenes, score candidates, or render a reel.

The normative clock is [ADR 0013](../adr/0013-canonical-media-time-origin.md). Storage of the original is [ADR 0014](../adr/0014-referenced-source-storage.md). Recipes and the cache are [ADR 0015](../adr/0015-derived-media-recipes-and-cache.md). Disk checks are [ADR 0016](../adr/0016-storage-safety.md). The new table is [ADR 0017](../adr/0017-source-manifests.md).

## What ingest accepts

`clipforge source ingest` takes an existing project and a filesystem path. `http`, `https`, `s3`, `ftp`, YouTube, TikTok, Instagram, Google Drive, and any other `://` scheme are rejected. Nothing is downloaded. The path must be a readable regular file. Spaces and non-ASCII names are ordinary paths, passed as argv entries, never through a shell.

Ingest requires `--rights-status` of `owned`, `licensed`, or `campaign_provided`, a `--rights-name`, a `--rights-evidence` file or http(s) reference, and `--confirm-rights`. That flag stores your assertion on an `AssetLicenseRecord`. It is not an independent legal review. `unknown` and `prohibited` stay blocked, and a cleared status without evidence stays blocked, because `require_rights_cleared` is unchanged.

The rights row is inserted before the source row, in the same short transaction. The source URI is the original `file:` URI. The bytes are not copied.

The same bytes in the same project deduplicate only when the selected video and audio streams match. A different selection is an error. Clipforge does not change the stored manifest and does not create a second stream variant in that project.

`media prepare` holds an exclusive file lock on that source before it deletes partials or updates job rows. A second prepare of the same source fails while the first one is alive. A `running` job left behind by a crashed process is marked failed only after the new process holds the lock.

## Clock and streams

Automatic video choice skips attached pictures, prefers `disposition.default`, then the lowest usable index. Automatic audio choice uses the same rule. `--video-stream` and `--audio-stream` take the ffprobe stream index. An index that is not a usable stream of that type fails. There is no fallback.

A video with no audio ingests. `transcription_eligible` is false. Prepare does not write `asr.flac`. Verify reports that as expected.

Canonical `t=0` is the first presentation timestamp of the selected video. Delayed audio is padded with silence. Early audio is trimmed. Speech samples are not stretched. The duration evidence string records which field was used, including an assumed zero start.

Frame timing is `cfr_likely` when `avg_frame_rate` and `r_frame_rate` are equal positive rationals, `vfr_possible` when they differ, and `unknown` when either is missing. HDR is `pq` for `smpte2084`, `hlg` for `arib-std-b67`, and `none` otherwise. `none` means those tags were absent, not that the grade was confirmed SDR. PQ and HLG fail proxy generation before ffmpeg. Round 2 does not convert HDR to SDR.

## Derived files

Work layout:

```text
$WORK_ROOT/projects/<project_id>/sources/<source_asset_id>/
  metadata/ffprobe.json
  metadata/ingest-manifest.json
  metadata/analysis-proxy.recipe.json
  metadata/asr-audio.recipe.json
  audio/asr.flac
  proxy/analysis.mp4
  logs/
```

The ASR filter, for a selected audio stream, is conceptually:

```text
mono, resample to 48 kHz
if audio starts before video t=0: atrim that lead-in
if audio starts after video t=0: concat generated silence of that length
apad/atrim to the canonical video duration
resample to 16 kHz s16 FLAC
```

The proxy filter bakes display rotation with `transpose` for 90, 180, and 270 degrees, scales to an even size inside a 1280 long edge without upscaling, deletes the display-matrix side data so a player does not rotate the pixels twice, and encodes with libx264, `veryfast`, CRF 28, `yuv420p`, `fps_mode passthrough`. Odd dimensions can lose at most one pixel per side so H.264 can use `yuv420p`. That is not a creative crop. Non-right-angle rotation fails rather than guessing a resample.

Duration must land within `max(100 ms, three frame periods)` of the canonical duration. The artifact is hashed, fsynced, and renamed onto its final name only after ffprobe accepts it.

## Tests

`tests/media_factory.py` builds short files with ffmpeg in a temporary directory. Nothing binary is committed. The delayed-audio test measures silence with `volumedetect`, not by listening. The early-audio test puts 200 Hz before video `t=0` and 2000 Hz after it, then checks that the ASR file starts in the higher band. `pytest -m media` is the integration job. `pytest -m "not media"` is the unit job and does not need ffmpeg. Full `pytest` runs both.

Rotation fixtures are remuxed with `-display_rotation` because this ffmpeg does not keep a `rotate` tag through libx264. HDR fixtures pass `x264-params` `transfer=smpte2084` for the same reason. Both are metadata tests. They are not graded HDR masters.

The early-audio fixture shifts the picture with `setpts=PTS+0.5/TB`, keeps those timestamps with `-fps_mode passthrough`, and sets `-muxdelay 0`. Without that, ffmpeg 6's MP4 muxer reported both streams at start 0. The audio is 0.5 seconds of 200 Hz followed by 2000 Hz.
