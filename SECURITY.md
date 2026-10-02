# Security

This repository is in private development. The notes below are the working policy, not a public disclosure program.

## Secrets

- Do not commit API keys, tokens, cookies, SSH private keys, `.env`, or cloud credentials.
- `.env.example` contains empty placeholders only. `clipforge` does not load dotenv files.
- GitHub CLI credentials stay in the user account (`~/.config/gh`). They are not part of this repo.
- Doctor output and logs must not print token values. A version string or "authenticated" is enough in docs, and docs must not paste a live token.

If a secret lands in a commit, rotate it, then remove it from history before anyone else fetches the repo. Do not leave it on `main` because a later commit deleted the file.

## Local media

Source videos, proxies, extracts, and renders are local files under the work root or an explicit path. They are gitignored. Do not copy them into `tests/fixtures`. Fixtures are small JSON.

Treat footage as confidential to the rights holder even when the machine is a laptop. Do not upload it to an unrelated service to "debug a render".

## Downloaded assets

Campaign files, stock, fonts, and music need an `AssetLicenseRecord` and an evidence URI before an edit may use them. `unknown` is not permission. Envato integration is not implemented. Do not drop downloaded zips into the tree.

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
