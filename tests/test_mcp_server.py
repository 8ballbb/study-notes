import pytest


def test_server_registers_all_tools():
    from study_notes import mcp_server

    tool_names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert {
        "fetch_youtube_transcript", "list_categories", "vault_search",
        "extract_frame", "vault_write", "check_slop",
    } <= tool_names


def test_server_name():
    from study_notes import mcp_server

    assert mcp_server.mcp.name == "study-notes-tools"


def test_validate_write_action_rejects_unknown_action():
    from study_notes.mcp_server import _validate_write_action

    with pytest.raises(ValueError):
        _validate_write_action("update", None)


def test_validate_write_action_merge_requires_target():
    from study_notes.mcp_server import _validate_write_action

    with pytest.raises(ValueError):
        _validate_write_action("merge", None)


def test_validate_write_action_new_note_rejects_target():
    from study_notes.mcp_server import _validate_write_action

    with pytest.raises(ValueError):
        _validate_write_action("new_note", "some/note.md")


def test_validate_write_action_accepts_valid_combos():
    from study_notes.mcp_server import _validate_write_action

    _validate_write_action("new_note", None)   # no raise
    _validate_write_action("merge", "a/b.md")  # no raise
