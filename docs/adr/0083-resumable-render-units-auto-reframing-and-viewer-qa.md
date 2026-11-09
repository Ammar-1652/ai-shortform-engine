# ADR 0083: Resumable render units, automatic portrait framing, and viewer QA

## Status

Accepted for the current Advanced Hero production path.

## Context

Long Remotion renders can fail after the browser has already produced valid
video or audio work. Re-running the whole composition wastes the completed
work and makes a crash look like an editorial failure. Portrait framing also
needs to use the visual-analysis evidence rather than silently inheriting a
review contain profile. Finally, a valid MP4/container probe is necessary but
does not prove that a viewer can read the captions, understand the hook/body/
punch structure, or see a purposeful graphic.

## Decision

Advanced browser renders use the pinned
`remotion-chunks-continuous-audio-v1` recipe. Video is rendered in global,
half-open frame chunks of 120 frames. Each chunk is ffprobe-validated and
recorded in an atomic candidate checkpoint with its input and renderer
dependency hashes, byte size, and SHA-256. Audio is rendered once for the
complete composition as stereo PCM16 WAV, then muxed once with the validated
video chunks and encoded to the final AAC track. A final MP4 is published only
after every receipt, mux, duration check, and loudness normalization succeeds.

The Advanced run writes `progress.json` after initialization and after every
candidate. It records the source, Hero review status, candidate set, batch
input, renderer dependency, and final media hashes. A failed run is marked
`failed` without promoting a manifest; `clipforge hero advanced render
--resume RUN_ID` validates those bindings and reuses only receipts whose file,
range, size, and hash still match. Stale or unknown units fail closed.

`--reframing auto` consults reviewed native-text annotations first. If those
annotations do not require a full-source contain view, it builds the
frame-level face-follow trajectory from the current visual analysis and
TimeMap. An invalid, incomplete, or stale track selects contain explicitly;
there is no silent crop fallback. The applied strategy and trajectory digest
remain in the plan, render input, manifest, QA, review, and delivery bindings.

Technical QA now includes a viewer-quality contract check. It rejects missing
clean caption coverage, duplicate forced-word ids, repeated source ranges,
unsupported quantitative graphics, and a center crop that would hide reviewed
source-native text. This contract is evidence from the typed direction,
alignment, geometry, and plan; it is not a substitute for decoded-frame
inspection or the human final-review decision.

## Consequences

- A crash can resume from the last verified unit without reinterpreting an old
  plan or approval.
- Chunked video never concatenates independent AAC segments, preventing chunk
  priming gaps from creating AV drift.
- Automatic framing is conservative around source-native text and fails closed
  when visual evidence cannot support a moving crop.
- Viewer-facing defects become a named QA failure instead of being hidden by a
  successful ffprobe or loudness check.
- Remotion browser renders take more bounded worker launches and disk space;
  the work root is the retention boundary and stale partials are never
  promoted. Human review remains mandatory.
