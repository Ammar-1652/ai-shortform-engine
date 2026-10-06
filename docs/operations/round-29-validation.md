# Round 29 validation

Branch `round-29-dynamic-reframing-quality`, started from `02ab8b4596da84bb777b52fe4bd4d806fbca6efd`.

## Behavior

`contain` remains the default Advanced Hero strategy. `face_follow` is opt-in and uses stored face-track geometry only. It does not identify a person, infer a speaker, or run face recognition. Unsupported evidence fails closed with a named blocker.

Whop MCP stays deferred. External platform publishing stays deferred. Arabic and Japanese alignment stay `alignment_not_claimed` unless a real provider runs. SQLite schema version stays 6.

## Checks

Run the local suite before the draft pull request:

- `uv run pytest`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy`
- `uv run clipforge schema check`
- `uv run clipforge doctor`
- `pnpm --dir apps/renderer lint`
- `pnpm --dir apps/renderer typecheck`
- `pnpm --dir apps/renderer test`
- Chrome/Remotion reframing smoke
- campaign production, final-review, local-delivery cache, and read-only verify smokes already covered by pytest

CI stays the two self-hosted jobs `verify-python` and `verify-renderer-browser`.
