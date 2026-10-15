# ADR 0074: Shared speech evidence discovery

## Status

Accepted for the first quality repair: evidence availability.

## Context

The installed, catalog-matching English, French, and Japanese speech WAV pack
was present under the operator's local data directory, but ordinary production
commands reported `speech_evidence_missing` without an exported environment
variable. Pytest supplied that variable from `tests/conftest.py`, so validation
and production used different configuration rules.

The external WAVs are provider smoke evidence. They are separate from the real
candidate ASR audio and its selected-clip forced alignment. Discovering a smoke
pack neither performs alignment nor proves lip sync or editorial quality.

## Decision

All callers use `speech_evidence_root()` to discover evidence. A non-empty
`CLIPFORGE_SPEECH_EVIDENCE_ROOT` is authoritative. Otherwise the function checks
`~/.local/clipforge-speech-evidence`, matching the installed side-interpreter
convention. A missing directory, ordinary file, or symlink root is rejected.
An invalid explicit override never falls back to the default directory.

Discovery only selects a directory. All existing WAV hash, container facts,
locale, catalog, checkpoint, model manifest, runtime, binding, producer, rights,
and stale-review checks remain required. It does not download or generate
audio, load `.env`, mutate the environment, or grant `verified_live` by itself.

Removing or changing evidence still blocks reuse. Fake alignment remains
non-live; unsupported locales retain their existing status.

Tests no longer inject the environment variable. Missing-evidence regressions
use explicit missing directories, so a valid installed pack cannot conceal
their failure cases.

## Consequences

A fresh production CLI process can use the existing verified pack without a
special shell setup. Operators may still choose another explicit directory.
No persisted contract, render recipe, SQLite migration, or existing artifact
is changed by directory discovery. Identical evidence bytes preserve existing
identity; changed or missing bytes are rejected by existing gates.
