from study_notes.config import Config


def _cfg(tmp_path):
    nw = tmp_path / "nw.md"
    nw.write_text("NOTE-WRITING")
    en = tmp_path / "en.md"
    en.write_text("ENRICH")
    sl = tmp_path / "slop.md"
    sl.write_text("ANTISLOP")
    return Config(
        vault_path=tmp_path,
        notes_root="r",
        attachments_dir="a",
        frames_subdir="frames",
        database_url="u",
        embedding_model="m",
        models={"extractor": "sonnet", "enricher": "haiku"},
        prompts={"note_writing": str(nw), "enrichment": str(en), "anti_slop": str(sl)},
        dry_run=False,
    )


def test_build_agents_sets_models_and_prompts(tmp_path):
    from study_notes.agent.agents import build_agents

    agents = build_agents(_cfg(tmp_path))
    assert set(agents) == {"extractor", "enricher"}
    assert agents["extractor"].model == "sonnet"
    assert "NOTE-WRITING" in agents["extractor"].prompt
    assert "ANTISLOP" in agents["extractor"].prompt
    assert agents["enricher"].model == "haiku"
    assert "ENRICH" in agents["enricher"].prompt
    assert "WebSearch" in agents["enricher"].tools
    assert "Read" in agents["extractor"].tools
    assert "mcp__study-notes__select_keyframes" in agents["extractor"].tools
    assert "mcp__study-notes__keep_frame" in agents["extractor"].tools
