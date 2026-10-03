# Security

This repository is in private development. The notes below are the working policy, not a public disclosure program.

## Secrets

- Do not commit API keys, tokens, cookies, SSH private keys, `.env`, or cloud credentials.
- `.env.example` contains empty placeholders only. `clipforge` does not load dotenv files.
- GitHub CLI credentials stay in the user account (`~/.config/gh`). They are not part of this repo.
- Doctor output and logs must not print token values. A version string or "authenticated" is enough in docs, and docs must not paste a live token.

If a secret lands in a commit, rotate it, then remove it from history before anyone else fetches the repo. Do not leave it on `main` because a later commit deleted the file.

## Local media

Source ingest accepts a local regular file and no remote URL. The original is referenced in place and is not copied into the work root. Proxies, FLAC files, partial outputs, and logs live under the work root and are gitignored. Cleanup refuses a path outside that root and does not delete the source. Do not commit footage, proxies, or FLAC files. Synthetic tests generate tiny files in a temporary directory and delete them with the test.

FFmpeg is invoked with an argument list. User paths are not interpolated into a shell command. Logs store the argv and a bounded stderr tail. They do not dump the environment.

Treat footage as confidential to the rights holder even when the machine is a laptop. Do not upload it to an unrelated service to debug a proxy.

`--confirm-rights` stores the operator's assertion. It is not legal verification. `unknown` and `prohibited` remain blocked.

## Transcription

Inference runs on this machine. Clipforge does not send source audio to a remote transcription API. The only optional network step is an explicit model download into `CLIPFORGE_MODEL_ROOT` after `--allow-model-download`. A cached model is used offline. Logs must not print `HF_TOKEN` or the process environment. Model directories are not cleaned by a recursive delete command. faster-whisper is invoked in process, not through a shell.

## Visual analysis

Scene detection and face detection run on this machine against the local analysis proxy. Clipforge does not upload frames to a vision API. Stored face data is boxes, optional keypoints, and a scene-local track id. There is no face embedding, name, age, gender, or ethnicity field. Representative JPEGs and contact sheets stay under the work root and are gitignored. The MediaPipe model downloads only with `--allow-model-download` from the official `storage.googleapis.com` BlazeFace URL, into `CLIPFORGE_MODEL_ROOT`. MediaPipe Tasks runs the detector on device. Clipforge does not claim that MediaPipe itself never sends performance metrics.

## Candidate mining

Mining reads the local transcript and visual-analysis JSON. It does not upload either artifact, call a remote model, decode the proxy, or decode the ASR audio. It does not run face recognition or speaker inference. Candidate excerpts are slices of the stored transcript and stay under the work root. Do not commit `candidates.json` or other runtime JSON that contains transcript text.

## Rough previews

`preview render` reads the local analysis proxy, the local ASR FLAC, and the stored transcript. It does not upload frames, audio, transcript text, or candidate text. Remotion runs on this machine. The browser is a local executable and is not exposed as a remote debugging service by Clipforge. Caption text is drawn as ordinary text, not as HTML. Render inputs reject `http://` and `https://` media URLs. The Node process is started from an argument list. `shell=True` is not used. Preview MP4s stay under the work root and are not committed.

## Candidate review

`review open` listens on `127.0.0.1` only. It refuses `0.0.0.0` and other hosts. The page assets ship with the package. They do not reference a CDN or a remote script. Preview MP4s are served by candidate id from the current manifest. The handler rejects symlink targets and paths outside the work root. Review notes are stored and shown as text. Decision writes are rejected when the preview set changed. The server does not upload media or call an external API.

## Downloaded assets

Campaign files, stock, fonts, and music need an `AssetLicenseRecord` and an evidence URI before an edit may use them. `unknown` is not permission. A version-1 database that stored a license id without a rights row is migrated to an `unknown` record written by `clipforge-migration-2`. That row stays blocked. The migration does not mark it owned, licensed, or campaign-provided. Envato integration is not implemented. Do not drop downloaded zips into the tree.

## Dependencies

- Python dependencies are pinned via `uv.lock`.
- JavaScript dependencies are pinned via `apps/renderer/pnpm-lock.yaml`.
- Install ffmpeg from the OS. Do not vendor a binary from an ad-hoc URL.
- Do not add an MCP wrapper around a local library.
- Review new dependencies for maintainer and license before adding them. Prefer the standard library when it is enough.

## Credentials at runtime

Round 1 needs no network credential to run tests, doctor, or the database. Future Envato or publishing credentials, if an ADR adds them, must come from the environment or a user-level secret store, never from a tracked file.

## Reporting

There is no public vulnerability mailbox yet. Report issues to the repository owner directly while the repo is private. Do not file a public GitHub issue that includes footage, tokens, or an unreleased exploit against a third-party site.

## What this repository refuses to automate

- Publishing
- Treating model output as legal clearance
- Using an asset with no rights evidence
