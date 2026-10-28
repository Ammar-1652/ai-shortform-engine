# ADR 0084: OS keyring for optional Envato bridge credentials

## Status

Accepted for local operator setup. Portal login is intentionally separate from
catalog discovery; the reviewed downloader is recorded in ADR 0085.

## Context

The official Envato MCP path provides catalog discovery but not a direct file
download. The operator's subscription bridge is a third-party web portal with
an interactive login. A password in `.env`, an ignored repository file, a
SQLite row, a job payload, or a browser profile inside the work root would be
recoverable from backups and could leak into diagnostics. Gitignore is not a
secret store.

## Decision

`clipforge assets envato auth setup` prompts only on a real local TTY and stores
the portal username/password as one versioned JSON secret in the OS Secret
Service through `secret-tool`. The record is scoped to the fixed portal origin
and service name. The password is never a CLI argument, environment variable,
JSON artifact, log, SQLite field, manifest, or schema model. Setup confirms the
password twice and verifies a keyring readback. Existing entries require
`--replace`; `auth forget --yes` removes only the local keyring entry and does
not claim to log out remotely.

`auth doctor` reports local keyring prerequisites without lookup. `auth status`
reports only whether an entry exists; it does not claim the portal session is
authenticated. The bridge downloader calls the credential store in memory,
validates the documented portal protocol, keeps browser profiles outside the
repository, and passes downloaded media and license files through the existing
Envato registration gates. A credential save is never treated as MCP
authentication, successful portal login, download, or license evidence.

## Consequences

- The operator has one-time local setup and automatic credential retrieval for
  the audited bridge without putting a secret in Clipforge artifacts.
- Headless CI, doctor, and tests do not need a keyring or account credentials.
- A desktop Secret Service and a logged-in user session are required.
- Each fetch creates a short-lived in-memory session; a credential presence
  check is never a live-session claim.
