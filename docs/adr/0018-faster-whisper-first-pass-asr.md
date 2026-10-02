# ADR 0018: faster-whisper first-pass ASR

- Status: Accepted
- Date: 2026-10-02

## Context

Round 2 writes `audio/asr.flac` on the canonical video clock. The next editorial steps need the words in that file, with timestamps a later round can search. They do not need word-perfect Hero captions yet.

WhisperX can force-align a selected range. Running it on every full source would add a second model, a second clock, and a reason to re-time audio that Round 2 already aligned. Cloud ASR APIs would upload the source audio.

## Decision

Full-source transcription uses faster-whisper 1.2.1 and CTranslate2. The only audio input is the Round 2 ASR FLAC for a source id. An arbitrary wav path is not a command.

faster-whisper time 0 is canonical source time 0. Clipforge converts seconds with `Decimal(str(seconds))` and half-up rounding to integer microseconds. It does not add `audio_offset_us` or `video_origin_us` again.

The default profile is `small.en`, language `en`, task `transcribe`, beam 5, word timestamps on, VAD off, `condition_on_previous_text` on, and a single temperature of 0.0. VAD stays off so silence is not removed from the clock. Translation is rejected. Word timestamps are stored as provisional (`alignment = approximate`). They are evidence for search and rough cuts, not Hero caption alignment.

CPU is a complete path. `cuda` fails when CTranslate2 cannot use CUDA. `auto` uses CUDA only when CTranslate2 reports a device and a supported compute type, and otherwise uses CPU and records why. The artifact stores the device and compute type that ran, not only the request.

A model download requires `--allow-model-download` when the model is not already in `CLIPFORGE_MODEL_ROOT` (default `var/models`). Doctor and verify do not download. Inference stays local. The optional network step is that explicit download.

The production path calls `WhisperModel.transcribe` once per run and consumes the segment generator before the source locks are released. `BatchedInferencePipeline` is not the default.

## Alternatives considered

- WhisperX for the full source. Rejected for this round. It remains the later Hero alignment pass on a selected range.
- OpenAI, Deepgram, or another remote API. Rejected. The audio would leave the machine.
- Leave VAD on. Rejected. It would hide silence and make the canonical clock harder to audit.
- Silent CPU fallback when `--device cuda` fails. Rejected. The operator asked for CUDA.

## Consequences

Hero captions still need a later WhisperX pass. A `.en` model cannot be asked to detect a non-English language. Changing beam size, temperature, VAD, or the engine version changes the transcript cache identity. GPU use depends on the CTranslate2 CUDA libraries that are actually loadable, not on `nvidia-smi` or the CUDA toolkit version.
