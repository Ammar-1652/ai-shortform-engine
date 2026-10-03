# ADR 0032: Provisional captions before Hero alignment

- Status: Accepted
- Date: 2026-10-03

## Context

Round 3 word timestamps are provisional. Round 6 still has to show readable captions so a person can judge a candidate. Pretending those times are forced alignment would make the review file look more precise than the evidence is.

## Decision

Caption algorithm `provisional-caption-v1` copies transcript text. It does not call a model and it does not paraphrase.

When the candidate cites word timestamps, cues are greedy chunks of those words. A new cue starts before a word that would pass 8 words, 42 Unicode code points, or 3 seconds, and before a gap longer than 1.25 seconds. A word that already ends with observed punctuation closes the cue. Words outside the candidate are not included.

When a segment has no words, one cue uses that segment's text and the overlap of the segment interval with the candidate. One untimed segment is not split into several timed cues. Mixed transcripts keep both kinds and are sorted by source time.

Cue source and output intervals stay integer microseconds. Output frames are a derivative: the first frame whose start is at or after the cue, and an exclusive end frame. A cue that would have to appear before its canonical start is omitted rather than shown early. Overlapping cues fail planning. Touching half-open boundaries are valid.

Every stored cue has `timing_quality = provisional`. The rough style is system sans-serif, white text, a dark shadow and a translucent plate, centered above the bottom safe area. There is no karaoke highlight.

## Alternatives considered

- WhisperX or word-by-word highlighting in this round. Rejected. That is Hero alignment work.
- Invent even word times inside an untimed segment. Rejected. The file would claim timing the transcript does not have.

## Consequences

Round 8 can replace these cues. Round 6 files must not be treated as publish-ready captions.
