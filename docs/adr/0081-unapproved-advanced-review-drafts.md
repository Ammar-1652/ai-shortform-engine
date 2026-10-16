# ADR 0081: Unapproved Advanced Hero review drafts

## Status

Accepted

## Context

Advanced Hero normally requires a human approval of the current Hero artifact
before planning or rendering. That protects the production path, but it makes
it impossible to prepare a joint Hero/Advanced review bundle when the operator
wants to inspect both outputs together.

## Decision

Add an explicit `--draft-only` path to Advanced direction planning, Advanced
planning, and Advanced rendering. It may use the current unapproved Hero
artifact, but it writes `hero_review_status: pending` into the plan, render
input, manifest, and cache record. The pending binding is deterministic and
includes the Hero artifact and manifest identity; it is not a fabricated
approval.

The default commands remain approval-gated. Delivery preflight rejects a
pending Advanced set, and pending drafts cannot authorize QA/final review or
publishing. A reviewer may inspect the encoded Hero and Advanced drafts
together; normal Hero approval and final approval remain append-only human
decisions.

## Consequences

The operator can render a complete review bundle without bypassing production
rights, alignment, source, TimeMap, asset, or renderer checks. Pending status
is part of cache identity, so a later approved run is not mistaken for the
draft-only artifact. Existing documents default to `approved` for backward
compatibility with their recorded approval binding.
