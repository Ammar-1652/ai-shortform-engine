"""The Codex-to-tool routing catalogue stays aligned with the real CLI."""

from click.testing import CliRunner
from typer.main import get_command

from clipforge.cli.main import app
from clipforge.operator.catalogue import CAPABILITIES, EXTENSIONS, validate_catalogue


def test_catalogue_has_unique_capabilities_and_real_commands() -> None:
    validate_catalogue(get_command(app))
    ids = [item.capability_id for item in CAPABILITIES]
    assert len(ids) == len(set(ids))
    assert len(CAPABILITIES) >= 20


def test_final_approval_is_human_and_extensions_cannot_bypass_gates() -> None:
    final = next(item for item in CAPABILITIES if item.capability_id == "final-accept")
    assert final.owner == "human_reviewer"
    assert final.execution == "human_decision"
    assert {item.kind for item in EXTENSIONS} == {
        "skill",
        "editorial_reference",
        "local_tool",
        "mcp",
        "renderer_component",
        "asset_pack",
    }
    assert all("TimeMap bypass" in item.prohibited_authority for item in EXTENSIONS)


def test_operator_cli_is_read_only_metadata() -> None:
    runner = CliRunner()
    result = runner.invoke(get_command(app), ["operator", "verify"])
    assert result.exit_code == 0
    assert "verified_capabilities:" in result.stdout
    assert "not_claimed" in result.stdout
