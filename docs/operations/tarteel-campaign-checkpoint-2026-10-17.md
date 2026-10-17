# Tarteel campaign checkpoint — candidate mining complete

Checkpoint id: `tarteel-2026-10-17-candidate-mining-v1`

This is the frozen return point for the Tarteel campaign. It records the
current source, rights, derived-media, transcript, visual-analysis, candidate
and local-asset state. Resume from this checkpoint instead of reacquiring or
reminding the operator of the campaign context.

## Code and state identity

- Repository: `Ammar-1652/ai-shortform-engine`
- Project id: `3865ea49-98ce-446e-ae4a-c4f384b0c9fe`
- Profile: `profile-paid-campaign`
- Checkpoint date: 2026-10-17 (Africa/Cairo)
- Code branch: `round-32-tarteel-intake-readiness`
- Code HEAD: `7743ffa` (`fix: register campaign local assets before advanced editing`)
- Draft repair PR: [#34](https://github.com/Ammar-1652/ai-shortform-engine/pull/34)
- PR #34 is stacked on the open motion-direction PR #33; neither is a merged
  claim for this checkpoint.
- SQLite: `var/clipforge.sqlite3`, schema version 6
- Campaign work root: `var/work/campaigns/Tarteel/`
- Derived-media root: `var/work/projects/3865ea49-98ce-446e-ae4a-c4f384b0c9fe/`

The database and all media remain gitignored. The tracked code worktree is
clean at the checkpoint. Do not commit `var/`, source video, models, renders,
or credentials.

## Campaign authority and hard rules

Read these before any resume:

- `var/work/campaigns/Tarteel/intake/campaign-rules.md`
- `var/work/campaigns/Tarteel/intake/campaign-provided-rights-assertion.md`
- `var/work/campaigns/Tarteel/intake/official-playlist-evidence-2026-10-16.md`
- `var/work/campaigns/Tarteel/analysis/source-maps/index.json`
- `var/work/campaigns/Tarteel/analysis/tarteel-60-idea-library.json`
- `var/work/campaigns/Tarteel/analysis/tarteel-60-production-plan.md`

The campaign permits only official playlist footage and campaign-provided
materials. It prohibits added music, added SFX, added narration, unrelated
outside media, misleading/clickbait claims, and negative portrayal of
children. Every edit needs one clear official CTA in the middle or near the
end; use a registered official watermark when original branding is absent.
The post caption first line is exactly:

`اشترك في قناة ترتيل على اليوتيوب: @tarteelarabic`

The raw YouTube SRTs and ASR transcripts are locating evidence, not final
captions. Quran text must be checked against the canonical review in each
source map and then forced-aligned to the selected audio. Hadith, commentary,
and interpretation must not be styled or labelled as Quran. A mistake may be
used only when the surrounding edit preserves the child's dignity.

## Frozen official sources

All six sources are in the official project, hash-bound, rights-cleared as
`campaign_provided`, prepared, and unchanged. The source files are under
`var/work/campaigns/Tarteel/acquisitions/youtube/`.

| video id / file | source asset id | source SHA-256 | duration (us) | video | fps |
|---|---|---|---:|---|---|
| `_Xan0yw2QV8.mp4` | `bec23dec-f8d6-4066-adf2-ac23e21894c3` | `e9987df786087399de5afe2ad2dd80a1b8e44612b12700421ee40a7245196b3d` | 772416667 | AV1 1920×1080 | 24 |
| `39Dq_PfpgSM.mp4` | `0ba39097-3732-4938-961b-b9216aa59a4b` | `1b266f4a69156caea3a9557cf582ca121eaf4d498206f2e777de1349cb53b9bc` | 684416667 | H.264 1920×1080 | 24 |
| `tf6zk3FqGwk.mp4` | `bdafcfaf-73c4-4584-8503-ba6ffb869711` | `64ebef09f37368374748a45295c0b8ec9f20d886f4111cb342d7d2d836a55bb1` | 1154600000 | AV1 1920×1080 | 25 |
| `SXhZvHdfxac.mp4` | `91163bff-32e1-4b1b-9ac7-63b124b770e9` | `1a57a2ff8451749616b2bf0d4d01d6164f25b58b6ff8f34c08df4db1d9412f96` | 1053600000 | H.264 1920×1080 | 25 |
| `zpqQFkCy4Lw.mp4` | `c206c5aa-1035-47d4-b009-25f871c9c9d6` | `692d8f3d5653d300c616fc346fd11f5e8b6ca192c1724cb81a60b65ca5f2977c` | 874440000 | H.264 1920×1080 | 25 |
| `5nKzjkdPj6U.mp4` | `49370e32-35e9-4cc9-bcd3-1bd1a9a2b9f6` | `2bbc1962701feb1dd87783885e31e4a3f1da5889a43db1657bdb8d737f4cb9a2` | 669875000 | H.264 1920×1080 | 24 |

Each source has `proxy/analysis.mp4`, `audio/asr.flac`, recipe sidecars, and
successful `media_prepare`/artifact records. Never replace these with a
manually transcoded file.

## Frozen transcript, vision, and candidate state

Every row below has a successful verified artifact in the source workspace.
Transcript timing is still `approximate`; it is not forced alignment.

| source id | transcript id / model | transcript SHA | vision analysis id / SHA | candidate run id / SHA | selected |
|---|---|---|---|---|---:|
| `bec23dec-f8d6-4066-adf2-ac23e21894c3` | `d876eaa0-3481-42bd-807c-82b4afa12c2a` / `medium` | `f108b3c489e314af83736523a9923ede9ad374c5d10570bb4bd7f59f397e8ff0` | `1895a1de-f782-4646-998f-2f8fdda35589` / `1d5c179866f41ecc8a0cb09cfdca5c0627becf09c880b1da4d387434783e442f` | `c4a48b0e-0a6c-4ea5-8642-be9c81a16f71` / `b7260ec32fb942bca164679535878185fc43e85b4e4d3496194d990a47867cab` | 25 |
| `0ba39097-3732-4938-961b-b9216aa59a4b` | `355fa901-9b9e-455c-87f6-fd9a4195ae01` / `small` | `96dace09549316ac69413d6092907ac5bef34d6ecf123c1961ca8932c54549b2` | `64209820-3364-4300-8bd3-a8506a2d6bc0` / `1b064eeb0612767488a53839aab93b35ac3c84886cf9e41b2bf77b4a2ad0d6be` | `831feab4-5a96-41ac-890b-68554cb2ddf7` / `d1bff9bbf0ee56183890a1519691fa1bc1ffa50237fcceceb22773b75b21c524` | 25 |
| `bdafcfaf-73c4-4584-8503-ba6ffb869711` | `6022b70b-bf78-403d-a2d2-0fa51abcd623` / `small` | `3acc9c90295af00950f367e7155be296b0cf9c478c374f48dec2d3aff2d79ea3` | `961edc98-a2da-4c49-8fb9-95fc2f9fbc80` / `825552af6a29dba7977e3bfc72d8887e61ee7ded3b4cdebf5ef9cea4e427cac8` | `d354d5d3-0bdd-49b9-8ccc-653c3afdafe8` / `95a4d89f26f794a6269ad88503f2e500ca7f0bb0ec795159a5613473bf97c738` | 25 |
| `91163bff-32e1-4b1b-9ac7-63b124b770e9` | `b6e0ed0e-25e5-4040-ba5a-e2efb8dad131` / `small` | `ba7a851eed63d746dda3d3e26e5b5a71c5b97cc01e829d762633c23ab68626bc` | `0e4d816d-168b-412d-a525-95403b68b454` / `3c97c00dd4971ce2de033e66715a3e89a3dc0f376044129011564ed086da4bda` | `5ce899ff-dbf0-410a-b420-0cddf7ca5aef` / `0afbe11c7093853d7f9444b8c61818f44d84a00003cabf60c5d8f6e409b3cb63` | 25 |
| `c206c5aa-1035-47d4-b009-25f871c9c9d6` | `870a877a-1b69-44b0-87f2-1db2c5911e7b` / `small` | `7ceb044281bf2166d4c3b16a5465cc6e22461ec6aec02abb52a5a662a1a736b3` | `c67e6f89-1179-42a8-b222-5c6388f83db1` / `d46cf5c39ac06971400bb46227426d31f1cd58ab8da8967e5057882a02c8d2b1` | `6298112d-3716-4ec2-8c9d-a96d53ed99e2` / `9f6fd0e456f18a3e0224c277280da2fd8e34610cd3eec507574bb9f64964838a` | 22 |
| `49370e32-35e9-4cc9-bcd3-1bd1a9a2b9f6` | `f2ec3d6a-9c8a-44f9-8e0c-f461d654db23` / `small` | `b087881c64f2157bcbb18c2b8136fbfbd0f659da0d5246328c529a7e809fce6e` | `14096b20-b9c7-4961-a1ac-62d215589bf3` / `0b9a7ed091269afe3baa92aeba7d4b6182e184fcdb0d441a058cf1f52c07c31e` | `7f4be1ed-b8f9-4e08-a44b-340e52e3f35c` / `21c608202f28ccdb6dfdb0a75e25edf0a7965bb4877b355803466577eb53dd9e` | 25 |

Total candidate set: 147 candidates. All six candidate sets are bound to their
current transcript and visual-analysis hashes. There are no candidate, Hero,
caption, framing, final, QA, or delivery reviews yet. There are no rough
preview, Hero, or Advanced Hero render artifacts for this project.

## Registered campaign assets

Eight local assets are registered in SQLite with `campaign_provided` rights and
the evidence file
`var/work/campaigns/Tarteel/intake/campaign-provided-rights-assertion.md`:

- `cta/cta-1.mp4` — `37af7188e0be9f9d2d7c8380760bc69345f399423d5227321359433f890c72f9`
- `cta/cta-2-green-screen.mp4` — `8e5e8b632f84c4a3cf51fc2acf33491a18886bac53444f12f3177de5f528e666`
- `cta/cta-3.mp4` — `d55febe3dc76ecd4921029610dbc111d21f9688b46b2dd7f5250898f87dd8c88`
- `cta/cta-4-green-screen.mp4` — `f1a4efb05e9ba0e5cdf0c2e07142f44adfcf5994b152ad5be1509309dadc8a59`
- `brand/watermarks/watermark-1.jpg` — `723d019b9097665aa663ac040cd6af4bd6643b247fed1fbe67da11e2552e95bc`
- `brand/watermarks/watermark-2.jpg` — `2ffb035555c122317e2c709bb6cc5735d483660843f0591b13f8e837e76f7739`
- `brand/watermarks/watermark-3.jpg` — `e6a9abc3904bbd50ba1d5a18d9a0310a9e8bd10c49f5375f9001545b156270a4`
- `brand/watermarks/watermark-4.jpg` — `801c5f60d53b96ff455529213f2ba3e16ad383f7a7c04b6f8baffa392e15a91f`

Each source catalog at
`var/work/projects/<project_id>/sources/<source_asset_id>/metadata/advanced-assets.json`
contains these eight entries. The user-supplied emblem is intentionally not
the registered official watermark set.

## Editorial library and first wave

The complete library is 60 source-grounded ideas in
`var/work/campaigns/Tarteel/analysis/tarteel-60-idea-library.json` and its
Markdown companion. Do not take the Cartesian product of all ideas and styles.
Use one story recipe, one motion style, one caption profile, one CTA choice,
and an explicit variant id per output.

The first 12 pilot ideas are: `tarteel-07`, `tarteel-22`, `tarteel-12`,
`tarteel-46`, `tarteel-45`, `tarteel-33`, `tarteel-11`, `tarteel-23`,
`tarteel-10`, `tarteel-48`, `tarteel-57`, and `tarteel-60`.

Start with six pilots:

1. `tarteel-07`: empathy/callback — mistake, context, reassurance.
2. `tarteel-22`: app proof — hidden verse, attempt, completion/correction.
3. `tarteel-12`: advice — source-grounded advice, explanation, takeaway.
4. `tarteel-33`: reaction ladder — reaction, rating, final score.
5. `tarteel-11`: meeting reveal — arrival, identities, meeting, recitation.
6. `tarteel-46`: educational bridge — food context, canonical Quran reference,
   respectful takeaway.

Compatible editing treatments:

- empathy: editorial-clean, face-follow where eligible, restrained captions;
- app proof: Remotion card/callout, controlled motion, no stock media;
- advice/education: calm whole-line Arabic captions and canonical references;
- comedy/reaction: reaction-first hook and hard semantic cuts, no added SFX;
- meeting: clean reveal pacing and source-grounded lower thirds;
- cross-source montage: only after single-source pilots pass and every segment
  keeps its own audio through the TimeMap.

Use callback hooks only when the later moment is source-grounded and the
TimeMap carries its original audio with it. Never place unrelated audio under a
new shot, split a word at a cut, or force a short into 60 seconds when its
story resolves earlier.

## Resume protocol

When the operator says “continue working on the Tarteel campaign,” do this
before changing anything:

```bash
git status --short --branch
uv run clipforge db status
uv run clipforge media verify SOURCE_ID
uv run clipforge transcript verify SOURCE_ID
uv run clipforge vision verify SOURCE_ID
uv run clipforge candidate verify SOURCE_ID
uv run clipforge assets verify-local SOURCE_ID
```

Run the verify commands for all six source ids in the table. Do not use
`--force` and do not rerun transcription or analysis unless a deliberate new
checkpoint is being created. A changed source hash, recipe, model revision,
transcript, visual artifact, or candidate artifact creates a new checkpoint;
the old checkpoint remains immutable.

Then select pilot candidates by their source windows and idea ids, render a
rough preview for review, and append human candidate decisions:

```bash
uv run clipforge preview render SOURCE_ID --candidate-id CANDIDATE_ID
uv run clipforge preview list SOURCE_ID
uv run clipforge review open SOURCE_ID
uv run clipforge review decide SOURCE_ID CANDIDATE_ID \
  --decision approved \
  --reviewer-id HUMAN_REVIEWER_ID \
  --preview-set-id PREVIEW_SET_ID_FROM_PREVIEW_LIST \
  --manifest-sha256 MANIFEST_SHA_FROM_PREVIEW_LIST \
  --artifact-id PREVIEW_ARTIFACT_ID \
  --project-id 3865ea49-98ce-446e-ae4a-c4f384b0c9fe
```

The four values ending in `_FROM_PREVIEW_LIST` must be copied from the
current preview set; do not invent them. The decision command is append-only
and must be run only after a human has watched the preview with audio and with
muted playback. `approved` is an example, not a pre-recorded decision.

Do not start Hero or Advanced Hero until a human has watched the rough preview
with audio and muted playback. Arabic forced alignment is currently not a
verified-live claim; final Quran captions require the canonical text review,
selected-clip audio alignment, and human review. A technically valid candidate
is not an approval or a delivery package.

## Freeze boundary

This checkpoint freezes intake and candidate mining, not the campaign forever.
System enhancements may be developed on another code branch, but they must not
rewrite these source, transcript, vision, candidate, rights, or asset records.
After an enhancement, compare the current hashes to this document before
resuming. If the enhancement changes a recipe, model, style, or contract, use a
new checkpoint id and keep this one available for comparison.
