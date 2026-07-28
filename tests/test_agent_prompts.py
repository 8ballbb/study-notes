from pathlib import Path


def test_orchestrator_prompt_covers_flow():
    t = Path("prompts/orchestrator.md").read_text().lower()
    for kw in ["decompose", "extractor", "enricher", "list_categories",
               "vault_search", "vault_write", "source", "verify"]:
        assert kw in t, kw


def test_note_writing_guide_is_toolbox_not_qa_default():
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "understand" in t and "concise" in t
    assert "compose" in t or "toolbox" in t  # formats combine, not one-per-note


def test_enrichment_guide_requires_sources():
    t = Path("prompts/enrichment.md").read_text().lower()
    assert "websearch" in t or "web search" in t
    assert "source" in t and ("cite" in t or "url" in t)
