"""Explicit responsibility boundaries for an operator-driven Clipforge run."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from clipforge.schemas.common import Versioned


class WorkflowRole(StrEnum):
    """Stable role names used in review and workflow contracts."""

    CODEX_OPERATOR = "codex_operator"
    SYSTEM_ENFORCER = "system_enforcer"
    HUMAN_REVIEWER = "human_reviewer"


class WorkflowRolePolicy(Versioned):
    """The responsibility split for one production run.

    Codex owns source-grounded editorial choices and orchestration. Clipforge
    owns deterministic media, provenance, rights, timing, cache, and QA gates.
    A person remains the only authority that can accept the final playback.
    """

    editorial_operator: Literal["codex_operator"] = "codex_operator"
    deterministic_enforcer: Literal["system_enforcer"] = "system_enforcer"
    final_reviewer: Literal["human_reviewer"] = "human_reviewer"
    final_playback_required: Literal[True] = True
    external_publishing: Literal["deferred"] = "deferred"


DEFAULT_WORKFLOW_ROLE_POLICY = WorkflowRolePolicy()
