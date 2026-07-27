import json

import pytest

from study_notes.claude_runner import (
    ClaudeRunError,
    TOOL_NAMES,
    WRITE_TOOL,
    build_command,
    mcp_config_dict,
    parse_result,
)


def test_mcp_config_points_at_server_with_env():
    cfg = mcp_config_dict("/x/config.toml")
    server = cfg["mcpServers"]["study-notes-tools"]
    assert server["command"] == "uv"
    assert server["args"][-1] == "study_notes.mcp_server"
    assert server["env"]["STUDY_NOTES_CONFIG"] == "/x/config.toml"


def test_build_command_includes_flags_and_all_tools():
    cmd = build_command(
        input_prompt="ingest https://x", model="claude-opus-4-8",
        system_prompt="PROC", mcp_config_path="/tmp/mcp.json",
        add_dirs=["/vault"], dry_run=False,
    )
    assert cmd[0] == "claude" and "-p" in cmd
    assert "--model" in cmd and "claude-opus-4-8" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--mcp-config" in cmd and "/tmp/mcp.json" in cmd
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert WRITE_TOOL in allowed  # write tool present when not dry-run
    for name in TOOL_NAMES:
        assert name in allowed


def test_build_command_dry_run_omits_write_tool():
    cmd = build_command(
        input_prompt="p", model="m", system_prompt="s",
        mcp_config_path="/tmp/mcp.json", add_dirs=[], dry_run=True,
    )
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert WRITE_TOOL not in allowed
    assert "mcp__study-notes-tools__vault_search" in allowed  # read tools still allowed


def test_parse_result_returns_result_text():
    out = json.dumps({"type": "result", "is_error": False, "result": "done: wrote 2 notes"})
    assert parse_result(out) == "done: wrote 2 notes"


def test_parse_result_raises_on_error_envelope():
    out = json.dumps({"type": "result", "is_error": True, "result": "boom"})
    with pytest.raises(ClaudeRunError):
        parse_result(out)


def test_parse_result_raises_on_garbage():
    with pytest.raises(ClaudeRunError):
        parse_result("not json")


def test_parse_result_raises_on_non_object_json():
    with pytest.raises(ClaudeRunError):
        parse_result("5")
    with pytest.raises(ClaudeRunError):
        parse_result("[1, 2, 3]")


def test_build_command_sets_bypass_permission_mode():
    cmd = build_command(
        input_prompt="p", model="m", system_prompt="s",
        mcp_config_path="/tmp/mcp.json", add_dirs=[], dry_run=False,
    )
    assert "--permission-mode" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "bypassPermissions"
