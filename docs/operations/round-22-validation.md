# Round 22 validation

Round 22 starts from merge `332b879f7d491ab148261c257743ef2d556cf55f` on branch `round-22-campaign-operator-control`. SQLite stays at schema 6. Contract `schema_version` stays `1.0.0`. No migration was added.

The operator selection is an append-only sidecar. `run` and `resume` call the existing campaign production runner. External publishing stays deferred. Live Whop discovery stays `not_configured`. Envato stays discovery-only. This file does not store credentials, cookies, bearer tokens, or filesystem paths.

## Commands

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run clipforge schema check
uv run clipforge doctor
pnpm --dir apps/renderer lint
pnpm --dir apps/renderer typecheck
pnpm --dir apps/renderer test
```

Local results on this branch: ruff, format, mypy, schema check, and doctor passed. Doctor reports SQLite schema version 6. Pytest: 496 passed, 1 skipped, 373 seconds. Renderer lint, typecheck, and 23 tests passed. The operator Chrome smoke is in that pytest run under the `browser` marker.

CI for the draft pull request uses the Round 21 workflow: `verify-python`, then `verify-renderer-browser`. Feature-branch pushes do not start that workflow.

## Operator surface

Read-only: `doctor`, `list`, `show`, `sources`, `verify`, `status`.

Mutating: `select`, `import`, `run`, `resume`. `serve` is a loopback GET server and rejects other methods.

`doctor` reports `whop_live: not_configured`, `envato: discovery_only`, `external_publishing: deferred`, VoiceStudio `en-US` `verified_live`, and Arabic and Japanese alignment as `alignment_not_claimed`.
