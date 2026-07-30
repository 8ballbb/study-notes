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


def test_tool_server_has_new_frame_tools(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    _, fns = build_tool_server(_ctx(tmp_path, db_conn))
    assert {"prepare_video", "select_keyframes", "keep_frame"} <= set(fns)
    assert "extract_frame" not in fns


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


@pytest.mark.asyncio
async def test_keep_frame_tool_embed_path_includes_video_id(tmp_path, db_conn, monkeypatch):
    # keep_frame tool returns an embed path scoped under the video_id folder
    from study_notes.agent import tools as t

    monkeypatch.setattr(t.fr, "keep_frame",
                        lambda cp, prefix, ts, vid, fd: "liver_00-00-05.jpg")
    _, tools = t.build_tool_server(_ctx(tmp_path, db_conn))
    out = json.loads(_text(await _call(tools, "keep_frame", {
        "candidate_path": "/x/c.jpg", "prefix": "liver",
        "timestamp": "00:00:05", "video_id": "vidABC",
    })))
    assert out["embed_path"] == "Attachments/frames/vidABC/liver_00-00-05.jpg"


@pytest.mark.asyncio
async def test_select_keyframes_tool_returns_candidates_and_montage(tmp_path, db_conn, monkeypatch):
    from study_notes.agent import tools as t

    def fake_select(video_path, start, end, budget, out_dir):
        return {
            "candidates": [
                {"path": out_dir / "cand_001.jpg", "timestamp": "00:00:01", "index": 0},
                {"path": out_dir / "cand_002.jpg", "timestamp": "00:00:02", "index": 1},
            ],
            "montage_path": out_dir / "montage.jpg",
        }

    monkeypatch.setattr(t.fr, "select_keyframes", fake_select)
    _, tools = t.build_tool_server(_ctx(tmp_path, db_conn))
    video_path = tmp_path / "video.mp4"
    out = json.loads(_text(await _call(tools, "select_keyframes", {
        "video_path": str(video_path), "start": "00:00:00", "end": "00:00:10", "budget": 5,
    })))
    assert out["candidates"] == [
        {"candidate_path": str(tmp_path / "cands_000000_000010" / "cand_001.jpg"),
         "timestamp": "00:00:01", "index": 0},
        {"candidate_path": str(tmp_path / "cands_000000_000010" / "cand_002.jpg"),
         "timestamp": "00:00:02", "index": 1},
    ]
    assert out["montage_path"] == str(tmp_path / "cands_000000_000010" / "montage.jpg")
