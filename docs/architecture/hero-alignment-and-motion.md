# Hero alignment and motion

Round 8 builds a reviewable Hero draft for candidates a person approved on the current rough preview. The draft is a separate artifact. It does not replace the rough preview and it does not publish.

## Approval

`hero align`, `hero plan`, and `hero render` read the effective review for each candidate and the current `rough_preview_set_json` artifact. The effective review is the newest row for that candidate and artifact, ordered by `created_at` and then `review_id`.

- `approved`: eligible
- `changes_requested`: excluded and reported as needing correction
- `rejected`: excluded
- no decision, or a decision on an older preview artifact: excluded

If none are approved, the command returns a no-op. It does not write an empty Hero set or a succeeded job. Stale source, manifest, candidate, transcript, visual analysis, proxy, ASR, or candidate bytes fail before any Hero artifact is written.

## Alignment

The production adapter is WhisperX on the approved clip only. One TimeMap segment is trimmed from `audio/asr.flac` and aligned as a unit. A jump cut aligns each source interval on that interval, then maps the words through the candidate TimeMap. Text is copied. Unicode, numbers, and punctuation stay as stored. Word intervals must be positive, monotonic, non-overlapping, and inside the TimeMap. Output frames are the first Hero frame at or after each boundary. The stored locale stays as requested. Provider lookup uses the normalized language code. en-US, fr-FR, and ja are `verified_live` only when an external speech file matches the packaged record and the measured model. en-GB is not verified without its own speech record. A missing Spanish or German weight file is `model_missing` and does not fall back to English. Arabic stays `alignment_not_claimed`. A jump cut aligns each segment from the full ASR file on that segment's source interval. Character pieces are grouped back onto the transcript word. Full-source alignment is `not_configured`.

`hero doctor` reports WhisperX, torch, torchaudio, NLTK, cached English punkt data, the torchaudio `WAV2VEC2_ASR_BASE_960H` checkpoint or a Hugging Face cache hit, CPU or CUDA, and that a normal run sets `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, and `HF_DATASETS_OFFLINE` to 1. WhisperX 3.4.5 does not declare `model_cache_only`. The adapter blocks `torch.hub` downloads instead. `--allow-model-download` is the only download switch. WhisperX stays out of the default lock.

`FakeForcedAlignment` is for tests. It splits the candidate span into equal integer parts and does not read provisional timestamps.

## Plan and motion

The plan is an `EditPlan` with `stage = hero`, wrapped by `HeroPlanDocument`. B-roll and audio events are empty. Motion library `motion-library-v1` adds an opening fade, caption emphasis, and a closing fade. Caption algorithm `hero-caption-v1` chunks the forced words. Overlapping cues fail. Provisional timing cannot be stored as a Hero caption.

## Profile and render

Profile `hero-draft-v1` is 1080×1920, 30/1, H.264, AAC, `yuv420p` (or the encoder's `yuvj420p`), `contain` fit, and background `neutral-dark-v1`. The rough profile stays 720×1280. There is no face-aware reframing.

`hero render` processes approved candidates in rank order, one at a time. The Remotion composition is `HeroDraft`. Media must be the staged local proxy and ASR file. Remote `http` and `https` URLs are rejected. ffprobe checks dimensions, frame rate, codecs, pixel format, audio, and a 100 ms duration tolerance. A cache hit does not start WhisperX, Node, Chrome, or a render. `--force` writes a new Hero set and leaves the previous run on disk.

The artifact kind is `hero_draft_set_json`. A failed render, manifest write, database write, or sidecar write leaves the previous current Hero set in place. Partial files are not promoted. Cancellation marks the job cancelled.

## Review

The rough-preview page can still show a short Hero card. The Hero review surface is separate. See [hero-review-and-approval.md](hero-review-and-approval.md). `clipforge hero review open` binds to loopback, checks the current Hero set, and plays that set in manifest order. A decision is an append-only `ReviewDecision` with `subject_kind = hero`. It repeats the artifact, manifest, plan, and alignment the page loaded. A mismatch asks for a reload. Approval does not publish or render another file.

## Still deferred

Publishing, external media URLs, dynamic reframing, B-roll, music, sound effects, analytics, automatic approval, and full-source WhisperX.
