# ADR 0068: Synchronized review and relevant asset gate

- Status: Accepted
- Date: 2026-10-07

## Context

The review recut was assembled from a picture file and a separate speech file.
Their encoded boundaries matched, but the review captions were derived from an
approximate full-source transcript rather than selected-clip forced alignment.
That combination can make a viewer perceive the edit as out of sync even when
the container has equal durations. The same workflow also requested unrelated
camera and film assets before the operator had a source-grounded asset brief.

## Decision

These are hard production gates for an enhanced short:

1. Picture and speech staging must use the same ordered `TimeMap`, start at
   output zero, and each stream must be within the project duration tolerance.
   Preview and Hero probes reject missing, delayed, or duration-drifting audio.
   A pair is not considered synchronized merely because its container
   durations match: the staging recipe records the identical ordered source
   ranges for both streams, and synchronization QA checks bounded windows
   across the whole output (including the final window) rather than only the
   aggregate duration. A non-zero window lag or a progressive lag trend is a
   failure requiring restaging from the canonical map.
2. Burned captions and active-word emphasis require selected-clip forced
   alignment. Approximate ASR timing may guide candidate mining, but it cannot
   be promoted into final caption evidence.
3. Graphics are Remotion components driven by typed, source-grounded events.
   Post-render overlays and arbitrary HTML/JS are not an editing path.
4. Envato search is performed through the official Envato MCP adapter. The
   operator receives one source-relevant request file containing item links,
   intended role, expected media kind/extension, and licensing status. The
   workflow stops after that file is written until the operator confirms that
   the selected files and license certificates are downloaded.
5. A downloaded asset cannot enter a render until it is hashed, registered,
   license-bound, policy-cleared, and present under the work root. Music and
   unrelated stock remain prohibited when campaign policy says so.

## Consequences

The renderer fails early instead of producing a plausible but unsynchronized
draft. Production Hero staging always writes the same-map recipe for picture
and speech, including a one-range edit; an operator must not copy an
independently encoded picture file beside an independently encoded speech
file. A source-grounded motion brief and manual Envato handoff precede asset
selection. Existing campaign rights, append-only review, and stale-artifact
checks remain authoritative. A live MCP outage is reported as unavailable; it
does not justify invented links or automatic downloads.
