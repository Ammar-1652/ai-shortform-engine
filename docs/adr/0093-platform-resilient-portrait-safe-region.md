# ADR 0093: Platform-resilient portrait safe region

## Status

Accepted for new directed portrait drafts.

## Context

TikTok and Instagram both display 9:16 media beneath changing interface chrome.
The viewers can obscure or re-adapt the outer pixels, and the available safe
area varies with device, caption length, and interactive controls. A source
native logo at the exact left edge therefore remains vulnerable even when the
encoded MP4 is a valid 1080x1920 file.

## Decision

Add the typed `platform-resilient-portrait-v1` safe region. A direction chooses
it only when reviewed edge content is important. The deterministic Remotion
composition keeps the foreground source aspect-correct at a restrained 0.90
scale over the recorded backdrop (legacy plans use the blurred source; new
Tarteel plans may use ADR 0094's source-palette gradient), and expands the
caption and context geometry to a conservative inner band. Its reusable context settings
are a 64px title, a two-line maximum, and a `y=280` anchor below the top feed
header. `portrait-safe-v1` remains the default for directions whose edge
content is nonessential.

The selected region is part of the direction and Advanced plan hashes, so a
changed region cannot reuse an old render, QA result, final review, or delivery
package. Platform-preview QA must test the decoded frames against both TikTok
and Instagram masks. Those masks are evidence for the target device, not a
universal guarantee; a private platform preview remains the final visual check.

The rule applies to both Hero and Advanced Hero paths that consume the typed
portrait transform. It does not add platform UI artwork to the production MP4.

## Consequences

- One cross-platform 1080x1920 file is produced instead of separate crops.
- Important logos, captions, CTAs, and titles are protected by an inner band.
- Nonessential edge content can retain the normal full-width treatment.
- Legacy lateral blur is an intentional design region, not accidental
  letterboxing; ADR 0094's framed Tarteel renders use a palette backdrop.
- Existing `portrait-safe-v1` artifacts remain immutable and verifiable.
