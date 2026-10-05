# CI on the single self-hosted runner

Clipforge CI runs on one machine, `clipforge-local`, with the labels `self-hosted`, `linux`, `x64`, and `clipforge`. GitHub will not run two jobs from this workflow at the same time. The previous workflow queued eleven jobs, and each one checked out the repository and prepared dependencies again.

A push to a feature branch also started a second copy while the pull request ran the same commit. The concurrency group cancelled one copy only after both had been created. CI now starts from pull requests, pushes to `main`, and manual `workflow_dispatch`. A normal feature-branch push does not start CI.

Fork pull requests still do not run. The job condition requires the head repository to be this repository, so a fork does not receive the self-hosted runner.

## Jobs

| Job | What it runs |
| --- | --- |
| `verify-python` | Tool check, frozen `uv sync`, Ruff, mypy, `clipforge schema check`, `clipforge doctor`, and `pytest -m "not browser and not model_smoke"` |
| `verify-renderer-browser` | Frozen `pnpm install`, renderer lint, typecheck, Vitest, then `pytest -m browser` |

`verify-renderer-browser` waits for `verify-python`. The browser step does not start when the Python job has failed, and it does not start when the renderer checks in the same job have failed. Chrome stays at one render at a time because the smoke tests run as one pytest process on the only runner.

`model_smoke` stays out of pull-request CI. It is the existing local model-weight marker and currently collects no tests. Live VoiceStudio, live Envato, and authorized long-source campaign runs also stay off the pull-request path. Their deterministic tests still run inside `verify-python`.

## Old job map

| Previous job | Command | Now |
| --- | --- | --- |
| `python` | Ruff, mypy, pytest excluding the domain markers, schema check, doctor | `verify-python` |
| `media` | `pytest -m media` | `verify-python` |
| `transcription` | import check and `pytest -m transcription` | `verify-python` |
| `vision` | import check and `pytest -m vision` | `verify-python` |
| `candidate` | `pytest -m candidate` | `verify-python` |
| `preview` | `pytest -m preview`, including the Remotion smoke | non-browser preview tests in `verify-python`; `pytest -m browser` in `verify-renderer-browser` |
| `review` | `pytest -m review` | same split |
| `analytics` | `pytest -m analytics` | same split |
| `benchmark` | `pytest -m benchmark` | same split |
| `hero` | `pytest -m hero` | same split |
| `renderer` | `pnpm lint`, `typecheck`, and `test` | `verify-renderer-browser` |

The `browser` marker is only on tests that launch Chrome or Remotion:

- `tests/test_preview_smoke.py`
- `tests/test_round19_render.py::test_real_remotion_preview_uses_the_trimmed_span`
- `tests/test_advanced_hero_chrome.py`
- `tests/test_hero_smoke.py`
- `tests/test_review_browser.py`
- `tests/test_hero_review_browser.py`
- `tests/test_round14_browser.py`
- `tests/test_round15_browser.py`

The other tests in `tests/test_round19_render.py` do not launch a browser and stay in `verify-python`. Markers such as `preview` and `hero` are not treated as browser tests by themselves.

This private repository does not expose branch-protection required checks through the GitHub API. If protection is added later, the status names are `verify-python` and `verify-renderer-browser`.

## Caches

The jobs reuse directories that survive the checkout cleanup:

- uv: `$HOME/.cache/clipforge/uv`
- pnpm: `$HOME/.cache/clipforge/pnpm-store`

There is no GitHub Actions cache upload. A missing tool or a failed frozen install fails the job. The workflow does not skip a suite because a cache is cold.

## Browser rule

One Chrome or Remotion render at a time. The smoke step is a single pytest process. Do not add a matrix or a second runner for it.

After a local smoke, check for leftovers:

```text
pgrep -af 'chrome|chromium|node|remotion' || true
```

Stop a Chrome process only when its command line is a headless test profile you started. Do not stop the desktop browser or the Actions listener.

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
