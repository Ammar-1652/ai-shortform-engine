# Round 11 validation

Date: 2026-10-04. Branch `round-11-profiles-policy-qa`. Started from Round 10 merge `81d49fff27f6ee8a2765746fc9054ac3e27a55ba`. The pull request is a draft and is not merged.

## Scope

Profiles and policies load from `configs/`. `profile-organic` keeps `policy-source-rights`. `profile-paid-campaign` adds `policy-asset-rights`. QA writes `qa_set_json` for the current advanced Hero artifact. SQLite schema stays 4.

Commands:

```text
clipforge profile doctor
clipforge profile list
clipforge profile show PROFILE_ID
clipforge profile verify PROFILE_ID
clipforge project set-profile PROJECT_ID PROFILE_ID
clipforge qa doctor
clipforge qa run SOURCE_ID
clipforge qa list SOURCE_ID
clipforge qa show SOURCE_ID
clipforge qa verify SOURCE_ID
clipforge qa gate SOURCE_ID
```

`qa run` exits 0 only when technical and campaign QA both pass. `qa verify` and `qa gate` do not rewrite the set.

## Checks

`./scripts/validate.sh` passed. That runs Ruff, format, mypy (158 source files), pytest (328 passed), `clipforge schema check`, renderer lint, typecheck, and 23 Vitest tests, then `clipforge doctor` (10 pass, schema version 4).

`tests/test_policy_qa.py` loads both profiles, rejects malformed and symlinked configuration, assigns a profile on create and on an existing project, and blocks an unprofiled project before a QA job. The synthetic advanced Hero smoke assigns `profile-organic`, runs QA, and gets technical pass and campaign pass. `qa show` contains no absolute path. `qa verify` and `qa gate` pass. After the source rights row is set to `prohibited`, both verify and gate fail and the previous passing set is not treated as current. A sidecar publish failure leaves the previous QA sidecar in place. A cancelled run records a cancelled QA job and does not publish a sidecar.

## Limitations

- No Envato search or download.
- No publishing, analytics, or automatic approval.
- No full-source WhisperX, speaker attribution, or face recognition.
- Music remains prohibited. Local B-roll and SFX stay supported.
- QA does not render media and does not replace Hero or advanced Hero review.
