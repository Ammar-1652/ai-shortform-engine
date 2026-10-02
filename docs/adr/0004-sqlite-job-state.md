# ADR 0004: SQLite for job state

- Status: Accepted
- Date: 2026-10-02

## Context

Projects, source pointers, jobs, artifact pointers, and reviews have to survive a process restart and stay on one machine. The relational shape of those five records is small. Most future documents are versioned JSON.

## Decision

State is one SQLite file. Default path: `var/clipforge.sqlite3` (gitignored). Override with `--db` or `DATABASE_PATH`.

Migrations are a tuple in `clipforge.storage.migrations`. The code applies pending versions inside a transaction and records them in `schema_migrations` and `PRAGMA user_version`. If those two numbers disagree, the file is rejected. Alembic is not used.

Connections are opened per operation. There is no process-global connection. `:memory:` is rejected because separate connections would not share it.

Tables in version 1: `projects`, `source_assets`, `jobs`, `artifacts`, `reviews`. Wider contract documents stay JSON (in columns or in artifact files) until a query needs a real column. JSON that fails validation fails the read.

## Alternatives considered

- Postgres. Rejected for V1 by ADR 0001. Nothing we store needs a server.
- Alembic. Rejected at this size. One SQL string and a version integer are easier to audit. Revisit if migrations grow branching or data backfills.
- A JSON file per project and no database. Rejected because job status and review history need transactions.

## Consequences

- Tests use temporary files.
- A newer database than the binary is an error, not a best-effort read.
- Adding a column is a new migration version, not an edit to version 1 after release.
