#!/usr/bin/env bash
# Full check. Fails on the first error. Does not download models.
# pytest includes ffmpeg integration tests. Install ffmpeg from the OS if they fail at startup.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run clipforge schema check

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is not on PATH. Install it, then re-run scripts/validate.sh." >&2
  exit 1
fi

( cd "$root/apps/renderer" && pnpm lint && pnpm typecheck && pnpm test )
uv run clipforge doctor
