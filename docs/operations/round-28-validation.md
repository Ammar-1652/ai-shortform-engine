# Round 28 validation

Started from main `ea8c933c821279fdf049c104f819a81ea255a31d` on branch `round-28-final-review-delivery-gate`.

Final approval is a human `ReviewDecision` with `subject_kind = final` and `automated = false`. Hero approval and a passing QA set do not authorize local delivery. Whop MCP stays deferred. External platform publishing stays deferred. SQLite schema stays 6. This file does not store credentials, cookies, bearer tokens, or filesystem paths.

## Gate

`publish export` fails with `final_approval_required` when the newest final row for the current Advanced Hero artifact is missing. `rejected` and `changes_requested` block. A newer rejection supersedes an older approval. An approval whose artifact id is not the current Advanced Hero artifact is not effective.

Changed source bytes fail before a package is copied. An empty MP4 is `corrupt_media`. A symlinked MP4 is `unsafe_path`. A stale posted manifest hash returns the reload-before-saving error. `final review verify` does not rewrite the database.

A repeated export of unchanged approved evidence is `cache_hit`. A package whose video bytes change fails `publish verify`. The previous package directory remains.

## Board

The final review page binds to `127.0.0.1`. `0.0.0.0` is refused before listen. The static page has `controls`, no `autoplay`, and no `eval(`, `innerHTML`, or remote URL. Typography such as `Café` is returned as text.

## Campaign

The production aggregate records a `final_review` stage. A source without an effective final approval is blocked. Another source is left as it was. Resume still retries the incomplete source.

## Local validation

`./scripts/validate.sh` passed: ruff, format, mypy (254 files), pytest 618 passed and 2 skipped, schema check, renderer 27 tests, and doctor with SQLite schema 6.

## Not in this round

Whop MCP was not called. No live Whop claim was made. No external platform upload was added. No SQLite migration was added.
