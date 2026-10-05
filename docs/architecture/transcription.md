# Transcription

Round 3 turns the Round 2 ASR FLAC into a typed transcript. It does not align Hero captions, detect scenes, or score candidates.

## Eligibility

`transcript run` takes a source id. It loads the source, the manifest, and the license. Rights must still pass `require_rights_cleared`. The referenced file must still match the stored SHA-256. `transcription_eligible` must be true. A source with no selected audio fails and does not get an empty fake transcript.

The command then requires `audio/asr.flac`, the `asr-audio` v1 sidecar, a matching hash, and a `media_prepare` job in `succeeded` for that project and source. It does not call `media prepare`.

## Model

Weights live under `CLIPFORGE_MODEL_ROOT`, default `var/models`, which is gitignored. A cached model is used as-is. A missing model downloads only with `--allow-model-download`, and only when free space stays above the disk reserve. The download size is used when the hub reports it. Otherwise the reserve itself must remain free, because the size is not known yet.

A hub snapshot is identified by the revision directory name. A local model directory is fingerprinted from file names, sizes, mtimes, and hashes of the small metadata files. `model.bin` is not re-hashed on every run. A same-size, same-mtime swap of that file would not change a local fingerprint. A new hub snapshot is a new revision and misses the cache.

`FasterWhisperBackend` loads one `WhisperModel` per run and uses the sequential `transcribe` path. Tests inject `FakeTranscriptionBackend`. `clipforge --help` does not load weights.

## Device

`cpu` never requires a GPU. `cuda` fails closed when CTranslate2 cannot use CUDA. `auto` selects CUDA only when CTranslate2 reports a device and a supported compute type. The stored device is the one that ran.

Auto compute type prefers `int8` on CPU and `int8_float16` on CUDA when that type is supported. An explicit type that CTranslate2 does not list is an error. An out-of-memory failure on explicit CUDA stays a failure. Auto does not retry a second device after inference has started.

## Clock

ASR sample 0 is canonical video time 0. faster-whisper seconds convert with `Decimal(str(seconds))` and half-up to microseconds. An end up to 100 ms past the canonical duration is clamped and recorded in `timing_adjustments`. A larger miss fails the job. The Round 2 audio offset is not applied again.

Word timestamps are provisional. WhisperX, later, aligns a selected Hero range. It is not installed here. An engine span whose start and end become the same microsecond is extended by 1 µs when that still fits in the source, and the adjustment is stored. A word time that falls outside its own segment, but still inside the source, is clamped into that segment and the original microsecond is stored in `timing_adjustments`. A word that would otherwise collapse at the segment boundary keeps one microsecond inside that segment. Word order inside the segment is restored by a recorded clamp. The words are not reordered in the text. The word text is not changed. A backwards span, or a timestamp more than 100 ms outside the source, still fails closed.

## Document

`transcript/transcript.json` is a `Transcript`. Segments and words keep engine text, including leading spaces and Unicode. Diagnostics (`avg_logprob`, `no_speech_prob`, `compression_ratio`, temperature) are stored when the engine sends them. They are not a quality score. Zero segments is a successful transcript with `speech_detected` false.

The sidecar is `metadata/transcript.recipe.json`. The artifact kind is `transcript_json`. A cache hit reuses the existing succeeded job. `--force` runs again and leaves the old job in history.

## Locks

See ADR 0020. Shared `prepare.lock`, then exclusive `transcribe.lock`. The generator is consumed before either lock is released. A busy lock fails before any job write. A stale `running` transcription job is failed only after the exclusive lock is held.

## Verify and show

`transcript show` and `transcript verify` do not load a model or download. Verify checks the source, rights, ASR identity, transcript hash, contract, and the succeeded producer job. A missing model cache is a warning.

## Failure

A missing model, a rights block, a mutated source, a corrupt FLAC, a failed prepare job, a CUDA miss, an inference exception, or a bad timestamp marks the job failed or never inserts it. A partial transcript is not published. A previous valid transcript is restored if a later database write fails. SIGINT marks the job cancelled.

## Later WhisperX handoff

The full-source transcript stays the search index. A selected candidate range will be cut from the same canonical audio and aligned with WhisperX for Hero captions. That pass is not this round.
