# ADR 0007: Hard compliance gates

- Status: Accepted
- Date: 2026-10-02

## Context

A strong hook does not make a forbidden claim, a missing license, or an unknown source legal. A weighted formula such as "creative 90 plus compliance 30" hides a block inside a flattering total.

## Decision

Compliance and rights are gates.

- `ComplianceRule.severity` is only `block`.
- `ComplianceResult.status` is `pass`, `fail`, or `insufficient_evidence`. There is no numeric compliance score field. Extra fields are rejected (`extra = forbid`).
- `require_compliance_cleared` returns only when every result is `pass` and the list is non-empty.
- `CandidateStatus.READY_FOR_REVIEW` requires that gate plus both transcript and visual evidence. `creative_score` is ignored by the gate.
- `require_rights_cleared` blocks `unknown`, `prohibited`, and any record without an evidence URI.
- `QAResult` status is the worst check. A caller cannot store `pass` over a failed check.

An LLM saying the clip is fine is not a pass. That text can be stored as evidence on an `insufficient_evidence` result.

## Alternatives considered

- A weighted rubric that includes a compliance percentage. Rejected. It lets a hook outvote a ban.
- "No evidence means pass, we will check later." Rejected. Missing evidence stays closed.

## Consequences

- Creative ranking can still order clips that already cleared the gate.
- Profiles change which rules apply. They do not change the gate into a score.
- Tests in `tests/test_schemas.py` lock the rejection of a smuggled `compliance_score`.
