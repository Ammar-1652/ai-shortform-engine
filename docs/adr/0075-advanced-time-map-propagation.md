# ADR 0075: Advanced Hero TimeMap propagation

## Status

Accepted for the editorial cut repair.

## Context

Advanced Hero plans recorded a `time_map_sha256`, but not the map itself. The
browser render staging step therefore reopened the original Hero plan and used
that map. A future reviewed jump-cut plan could carry a different digest while
the actual staged picture and speech still came from one continuous Hero range.

## Decision

New `AdvancedHeroPlanDocument` records persist the exact `TimeMapDocument` used
to derive captions, graphics, reframing windows, and staged picture/audio.
Advanced rendering stages that persisted map. Old immutable plans with no map
remain readable and use their original Hero map. The stored digest must match
the persisted map. A mismatch fails before rendering.

The map remains the only output clock. It is ordered, integer-microsecond, and
validated by the existing TimeMap contract. This change does not authorize an
unreviewed map or change candidate selection; the next editorial-arc step must
create and bind a reviewed map before production use.

## Consequences

The renderer can no longer silently discard an approved multi-segment map at
the staging boundary. The map is included in the Advanced plan fingerprint and
therefore changes cache identity and stale evidence. Existing plans remain
verifiable without migration because the field is optional for old records.
