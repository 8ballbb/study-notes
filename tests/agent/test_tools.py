import json
from datetime import date

import pytest

from study_notes.agent.context import EngineContext
from study_notes.config import Config
from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance
from study_notes.tools.vault_write import VaultWriter
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _ctx(tmp_path, db_conn):
    cfg = Config(vault_path=tmp_path, notes_root="Notes",
                 attachments_dir="Attachments", frames_subdir="frames",
                 database_url="unused", embedding_model="fake",
                 models={}, prompts={}, dry_run=False)
    index = VaultIndex(db_conn, FakeEmbedder())
    return EngineContext(config=cfg, index=index, writer=VaultWriter(cfg, index))


def _text(result: dict) -> str:
    return result["content"][0]["text"]


async def _call(tools, name, args):
    return await tools[name](args)


@pytest.mark.asyncio
async def test_list_categories_and_search_tools(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    ctx = _ctx(tmp_path, db_conn)
    ctx.index.upsert_category("Web APIs", "http")
    prov = Provenance(origin="u", input_type="youtube", captured_at=date.today(), source_date=None)
    ctx.index.upsert_note(Note(path="Notes/Web APIs/HTTP.md", title="HTTP",
                               category="Web APIs", content="status codes", provenance=prov))
    _, tools = build_tool_server(ctx)

    cats = json.loads(_text(await _call(tools, "list_categories", {})))
    assert any(c["name"] == "Web APIs" for c in cats)

    hits = json.loads(_text(await _call(tools, "vault_search",
                                        {"query": "status codes", "category": "Web APIs"})))
    assert any("HTTP" in h["path"] for h in hits)


@pytest.mark.asyncio
async def test_check_slop_tool(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    _, tools = build_tool_server(_ctx(tmp_path, db_conn))
    findings = json.loads(_text(await _call(tools, "check_slop",
                                            {"text": "Here's the thing. Studies show it."})))
    assert findings  # detects slop


@pytest.mark.asyncio
async def test_vault_write_tool_writes_note(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    ctx = _ctx(tmp_path, db_conn)
    _, tools = build_tool_server(ctx)
    out = json.loads(_text(await _call(tools, "vault_write", {
        "title": "Raft", "category": "Distributed Systems",
        "markdown": "---\ntitle: Raft\ncategory: Distributed Systems\n---\n\n## Notes\n- x\n",
        "source": "https://youtu.be/abc", "source_type": "youtube", "source_date": "2025-11-14",
    })))
    assert out["path"].endswith("Raft.md")
    assert (tmp_path / out["path"]).exists()
