# ADR 0038: Selected-clip forced alignment

- Status: Accepted
- Date: 2026-10-03

## Context

Round 3 transcribes the whole ASR FLAC with faster-whisper and stores provisional word times. A Hero caption that reused those times would look more precise than the evidence. Running WhisperX across the full source would also do work the reviewer has not approved.

## Decision

Hero alignment runs only on a candidate whose effective review for the current rough-preview artifact is `approved`. The text authority is the transcript words named by that candidate. The adapter trims the existing ASR FLAC to the candidate TimeMap and calls WhisperX on that span. It does not transcribe the rest of the source and it does not rewrite, normalize, or invent words.

Every stored word is `alignment_quality = forced`, with source and output microseconds, half-open Hero frames, the WhisperX version, and the alignment configuration hash. A count or text mismatch fails the job. Provisional times are not substituted. A normal run sets `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, and `HF_DATASETS_OFFLINE` to 1, requires cached English NLTK punkt data, and blocks `torch.hub` downloads. `model_cache_only` is passed only when the installed loader declares that parameter. English alignment uses torchaudio `WAV2VEC2_ASR_BASE_960H`. WhisperX is not a default project dependency. Model download requires `--allow-model-download`.

Tests inject `FakeForcedAlignment`. Production commands use the WhisperX adapter. When the package is not importable, the adapter uses the optional side interpreter from [ADR 0054](0054-candidate-local-render-staging.md). A missing interpreter still fails closed.

## Alternatives considered

- Reuse provisional transcript times for the first Hero render. Rejected. The draft would hide an alignment failure.
- Align the full source once and slice it later. Rejected. Round 8 only has a reason to align clips a person approved.

## Consequences

Hero captions and motion use the forced words. Rough previews stay provisional. If WhisperX or its model is missing, `hero align` and `hero render` fail and leave the previous Hero artifact in place.
