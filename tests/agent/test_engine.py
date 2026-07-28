from pathlib import Path

import pytest

from study_notes.agent.context import EngineContext
from study_notes.config import Config
from study_notes.embedding import FakeEmbedder
from study_notes.tools.vault_write import VaultWriter
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _ctx(tmp_path, db_conn):
    for n in ["orchestrator", "note_writing", "enrichment", "anti_slop"]:
        (tmp_path / f"{n}.md").write_text(n)
    cfg = Config(vault_path=tmp_path, notes_root="Notes",
                 attachments_dir="Attachments", frames_subdir="frames",
                 database_url="unused", embedding_model="fake",
                 models={"orchestrator": "opus", "extractor": "sonnet", "enricher": "haiku"},
                 prompts={"orchestrator": str(tmp_path / "orchestrator.md"),
                          "note_writing": str(tmp_path / "note_writing.md"),
                          "enrichment": str(tmp_path / "enrichment.md"),
                          "anti_slop": str(tmp_path / "anti_slop.md")},
                 dry_run=False)
    index = VaultIndex(db_conn, FakeEmbedder())
    return EngineContext(config=cfg, index=index, writer=VaultWriter(cfg, index))


def test_build_options_wires_models_agents_tools(tmp_path, db_conn):
    from study_notes.agent.engine import build_options

    opts = build_options(_ctx(tmp_path, db_conn))
    assert opts.model == "opus"
    assert set(opts.agents) == {"extractor", "enricher"}
    assert "study-notes" in opts.mcp_servers
    assert "mcp__study-notes__vault_write" in opts.allowed_tools
    assert "WebSearch" in opts.allowed_tools
    assert opts.permission_mode == "bypassPermissions"


@pytest.mark.asyncio
async def test_run_ingest_raises_on_error_result(tmp_path, db_conn, monkeypatch):
    from claude_agent_sdk import ResultMessage

    from study_notes.agent import engine
    from study_notes.agent.engine import EngineError, run_ingest

    async def fake_query(*, prompt, options):
        yield ResultMessage(subtype="error_max_turns", duration_ms=1, duration_api_ms=1,
                            is_error=True, num_turns=1, session_id="s", result="boom")

    monkeypatch.setattr(engine, "query", fake_query)
    with pytest.raises(EngineError):
        await run_ingest(_ctx(tmp_path, db_conn), "go")


@pytest.mark.asyncio
async def test_run_ingest_returns_text_on_success(tmp_path, db_conn, monkeypatch):
    from claude_agent_sdk import ResultMessage

    from study_notes.agent import engine
    from study_notes.agent.engine import run_ingest

    async def fake_query(*, prompt, options):
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                            is_error=False, num_turns=1, session_id="s", result="the plan")

    monkeypatch.setattr(engine, "query", fake_query)
    out = await run_ingest(_ctx(tmp_path, db_conn), "go")
    assert out == "the plan"
