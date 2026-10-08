# Advanced Hero editing

Round 10 adds a separate advanced Hero artifact. It does not rewrite `hero_draft_set_json`.

## Profile

`advanced-hero-v1` is 1080×1920, 30/1, H.264, AAC, `yuv420p` (or the encoder's `yuvj420p`). Music is disallowed. B-roll and SFX must be rights-cleared local files. The maximum counts and gain limits live on the profile.

Reframing strategies include `contain` and the opt-in `face_follow`. `contain` is the default. `face_follow` builds a deterministic crop from stored face-track geometry. See [dynamic reframing](dynamic-reframing.md). A face box is geometry. It is not an identity and it is not the speaker. A strategy with too little evidence fails closed. The older `center_crop`, `manual_window`, `visual_safe_window`, `multi_face_safe_window`, and `saliency_window` names still fail closed when the render path does not support them.

## Plan and render

`clipforge hero advanced plan` reads the current approved Hero review, forced alignment, Hero plan, visual analysis, and local assets. A clean production plan also requires the persisted direction brief. `clipforge hero advanced render` writes `advanced_hero_draft_set_json` through `RemotionAdvancedRenderBackend`. The CLI does not accept a test encoder. Unit tests pass `FakeAdvancedRenderBackend` explicitly. Candidates stay in Hero manifest rank order. Overlapping B-roll and overlapping typography fail planning.

## Direction and style presets

For a new presentation pass, the operator first runs the project-local
`clipforge-motion-direction` skill. The resulting declarative brief must name
the current source, candidate, Hero-plan hash, TimeMap hash, exact transcript
evidence, and three alternatives. It is bound with:

```text
clipforge hero advanced direction plan SOURCE_ID CANDIDATE_ID --brief direction.json --style auto
clipforge hero advanced plan SOURCE_ID CANDIDATE_ID --reframing contain
clipforge hero advanced render SOURCE_ID
```

`--style auto` selects the highest scored option with a stable id tie-break.
An explicit preset override is limited to `editorial-clean-v1`,
`kinetic-caption-v1`, `documentary-broll-v1`, `data-explainer-v1`,
`paper-explainer-v1`, or `premium-minimal-v1`. Each preset carries numeric
easing/frame/travel/scale choices, local font identity and hashes, contrast,
accent, safe margins, and an emphasis limit. Remotion receives that typed
contract and the selected direction hash; it does not receive executable
creative code. A changed brief or preset makes the plan and all downstream
render/QA/review/delivery evidence stale. Old plans without direction remain
immutable compatibility artifacts.

Preset intent is deliberately narrow so presets cannot override one another:

| Preset | Use when | Motion/graphic priority |
| --- | --- | --- |
| `editorial-clean-v1` | General talking-head or interview excerpt | Readability and subject visibility; restrained active-word emphasis |
| `kinetic-caption-v1` | A fast, already coherent spoken passage | Short caption entrances and one highlighted word; no invented hook |
| `documentary-broll-v1` | Reviewed B-roll supports the spoken claim | Whole caption runs and relevant B-roll before ornament |
| `data-explainer-v1` | An explicit source-grounded numeric comparison exists | Exact labels and units; no chart when facts are missing |
| `paper-explainer-v1` | Calm explanatory or process segment | Slightly slower cards and whole-run captions |
| `premium-minimal-v1` | Clean source with strong native composition | Minimal accent and motion; omission beats clutter |

Precedence is fixed: campaign policy and rights, source evidence and TimeMap,
safe-region/collision checks, caption readability, selected preset, then
optional B-roll/SFX/diagram decoration. A lower-priority layer is omitted when
it collides with a higher-priority layer; it cannot move captions or the source
subject outside the safe region. Presets do not select a new excerpt, reorder
speech, add a CTA, or manufacture a hook/punch. Direction beats are editorial
labels; canonical forced-alignment cues remain the only caption timing source.
B-roll and SFX are never evenly spaced: a selected option must carry an
explicit `DirectionAssetPlacement` with source evidence, purpose, relevance
note, and an output-clock interval. Passing only asset ids creates an explicitly
marked legacy event that QA and Remotion reject for clean production. A
direction may omit both asset types when the source does not need them.

Before a render job is inserted, every stored plan is checked against the current source, candidate set, rough preview, Hero artifact, Hero approval, alignment, Hero plan, visual analysis, TimeMap, asset hashes, and rights. A stale or revoked binding fails closed and does not publish a sidecar.

Asset paths are checked lexically before `Path.resolve()`. A symlink at the file or at a parent directory is rejected, including a symlink whose target has the expected hash. Absolute paths, `..`, backslashes, and file URIs outside the work root are rejected. The same check covers cache validation, staging, rendering, and media serving.

The production composition uses `contain` over a deliberate blurred full-frame background (not accidental black bars) and the neutral-dark fallback `#111111` unless the stored plan is `face_follow` or `center_crop`. `face_follow` places the stored crop and does not use `objectFit: cover`; `center_crop` uses its explicit portrait crop. Other unsupported strategies fail before the job. B-roll keeps its reviewed output interval and `broll_source_in_us`. SFX gain converts with `10 ** (gain_db / 20)` inside `-24..6` dB, trims from its declared asset in-point, and plays on the declared interval. Music is rejected. After rendering, ffmpeg `ebur128=peak=true` must measure within 1.5 LU of the -16 LUFS target and below -1.5 dBTP; near-silent or clipped output fails before an artifact is committed. Picture and speech are staged from identical ordered TimeMap ranges.

## Review

`GET /api/advanced-hero-review` returns the current advanced set without filesystem paths. `GET /api/advanced-hero-review/hero/<candidate_id>` returns one candidate. `GET /media/advanced-hero/<candidate_id>` serves only that set's MP4. Decisions are append-only `ReviewDecision` rows for `approved`, `rejected`, and `changes_requested`. The page has no default selection. The newest decision on the current advanced artifact is the effective decision. Older rows stay in history. A mismatched advanced set returns the existing reload message. Text is assigned with `textContent`.

## Deferred

Envato search and download, publishing, music, full-source WhisperX, speaker attribution, face recognition, automatic approval, analytics, and republish automation.
