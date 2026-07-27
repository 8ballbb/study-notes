import pytest


def test_server_registers_all_five_tools():
    from study_notes import mcp_server

    tool_names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert {
        "fetch_youtube_transcript",
        "list_categories",
        "vault_search",
        "extract_frame",
        "vault_write",
    } <= tool_names


def test_server_name():
    from study_notes import mcp_server

    assert mcp_server.mcp.name == "study-notes-tools"
