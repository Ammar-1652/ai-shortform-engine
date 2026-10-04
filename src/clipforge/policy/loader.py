"""Load JSON profiles and policies. Paths are checked before they are resolved."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from clipforge.errors import ClipforgeError
from clipforge.paths import find_repo_root
from clipforge.schemas.governance import CampaignProfile, ComplianceRule
from clipforge.schemas.provenance import ArtifactProvenance


class PolicyError(ClipforgeError):
    """A profile or policy file cannot be used. This is not a pass."""


@dataclass(frozen=True, slots=True)
class PolicyResolution:
    policy_id: str
    name: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ProfileResolution:
    profile_id: str
    name: str
    mode: str
    objective: str
    policies: tuple[PolicyResolution, ...]
    profile_sha256: str
    provenance: ArtifactProvenance

    @property
    def policy_ids(self) -> tuple[str, ...]:
        return tuple(item.policy_id for item in self.policies)


@dataclass(frozen=True, slots=True)
class PolicyCatalog:
    profiles: dict[str, CampaignProfile]
    policies: dict[str, ComplianceRule]
    profile_sha256: dict[str, str]
    policy_sha256: dict[str, str]


def repo_config_root() -> Path:
    return find_repo_root() / "configs"


def load_catalog(config_root: Path | None = None) -> PolicyCatalog:
    """Read every profile and policy. Duplicate ids and bad files fail closed."""
    root = config_root if config_root is not None else repo_config_root()
    profiles = _load_dir(root / "profiles", CampaignProfile, "profile", "profile_id")
    policies = _load_dir(root / "policies", ComplianceRule, "policy", "rule_id")
    return PolicyCatalog(
        profiles={item.profile_id: item for item, _digest in profiles},
        policies={item.rule_id: item for item, _digest in policies},
        profile_sha256={item.profile_id: digest for item, digest in profiles},
        policy_sha256={item.rule_id: digest for item, digest in policies},
    )


def resolve_profile(
    profile_id: str,
    *,
    config_root: Path | None = None,
    catalog: PolicyCatalog | None = None,
    provenance: ArtifactProvenance | None = None,
) -> ProfileResolution:
    """Resolve one profile and every policy it names. Missing policies do not pass."""
    loaded = catalog if catalog is not None else load_catalog(config_root)
    profile = loaded.profiles.get(profile_id)
    if profile is None:
        raise PolicyError(
            f"unknown profile {profile_id}. Run `clipforge profile list` to see the profiles on disk."
        )
    resolved: list[PolicyResolution] = []
    for policy_id in sorted(profile.policy_ids):
        policy = loaded.policies.get(policy_id)
        if policy is None:
            raise PolicyError(
                f"profile {profile_id} references missing policy {policy_id}. A missing policy is not a pass."
            )
        resolved.append(PolicyResolution(policy.rule_id, policy.name, loaded.policy_sha256[policy.rule_id]))
    return ProfileResolution(
        profile_id=profile.profile_id,
        name=profile.name,
        mode=profile.mode.value,
        objective=profile.objective,
        policies=tuple(resolved),
        profile_sha256=loaded.profile_sha256[profile.profile_id],
        provenance=provenance
        if provenance is not None
        else ArtifactProvenance(
            created_at=datetime.now(UTC),
            created_by="clipforge",
            tool="clipforge-profile",
            tool_version="0",
        ),
    )


def canonical_sha256(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_ModelT = TypeVar("_ModelT", CampaignProfile, ComplianceRule)


def _load_dir(
    directory: Path,
    model: type[_ModelT],
    label: str,
    identity: str,
) -> list[tuple[_ModelT, str]]:
    if directory.is_symlink():
        raise PolicyError(f"{label} config root is a symlink")
    if not directory.is_dir():
        raise PolicyError(f"{label} config root is missing")
    found: dict[str, tuple[_ModelT, str]] = {}
    paths = sorted(path for path in directory.iterdir() if path.name.endswith(".json"))
    for path in paths:
        relative = path.name
        confined = _confine(directory, relative, label)
        try:
            payload = json.loads(confined.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyError(f"{label} file {relative} is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict) or "schema_version" not in payload:
            raise PolicyError(f"{label} file {relative} must contain schema_version")
        try:
            parsed = model.model_validate(payload)
        except ValidationError as exc:
            raise PolicyError(f"{label} file {relative} was rejected: {exc}") from exc
        key = str(getattr(parsed, identity))
        if key in found:
            raise PolicyError(f"duplicate {label} id {key}")
        canonical = parsed.model_dump(mode="json")
        if identity == "profile_id":
            canonical["policy_ids"] = sorted(canonical["policy_ids"])
        found[key] = (parsed, canonical_sha256(canonical))
    return [found[key] for key in sorted(found)]


def _confine(root: Path, relative: str, label: str) -> Path:
    if (
        not relative
        or relative.startswith(("/", "\\"))
        or "\\" in relative
        or "\x00" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise PolicyError(f"{label} path escapes the config root")
    current = root
    for part in relative.split("/"):
        current = current / part
        if current.is_symlink():
            raise PolicyError(f"{label} file is a symlink")
    resolved = current.resolve()
    root_resolved = root.resolve()
    if resolved != root_resolved and root_resolved not in resolved.parents:
        raise PolicyError(f"{label} path escapes the config root")
    return resolved
