.PHONY: doctor test lint typecheck schema fmt validate renderer-test

doctor:
	uv run clipforge doctor

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy
	cd apps/renderer && pnpm typecheck

schema:
	uv run clipforge schema check

renderer-test:
	cd apps/renderer && pnpm lint && pnpm typecheck && pnpm test

validate:
	./scripts/validate.sh
