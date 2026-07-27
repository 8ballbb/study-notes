from pathlib import Path

PROC = Path("prompts/procedure.md")


def test_procedure_names_all_tools_and_steps():
    text = PROC.read_text()
    for tool in ["fetch_youtube_transcript", "list_categories", "vault_search",
                 "extract_frame", "check_slop", "vault_write"]:
        assert tool in text, f"procedure must mention {tool}"
    for step in ["Segment", "Extract", "categor", "Verify"]:
        assert step.lower() in text.lower()
    # must instruct using the exact provided source string
    assert "source" in text.lower()
