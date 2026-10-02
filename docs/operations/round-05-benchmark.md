# Round 5 benchmark

This is a synthetic timing note. The sentences are original test text. The numbers are not real-world editorial performance.

Machine: local development workstation. Command: in-process `mine_documents` on constructed transcript and visual documents. No video decode, no model, no database.

## Input

- Represented source duration: 480,000,000 µs (8 minutes)
- Transcript segments: 19
- Words: 209
- Visual scenes: 12
- Each spoken span is 20 seconds, followed by 5 seconds without a segment
- Scene length: 40 seconds, tiling the source

## Result

| Stage | Time |
| --- | --- |
| Build the in-memory documents | 0.001 s |
| Window generation | 0.002 s |
| Feature extraction | 0.006 s |
| Scoring | 0.002 s |
| Dedupe | 0.001 s |
| Full `mine_documents` including assembly | 0.016 s |
| JSON serialization | 0.003 s |

- Raw hypotheses: 37
- Hard filtered: 0
- Duplicates removed: 18
- Eligible distinct: 19
- Selected: 19
- Raw cap reached: no
- Candidate JSON size: 123,494 bytes

A second identical service call is a cache hit and does not call window generation, scoring, or dedupe. That behavior is covered by `tests/test_candidate_service.py`. This note does not time a disk cache hit separately from the JSON write above.

The selected intervals are about 20.25–20.50 seconds. Mean quality on this fixture was about 0.846 and mean edit opportunity about 0.278. Those figures only describe this generator output.
