# Round 3 validation

Local validation of the faster-whisper transcription round. CI run ids are the checks on the draft pull request for `round-03-transcription`. This file does not copy those ids back after the branch is green.

## Baseline

| Item | Value |
| --- | --- |
| Required main SHA | `d9f227c90e933f319376a183dd407267d606602b` |
| Verified starting SHA | `d9f227c90e933f319376a183dd407267d606602b` |
| Branch | `round-03-transcription` |
| Schema version | 4 |
| Database migration | none. Migrations 1–4 are unchanged. |

## Dependencies

| Package | Version |
| --- | --- |
| faster-whisper | 1.2.1 |
| CTranslate2 | 4.8.2 |
| PyAV (`av`) | 18.1.0 |
| huggingface-hub | 1.33.0 |
| tokenizers | 0.23.2 |
| Python | 3.11.15 |

`uv.lock` pins them. CI imports `faster_whisper` and `ctranslate2` and sets `HF_HUB_OFFLINE=1`. It does not download weights.

## Model

| Item | Value |
| --- | --- |
| Model root | `CLIPFORGE_MODEL_ROOT`, default `var/models` (gitignored) |
| Default profile model | `small.en` (not downloaded in this validation) |
| Smoke model | `tiny.en` |
| Revision | `0d3d19a32d3338f10357c0889762bd8d64bbdeba` |
| Source | hub snapshot |
| Cache size | 75 MiB |
| Download | only with `--allow-model-download` when the snapshot is absent |
| Offline | a second smoke used the cached snapshot and did not print a hub download warning |

## Runtime

CPU compute types reported by CTranslate2: `int8`, `int8_float32`, `int16`, `float32`. Auto CPU selection is `int8`.

`nvidia-smi` sees an RTX 3060 Laptop, 6144 MiB, driver 610.57.04. `nvcc` is CUDA 13.3. CTranslate2 reports one CUDA device and would list CUDA compute types, including `int8_float16`. Those libraries do not load:

- `libcublas.so.12` is missing. The machine has `libcublas.so.13`.
- `libcudnn.so.9` is missing.

No CUDA wheel, driver change, or cuBLAS package was installed. Explicit `--device cuda` fails and does not fall back to CPU. `--device auto` selects CPU and records that warning. `transcript doctor` is WARN on CUDA and PASS on CPU. The general `clipforge doctor` stays green.

## Profile

`small.en`, language `en`, task `transcribe`, beam 5, word timestamps on, VAD off, `condition_on_previous_text` on, temperature `0.0` as a single value so the library's temperature fallback list is not used.

## Canonical time

ASR FLAC time 0 is canonical source time 0. Seconds become microseconds with `Decimal(str(seconds))` and half-up. The Round 2 audio offset is not added again. A prepared file whose audio offset was about 479 ms still maps a model time of 0.5 s to 500,000 µs. Ends up to 100 ms past the canonical duration are clamped and listed on the document. Larger misses fail the job.

## Results

| Check | Result |
| --- | --- |
| Segment and word validation | pass, including overshoot, negative time, order, and probability |
| Empty speech | pass. Zero segments, `speech_detected` false |
| Unicode and leading spaces | pass. Word text is not stripped |
| Cache hit | pass. Second run does not call the backend |
| Force | pass. New job, old job kept, artifact points at the new job |
| Rights unknown and prohibited | pass. No backend call |
| Source mutation | pass. Fails before inference |
| Corrupt ASR bytes | pass. Asks for `media prepare`. No backend call |
| Failed media_prepare job | pass. Transcription blocked |
| Active prepare lock | pass. No new job, partial kept |
| Second transcription lock | pass. No backend call |
| Stale running job | pass. Marked failed after the lock, new job continues |
| Generator failure | pass. Previous transcript bytes kept, partial removed |
| Database failure after publish | pass. Previous bytes restored |
| Missing model | pass. No download helper call |
| Explicit CUDA and auto CPU | pass |
| pytest | 132 passed |
| Non-media, non-transcription | 95 |
| Media, including one delayed-audio transcript | 18 |
| Transcription, fake backend, no weights | 19 |
| Ruff | pass |
| Format | pass |
| mypy | pass |
| Schema check | pass. 48 schema files |
| Renderer | run by `scripts/validate.sh` |
| `clipforge doctor` | pass. Schema version 4 |
| `transcript doctor` | WARN. CPU pass, CUDA libraries missing, `small.en` not cached |

## Known limitations

Transcription does not translate, diarize, or correct text with an LLM. Word times are provisional. VAD is off. `small.en` is the default and was not benchmarked here. GPU inference does not run until `libcublas.so.12` and `libcudnn.so.9` load. Stream-variant sources in one project remain a Round 2 conflict. No migration 5.

## Round 4

Scene, visual, and face analysis. Not started. WhisperX is not started.
