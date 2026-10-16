# ADR 0079: Claim-specific native graphics

## Status

Accepted

## Context

The native `business_spotlight` Remotion template draws a rising business
trend. The previous direction validator allowed the template for the word
“company” alone. That made a technically source-bound chart visually imply a
financial trend that the transcript never stated.

## Decision

Template eligibility is tied to the visual meaning of the template. A
`business_spotlight` graphic requires source evidence containing `business`,
`founder`, or `enterprise`; a generic `company` mention is insufficient. When
no allowlisted template faithfully depicts the claim, the direction omits the
graphic. The copied evidence text, purpose, interval, and geometry remain
required and continue to flow into plan, render, QA, review, and cache identity.

## Consequences

The current exotic-car/company sentence no longer receives a rising chart by
keyword coincidence. A reviewed car/company illustration or restraint is
required. Existing artifacts remain immutable; a new direction and approval
are required before a changed graphic plan can render.
