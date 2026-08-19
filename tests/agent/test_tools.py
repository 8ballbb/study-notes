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


def _ctx(tmp_path, db_conn, browser=None, frames=None, ask_fn=None):
    cfg = Config(
        vault_path=tmp_path,
        notes_root="Notes",
        attachments_dir="Attachments",
        frames_subdir="frames",
        database_url="unused",
        embedding_model="fake",
        models={},
        prompts={},
        dry_run=False,
        frames=frames or {},
        browser=browser or {"profile": "~/.study-notes/browser-profile"},
    )
    index = VaultIndex(db_conn, FakeEmbedder())
    return EngineContext(config=cfg, index=index, writer=VaultWriter(cfg, index), ask_fn=ask_fn)


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
    ctx.index.upsert_note(
        Note(
            path="Notes/Web APIs/HTTP.md",
            title="HTTP",
            category="Web APIs",
            content="status codes",
            provenance=prov,
        )
    )
    _, tools = build_tool_server(ctx)

    cats = json.loads(_text(await _call(tools, "list_categories", {})))
    assert any(c["name"] == "Web APIs" for c in cats)

    hits = json.loads(
        _text(await _call(tools, "vault_search", {"query": "status codes", "category": "Web APIs"}))
    )
    assert any("HTTP" in h["path"] for h in hits)


@pytest.mark.asyncio
async def test_check_slop_tool(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    _, tools = build_tool_server(_ctx(tmp_path, db_conn))
    findings = json.loads(
        _text(await _call(tools, "check_slop", {"text": "Here's the thing. Studies show it."}))
    )
    assert findings  # detects slop


@pytest.mark.asyncio
async def test_vault_write_tool_writes_note(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    ctx = _ctx(tmp_path, db_conn)
    _, tools = build_tool_server(ctx)
    out = json.loads(
        _text(
            await _call(
                tools,
                "vault_write",
                {
                    "title": "Raft",
                    "category": "Distributed Systems",
                    "markdown": "---\ntitle: Raft\ncategory: Distributed Systems\n---\n\n## Notes\n- x\n",
                    "source": "https://youtu.be/abc",
                    "source_type": "youtube",
                    "source_date": "2025-11-14",
                },
            )
        )
    )
    assert out["path"].endswith("Raft.md")
    assert (tmp_path / out["path"]).exists()


@pytest.mark.asyncio
async def test_keep_frame_tool_embed_path_includes_video_id(tmp_path, db_conn, monkeypatch):
    # keep_frame tool returns an embed path scoped under the video_id folder
    from study_notes.agent import tools as t

    monkeypatch.setattr(t.fr, "keep_frame", lambda cp, prefix, ts, vid, fd: "liver_00-00-05.jpg")
    _, tools = t.build_tool_server(_ctx(tmp_path, db_conn))
    out = json.loads(
        _text(
            await _call(
                tools,
                "keep_frame",
                {
                    "candidate_path": "/x/c.jpg",
                    "prefix": "liver",
                    "timestamp": "00:00:05",
                    "video_id": "vidABC",
                },
            )
        )
    )
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
    out = json.loads(
        _text(
            await _call(
                tools,
                "select_keyframes",
                {
                    "video_path": str(video_path),
                    "start": "00:00:00",
                    "end": "00:00:10",
                    "budget": 5,
                },
            )
        )
    )
    assert out["candidates"] == [
        {
            "candidate_path": str(tmp_path / "cands_000000_000010" / "cand_001.jpg"),
            "timestamp": "00:00:01",
            "index": 0,
        },
        {
            "candidate_path": str(tmp_path / "cands_000000_000010" / "cand_002.jpg"),
            "timestamp": "00:00:02",
            "index": 1,
        },
    ]
    assert out["montage_path"] == str(tmp_path / "cands_000000_000010" / "montage.jpg")


@pytest.mark.asyncio
async def test_select_keyframes_budget_defaults_from_config(tmp_path, db_conn, monkeypatch):
    from study_notes.agent import tools as t

    seen = {}

    def fake_select(video_path, start, end, budget, out_dir):
        seen["budget"] = budget
        return {"candidates": [], "montage_path": out_dir / "montage.jpg"}

    monkeypatch.setattr(t.fr, "select_keyframes", fake_select)
    ctx = _ctx(tmp_path, db_conn, frames={"enabled": True, "budget": 3})
    _, tools = t.build_tool_server(ctx)
    # No "budget" in args -> falls back to the configured [frames].budget (3), never zero.
    json.loads(
        _text(
            await _call(
                tools,
                "select_keyframes",
                {
                    "video_path": str(tmp_path / "v.mp4"),
                    "start": "00:00:00",
                    "end": "00:00:05",
                },
            )
        )
    )
    assert seen["budget"] == 3


@pytest.mark.asyncio
async def test_frames_disabled_short_circuits(tmp_path, db_conn, monkeypatch):
    from study_notes.agent import tools as t

    called = {"select": False, "download": False}
    monkeypatch.setattr(
        t.fr, "select_keyframes", lambda *a, **k: called.__setitem__("select", True)
    )
    monkeypatch.setattr(
        t.fr, "download_video", lambda *a, **k: called.__setitem__("download", True)
    )
    ctx = _ctx(tmp_path, db_conn, frames={"enabled": False})
    _, tools = t.build_tool_server(ctx)
    pv = json.loads(_text(await _call(tools, "prepare_video", {"url": "https://y/x"})))
    sk = json.loads(
        _text(
            await _call(
                tools,
                "select_keyframes",
                {
                    "video_path": str(tmp_path / "v.mp4"),
                    "start": "00:00:00",
                    "end": "00:00:05",
                },
            )
        )
    )
    assert pv["disabled"] is True
    assert sk["disabled"] is True
    assert called == {"select": False, "download": False}  # real work skipped


@pytest.mark.asyncio
async def test_ask_user_tool_returns_typed_answer(tmp_path, db_conn):
    from study_notes.agent import tools as t

    ctx = _ctx(tmp_path, db_conn, ask_fn=lambda prompt: "make it shorter")
    _, tools = t.build_tool_server(ctx)
    out = json.loads(_text(await _call(tools, "ask_user", {"question": "what should change?"})))
    assert out["answer"] == "make it shorter"


@pytest.mark.asyncio
async def test_rewrite_note_tool_rewrites_body(tmp_path, db_conn):
    from datetime import date

    from study_notes.agent import tools as t
    from study_notes.models import Provenance

    ctx = _ctx(tmp_path, db_conn)
    prov = Provenance(
        origin="https://y/x", input_type="youtube", captured_at=date(2026, 7, 26), source_date=None
    )
    path = ctx.writer.write_markdown("Backpressure", "Systems", "# Backpressure\n\nOld.", prov)
    _, tools = t.build_tool_server(ctx)

    out = json.loads(
        _text(
            await _call(
                tools,
                "rewrite_note",
                {"path": path, "markdown": "# Backpressure\n\nNew and clearer."},
            )
        )
    )
    assert out["path"] == path
    assert "New and clearer." in (tmp_path / path).read_text()


@pytest.mark.asyncio
async def test_fetch_webpage_tool_returns_ok_shape(tmp_path, db_conn, monkeypatch):
    # No real browser: monkeypatch webpage.fetch_webpage with an async fake.
    from study_notes.agent import tools as t
    from study_notes.tools.webpage import WebpageResult

    captured = {}

    async def fake_fetch_webpage(url, *, profile_dir, timeout_ms, headless=True, paywall_rules=()):
        captured["paywall_rules"] = paywall_rules
        return WebpageResult(
            url=url, title="Example Title", text="Example body text.", source_date="2025-01-02"
        )

    monkeypatch.setattr(t.webpage, "fetch_webpage", fake_fetch_webpage)
    ctx = _ctx(tmp_path, db_conn)
    _, tools = t.build_tool_server(ctx)
    out = json.loads(_text(await _call(tools, "fetch_webpage", {"url": "https://example.com/a"})))
    assert out == {
        "url": "https://example.com/a",
        "title": "Example Title",
        "text": "Example body text.",
        "source_date": "2025-01-02",
    }
    # the wrapper forwards the configured paywall rules (empty by default here)
    assert captured["paywall_rules"] == ctx.config.paywall.get("rules", [])
