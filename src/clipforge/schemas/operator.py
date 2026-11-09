"""Discovery metadata for tools; these records never execute a command."""

from typing import Literal, Self

from pydantic import Field, model_validator

from clipforge.schemas.common import EntityId, Versioned


class OperatorCapability(Versioned):
    capability_id: EntityId
    purpose: str = Field(min_length=1)
    owner: Literal["codex_operator", "human_reviewer"] = "codex_operator"
    plane: Literal["control", "media", "decision", "asset", "review"]
    command: list[str] = Field(min_length=1)
    requires: list[str] = Field(min_length=1)
    produces: list[str] = Field(min_length=1)
    execution: Literal["read", "write", "human_decision"]
    limitation: str = Field(min_length=1)

    @model_validator(mode="after")
    def authority_is_explicit(self) -> Self:
        if self.execution == "human_decision" and self.owner != "human_reviewer":
            raise ValueError("human decisions cannot be assigned to Codex")
        if (
            self.command[:2] == ["final", "review"]
            and self.command[-1] == "decide"
            and (self.owner != "human_reviewer" or self.execution != "human_decision")
        ):
            raise ValueError("final approval belongs to the human reviewer")
        if any(not part.isascii() or not part.replace("-", "").isalnum() for part in self.command):
            raise ValueError("capability commands contain literal CLI names only")
        return self


class ExtensionBoundary(Versioned):
    kind: Literal["skill", "editorial_reference", "local_tool", "mcp", "renderer_component", "asset_pack"]
    approved_location: str = Field(min_length=1)
    consumer: str = Field(min_length=1)
    required_evidence: list[str] = Field(min_length=1)
    prohibited_authority: list[str] = Field(min_length=1)
