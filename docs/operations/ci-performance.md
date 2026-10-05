# CI on the single self-hosted runner

Clipforge CI runs on one machine, `clipforge-local`, with the labels `self-hosted`, `linux`, `x64`, and `clipforge`. GitHub will not run two jobs from this workflow at the same time. Eleven separate jobs therefore waited in a queue, and each one checked out the repository and prepared dependencies again.

A push to a feature branch also started a second copy of that workflow while the pull request ran the same commit. The concurrency group cancelled one of them only after both had been created. The workflow now starts from pull requests, pushes to `main`, and manual `workflow_dispatch`. A normal feature-branch push does not start CI.

## Jobs

| Job | What it runs |
| --- | --- |
| `verify-python` | Tool check, frozen `uv sync`, Ruff, mypy, `clipforge schema check`, `clipforge doctor`, and `pytest -m "not browser and not model_smoke"` |
| `verify-renderer` | Frozen `pnpm install`, renderer lint, typecheck, Vitest, then `pytest -m browser` |

`verify-renderer` waits for `verify-python`. The browser step does not start when the Python job has failed, and it does not start when the renderer checks in the same job have failed. Chrome stays at one render at a time because the smoke tests run as one pytest process on the only runner.

`model_smoke` stays out of pull-request CI. It is the existing local model-weight marker. Live VoiceStudio, live Envato, and authorized long-source campaign runs also stay off the pull-request path. Their deterministic tests still run inside `verify-python`.

## Old job map

| Previous job | Command | Now |
| --- | --- | --- |
| `python` | Ruff, mypy, pytest excluding the domain markers, schema check, doctor | `verify-python` |
| `media` | `pytest -m media` | `verify-python` |
| `transcription` | import check and `pytest -m transcription` | `verify-python` |
| `vision` | import check and `pytest -m vision` | `verify-python` |
| `candidate` | `pytest -m candidate` | `verify-python` |
| `preview` | `pytest -m preview`, including the Remotion smoke | non-browser preview tests in `verify-python`; `pytest -m browser` in `verify-renderer` |
| `review` | `pytest -m review` | same split |
| `analytics` | `pytest -m analytics` | same split |
| `benchmark` | `pytest -m benchmark` | same split |
| `hero` | `pytest -m hero` | same split |
| `renderer` | `pnpm lint`, `typecheck`, and `test` | `verify-renderer` |

The browser marker is on the tests that launch Chrome or Remotion: the preview smoke, the trimmed-span Remotion smoke, the advanced Chrome render and review page, the Hero render smoke, and the review, Hero review, analytics, and benchmark browser smokes. Every other collected test remains in `verify-python`, except `model_smoke`.

This private repository does not expose branch-protection required checks through the GitHub API. If protection is added later, the status names are `verify-python` and `verify-renderer`.

## Caches

The jobs reuse directories that survive the checkout cleanup:

- uv: `$HOME/.cache/clipforge/uv`
- pnpm: `$HOME/.cache/clipforge/pnpm`

There is no GitHub Actions cache upload. A missing tool or a failed frozen install fails the job. The workflow does not skip a suite because a cache is cold.

## Browser rule

One Chrome or Remotion render at a time. The smoke step is a single pytest process. Do not add a matrix or a second runner for it.

## When a job looks stuck

The runner accepts one job. A queued workflow is usually waiting for that job, or for a previous run that the concurrency group has not finished cancelling. On the runner host, `Runner.Listener` should be the only Actions listener. A listener left behind by a killed session has to exit before a new one can connect. Do not register a second runner to get past a stuck job.

## Local commands

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run clipforge schema check
uv run clipforge doctor
uv run pytest -m "not browser and not model_smoke"
pnpm --dir apps/renderer install --frozen-lockfile
pnpm --dir apps/renderer lint
pnpm --dir apps/renderer typecheck
pnpm --dir apps/renderer test
uv run pytest -m browser
```

The browser command needs the renderer dependencies and a local Chrome. It is the same set of tests the pull request runs after the renderer checks.
