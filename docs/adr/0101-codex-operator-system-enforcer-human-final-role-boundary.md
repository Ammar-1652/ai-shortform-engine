# ADR 0101: Codex operator, deterministic system, and human final review

**Status:** accepted for the operator-driven local workflow

## Context

Clipforge is operated by Codex in this workspace. Codex chooses source
intervals, editorial structure, caption corrections, framing, graphics, and
rights-cleared supporting assets. Clipforge executes those choices through
typed local tools and enforces timing, provenance, rights, cache, QA, and
delivery gates. A person watches the exact encoded result before it can be
accepted or delivered.

The previous contracts described many candidate and Hero decisions as human
reviews even when Codex was the authorized operator. That made the workflow
ambiguous and encouraged manual batch files to stand in for the production
path. Final playback must remain human because automated metadata and frame
inspection cannot truthfully claim a person's viewing decision.

## Decision

Every current production workflow uses three explicit responsibilities:

1. `codex_operator` is the editorial brain. It reads policy, source evidence,
   transcript/alignment, visual analysis, existing artifacts, and the selected
   skill. It chooses a source-grounded plan and invokes approved Clipforge
   tools. It may record candidate, Hero, caption, framing, direction, speech,
   and arc decisions. It cannot approve a final artifact or claim human
   playback.
2. `system_enforcer` is the deterministic muscle. Typed Python services,
   ffmpeg/ffprobe, Remotion, storage, rights checks, TimeMap conversion,
   cache identity, stale checks, QA, and delivery verify and execute the
   declarative plan. A skill, MCP result, repository, or agent may not inject
   executable renderer code or bypass these gates.
3. `human_reviewer` watches the exact MP4 with audio and muted playback and
   records the append-only final decision. Only this role can approve a final
   artifact for local delivery.

`ReviewDecision.reviewer_role` is persisted in SQLite. Final decisions reject
`codex_operator`; candidate and Hero editorial decisions may use either
Codex or a person. `WorkflowRolePolicy` is carried by campaign and Advanced
Hero documents. The policy keeps external publishing deferred.

## Tool and extension boundary

Codex selects capabilities through project skills and calls the existing CLI
or typed service. Each capability has one owner:

- source probing and extracts: media tools and `source` / `media` CLI;
- transcription and forced alignment: language/transcript services and
  `hero align`;
- candidate mining and review decisions: candidate service and review CLI;
- hook/body/punch and presentation: the project motion-direction skill,
  `DirectionDocument`, and `EditorialArcDocument`;
- crops and face-safe framing: reframe/Advanced Hero plan contracts;
- captions: shared caption builders and Remotion caption components;
- B-roll, images, fonts, and SFX: registered asset catalog, license records,
  and typed direction placements;
- motion graphics: allowlisted Remotion components selected by typed events;
- encoding and checkpoints: Advanced Hero service and Remotion backend;
- proof: ffprobe, decoded frame/audio evidence, QA, and final review.

Future tools, MCP adapters, repositories, or skills must first produce a
source-grounded typed input at the appropriate boundary. They may not call
the renderer directly, write an approval, replace the TimeMap, or store
credentials in production artifacts. Their identity, version, license, and
output-changing files enter the existing provenance and cache fingerprint.

## Consequences

Codex can run the complete editorial and technical workflow without waiting for
human approval at each intermediate step. The system still stops when evidence
is missing or stale, and delivery still stops until a human reviews the exact
artifact. Old review rows and artifacts remain readable; new rows record their
role explicitly through migration 7.
