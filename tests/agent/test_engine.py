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
    cfg = Config(vault_path=tmp_path, notes_root="04 - Resources",
                 attachments_dir="06 - Attachments", frames_subdir="frames",
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
