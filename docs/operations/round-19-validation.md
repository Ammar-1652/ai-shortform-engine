# Round 19 validation

Round 19 starts from `9209df919d5f6a7503a5e1ae77da9773fc038209` on branch `round-19-real-source-voice-multilingual`. Status: PARTIAL. Both authorized sources were hashed, prepared, transcribed, analyzed, and mined. Rough preview did not promote an MP4, so review, Hero, QA, and local delivery did not run. External platform publishing stays deferred. This file records commands and measured identities. It does not store credentials, cookies, bearer tokens, or filesystem paths.

## Sources

Only the two selected Antoine Sallis campaign files are in scope. Both were re-hashed and re-probed by `clipforge source ingest` before later stages. Unselected campaign files were not fetched.

| Campaign id | Bytes | SHA-256 | Duration |
| --- | ---: | --- | ---: |
| src-before-famous | 180882018 | `abe817eb72bdd67980de1b6a945858043ffead6567585d45b3ccdf1edfd08a89` | 587687100 µs |
| src-american-secret | 163530208 | `495ae005f3ec2e7365a6baf57abc1e0c57529860dfa090cc3cb449da160b9ba8` | 835668167 µs |

Expected picture is H.264, 1920×1080. src-before-famous is 30000/1001. src-american-secret is 24000/1001. Both carry AAC at 44100 Hz stereo. Ingest reported one video stream, one audio stream, referenced storage, and transcription eligibility. The execution record below is updated after each stage finishes. A missing stage is not described as passed.

## Commands

```text
uv run clipforge source ingest PROJECT SOURCE --rights-status campaign_provided --confirm-rights
uv run clipforge media prepare SOURCE_ID
uv run clipforge transcript run SOURCE_ID --model small.en --language en --device cpu --allow-model-download
uv run clipforge vision analyze SOURCE_ID --allow-model-download
uv run clipforge candidate mine SOURCE_ID
uv run clipforge preview render SOURCE_ID
uv run clipforge review decide --reviewer-id round19-validation
uv run clipforge hero align SOURCE_ID CANDIDATE_ID
uv run clipforge benchmark run SOURCE_ID --fixture real_source
uv run clipforge benchmark readiness BENCHMARK_ID
uv run clipforge language check
uv run clipforge voice doctor --provider voicestudio
uv run clipforge assets envato search --provider envato --query "office desk" --asset-type video --category "Stock Footage" --orientation vertical --resolution 1080p --min-duration 3 --max-duration 30
```

Later transcript runs set `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, and `HF_DATASETS_OFFLINE`. Review notes say the decision is a controlled real-source validation decision. Review rows are appended through the review command. Database rows are not edited to approve a candidate or a Hero.

## ASR

The project model is `small.en`. The first transcript run of this round used `--allow-model-download` and cached hub snapshot `d1d751a5f8271d482d14ca55d9e2deeebbae577f`. The checkpoint file `model.bin` in that snapshot has SHA-256 `62b2a45b05ee59acb4a5341b33ee35e041395d378d418a18acfe4c9e768ee37a`. Installed packages are faster-whisper 1.2.1, CTranslate2 4.8.2, and huggingface-hub 1.33.0. Model files stay in the local model directory and are not committed. Later transcript runs in this round set the offline hub variables and do not download again.

The first src-before-famous pass reached 100% and then failed closed: segment 2 word 9 had the same start and end, 29540000 µs. Clipforge now records that empty engine span and extends the end by 1 µs when that still fits inside the source. The word text is not rewritten. A span that runs backwards still fails. The transcript job is repeated offline after that change.

## Alignment and captions

WhisperX, torch, torchaudio, and NLTK are not installed in the Clipforge environment. `clipforge hero doctor` warns that align fails closed and does not use provisional timings. A wav2vec2 English checkpoint is already in the local torch hub cache, and that does not make the aligner installed. English alignment stays `alignment_not_claimed` until `hero align` succeeds. Arabic and Japanese caption proofs keep the source characters, draw inside the 64-pixel safe margin of a 1080×1920 frame, and set `alignment_status` to `alignment_not_claimed`. `clipforge language check` printed `multilingual_pass` and `alignment_claim: alignment_not_claimed` for `en-US`, `ar` (RTL), and `ja`. Unsupported tags such as `zh-CN` fail before a render job.

## VoiceStudio

Narration is disabled unless `CLIPFORGE_VOICESTUDIO_ENABLED=1`. `CLIPFORGE_VOICESTUDIO_URL` selects the local service and defaults to loopback port 3900. Doctor then checks `GET /health` and `GET /.well-known/voicestudio-speech`. Generation uses the documented `POST /v1/audio/speech` body: model, voice, input, ISO 639-1 language, and WAV. The narration record stores the audio hash, size, duration, language, voice and model ids, provider version, and license identity. Cache identity includes the script hash, so a changed script misses. Fake-provider tests cover that path when the service is absent.

On this machine the documented `bun run dev` command cannot start: `bun` is not installed, and nothing accepts connections on the loopback speech port. `clipforge voice doctor` reports `health: not_called` and `capabilities: not_called`. Live smoke is `voice_provider_unavailable`. It is not `voice_live_pass`. Fake-provider tests cover cache hits, script changes, and provider-version changes.

## Envato

Search goes through `https://mcp.envato.com/mcp`. The adapter reads the live tool schema, selects `search_stock_video` for video, maps category and `1080p` onto the advertised fields, and rejects an ambiguous `duration` plus any unsupported filter before `tools/call`. Item ids, direct download URLs, formats, and licenses stay empty when the server does not return them. A manual request file is written in that case. Antoine campaign policy still blocks those rows from a render.

The live search used query `office desk`, asset type video, category `Stock Footage`, orientation vertical, resolution `1080p`, minimum duration 3 seconds, and maximum duration 30 seconds. The call returned five item pages. Direct download URLs, item ids, durations, formats, and licenses were null. Each row is `outside_media_prohibited_by_campaign_policy`, so none is an Antoine render input. The request command wrote `asset_download_requests.json` and `asset_download_requests.md` and reported `manual_download_required`. Per-row `download_status` stays `rejected` because campaign policy blocks the asset. That is stronger than a pending manual download, and it still does not invent a file URL.

| Item page |
| --- |
| https://elements.envato.com/vertical-top-view-of-desk-with-laptop-presentation-RCH48QK |
| https://elements.envato.com/work-table-with-stationery-and-cups-of-coffee-RAYHB68 |
| https://elements.envato.com/vertical-of-interior-of-modern-office-with-documen-5L7XVSL |
| https://elements.envato.com/vertical-video-shifting-camera-showing-black-mesh--5U36PES |
| https://elements.envato.com/vertical-video-panning-camera-revealing-plant-in-t-ZBS2C33 |

## Readiness labels

`clipforge benchmark readiness` distinguishes `synthetic_only`, `real_source`, `technical_pass`, `local_delivery_pass`, `voice_disabled`, `voice_live_pass`, `voice_provider_unavailable`, `multilingual_pass`, `alignment_not_claimed`, and `external_publishing_deferred`. Synthetic evidence does not set `real_source_verified` to passed.

## Execution record

Stages below are filled from the local run. Until a row says passed, that stage is not claimed.

| Stage | src-before-famous | src-american-secret |
| --- | --- | --- |
| Ingest hash and duration | passed, values in the source table | passed, values in the source table |
| Media prepare | passed | passed |
| Transcript | passed offline after the timing repair | passed offline, same model revision |
| Visual analysis | passed, 87 scenes, 96 face tracks | passed, 17 scenes, 293 face tracks |
| Candidate mining | passed, 22 selected | passed, 25 selected |
| Preview | failed, no MP4 promoted | not started |
| Review, align, Hero, QA, local delivery | blocked on preview | blocked on preview |

src-before-famous transcript job `a817d655-293e-4ebd-9a48-42c2a39deedc`, transcript `17ac3726-3c95-4114-913b-79547f1b013e`, SHA-256 `026356d160d6ed1025f2172636cd0f85c8ce9aaff0afa54c4fab9324e221d505`. Model `small.en` revision `d1d751a5f8271d482d14ca55d9e2deeebbae577f`, device cpu, compute `int8`, detected language `en` at probability 1.0. 156 segments and 1635 words. Cache miss. Inference 109.803 seconds, real-time factor 0.187. The artifact is bound to that source, model revision, and producer job. The run used the offline hub variables and did not download the model again. The candidate set stores the same transcript SHA-256, transcript job, and source SHA-256. Its transcript timing quality is `provisional` and its alignment label is `approximate`, which is not a WhisperX claim.

Visual analysis job `8e9048e9-9924-4950-853c-055b51fd3390`, analysis `f37721ca-9777-4e91-8378-b18e873726c2`, SHA-256 `a5407061f5ba6838ab16a5ae50a42bad95a3c5c5ab072fdfe840aeb693585824`. Mining job `c27931cd-ed38-42cf-94b0-39950aa4501a`, mining id `2f060ce6-a793-4be1-981a-6b8524a126b2`, artifact SHA-256 `85f3c70ccadc886332fe76bfa1da877b136308d467d9e91e99e12083269205c7`. 1637 raw hypotheses, 22 selected. The validation path will review candidate `f112bd8e-40bd-51fb-b662-518907f5d22c` through the review command.

src-american-secret media prepare job `5d8e6c0c-0778-4fe5-96d8-679b58e717a0`. Proxy SHA-256 `8dce9ac840cc1f4e04813d9d2fe73f45b48bd5f85755d5d3291ebcdcf0d3ae95`. ASR audio SHA-256 `334ebb4d2732577095d245907997541d496b570aa206f2a33c5323f1841c2f70`. Transcript job `2e1b4895-61a0-4cbc-a34c-d3d546e1db1f`, transcript `bb9ce7b5-d546-438a-b2c9-fd5e80eba534`, SHA-256 `c200b46e5a36256c941759c3c803627d87a7aec536b95ff2a4536c9f0dc9e70d`. Same `small.en` revision, cpu, `int8`, detected `en` at probability 1.0. 135 segments and 2097 words. Cache miss. Inference 142.404 seconds, real-time factor 0.170. Offline hub variables were set. No second model download. Visual analysis job `a0055cdd-f250-43f7-8e1c-ab1714ae73e1`, analysis `dfe9685f-475e-4431-a361-8ffb257ab86e`, SHA-256 `9493b6f559d774ea7a93444ac0f959363db87efec305581d887d4d3adb100861`. Mining job `6afe5235-d9b8-43ce-a4b8-4d0461c0e96c`, mining id `5605aec5-6153-40fc-9ea9-f0e4ef98929a`, artifact SHA-256 `81cb8f0583ea9799d27815a40d69de6e30b59d228ce37ba6486e56e0c273e4d1`. 716 raw hypotheses, 25 selected. Candidate `d6188336-411b-5596-be22-2be25aed290a` was the intended review target. Timing quality is `provisional` and alignment is `approximate`.

Rough preview of src-before-famous was attempted twice and did not promote an MP4. The first attempt stopped in Remotion with `No frame found at position 9131000` while free memory was under 1 GiB. The proxy itself has a decodable frame at 9.131 seconds, so the miss matches Remotion's OffthreadVideo cache eviction note. The second attempt stopped with `Session closed` and `waiting for the page to render the React component failed: timeout 33000ms exceeded`. Partial preview files were not promoted. Review, forced alignment, Hero render, QA, and local delivery were not started. `clipforge hero align` was not run. WhisperX remains uninstalled, so an align attempt would fail closed rather than invent timings.
