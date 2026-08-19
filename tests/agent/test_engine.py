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
    cfg = Config(
        vault_path=tmp_path,
        notes_root="Notes",
        attachments_dir="Attachments",
        frames_subdir="frames",
        database_url="unused",
        embedding_model="fake",
        models={"orchestrator": "opus", "extractor": "sonnet", "enricher": "haiku"},
        prompts={
            "orchestrator": str(tmp_path / "orchestrator.md"),
            "note_writing": str(tmp_path / "note_writing.md"),
            "enrichment": str(tmp_path / "enrichment.md"),
            "anti_slop": str(tmp_path / "anti_slop.md"),
        },
        dry_run=False,
    )
    index = VaultIndex(db_conn, FakeEmbedder())
    return EngineContext(config=cfg, index=index, writer=VaultWriter(cfg, index))


@pytest.mark.asyncio
async def test_approval_hook_allows_on_yes_denies_on_no(tmp_path, db_conn):
    from study_notes.agent import engine

    ctx = _ctx(tmp_path, db_conn)
    answers = iter(["no thanks", "yes"])
    ctx.ask_fn = lambda prompt: next(answers)
    hook = engine._approval_hook(ctx)

    deny = await hook({"tool_input": {"title": "T", "markdown": "body"}}, "id", None)
    allow = await hook({"tool_input": {"title": "T", "markdown": "body"}}, "id", None)

    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "no thanks" in deny["hookSpecificOutput"]["permissionDecisionReason"]
    assert allow["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_build_interactive_options_wires_ask_user_and_approval_hook(tmp_path, db_conn):
    from study_notes.agent import engine

    ctx = _ctx(tmp_path, db_conn)
    opts = engine.build_interactive_options(
        ctx,
        system_prompt="hi",
        allowed=[f"{engine._SN}vault_write", f"{engine._SN}ask_user"],
        approve_tools=[f"{engine._SN}vault_write"],
    )

    assert f"{engine._SN}ask_user" in opts.allowed_tools
    assert opts.permission_mode == "bypassPermissions"  # hook gates under bypass
    matchers = opts.hooks["PreToolUse"]
    assert matchers[0].matcher == f"{engine._SN}vault_write"
    assert matchers[0].timeout == 3600  # long human-wait allowance
    # SDK-isolation invariant (CLAUDE.md: "Do NOT remove these") must survive the interactive path
    assert opts.setting_sources == []
    assert opts.strict_mcp_config is True


@pytest.mark.asyncio
async def test_approval_hook_denies_on_empty_and_eof(tmp_path, db_conn):
    from study_notes.agent import engine

    ctx = _ctx(tmp_path, db_conn)
    ti = {"tool_input": {"title": "T", "markdown": "body"}}

    ctx.ask_fn = lambda prompt: ""  # empty answer -> deny
    empty = await engine._approval_hook(ctx)(ti, "id", None)
    assert empty["hookSpecificOutput"]["permissionDecision"] == "deny"

    def _eof(prompt):
        raise EOFError

    ctx.ask_fn = _eof  # closed/non-tty stdin -> fail closed (deny), no crash
    eof = await engine._approval_hook(ctx)(ti, "id", None)
    assert eof["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_build_options_wires_models_agents_tools(tmp_path, db_conn):
    from study_notes.agent.engine import build_options

    opts = build_options(_ctx(tmp_path, db_conn))
    assert opts.model == "opus"
    assert set(opts.agents) == {"extractor", "enricher"}
    assert "study-notes" in opts.mcp_servers
    assert "mcp__study-notes__vault_write" in opts.allowed_tools
    assert "WebSearch" in opts.allowed_tools
    assert opts.permission_mode == "bypassPermissions"
    assert "mcp__study-notes__prepare_video" in opts.allowed_tools
    assert "mcp__study-notes__keep_frame" in opts.allowed_tools
    assert "Read" in opts.allowed_tools
    assert "mcp__study-notes__extract_frame" not in opts.allowed_tools
    # reconcile-on-merge: the add path can rewrite an existing note in place
    assert "mcp__study-notes__rewrite_note" in opts.allowed_tools


@pytest.mark.asyncio
async def test_run_ingest_raises_on_error_result(tmp_path, db_conn, monkeypatch):
    from claude_agent_sdk import ResultMessage

    from study_notes.agent import engine
    from study_notes.agent.engine import EngineError, run_ingest

    async def fake_query(*, prompt, options):
        yield ResultMessage(
            subtype="error_max_turns",
            duration_ms=1,
            duration_api_ms=1,
            is_error=True,
            num_turns=1,
            session_id="s",
            result="boom",
        )

    monkeypatch.setattr(engine, "query", fake_query)
    with pytest.raises(EngineError):
        await run_ingest(_ctx(tmp_path, db_conn), "go")


@pytest.mark.asyncio
async def test_run_ingest_returns_text_on_success(tmp_path, db_conn, monkeypatch):
    from claude_agent_sdk import ResultMessage

    from study_notes.agent import engine
    from study_notes.agent.engine import run_ingest

    async def fake_query(*, prompt, options):
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            result="the plan",
        )

    monkeypatch.setattr(engine, "query", fake_query)
    out = await run_ingest(_ctx(tmp_path, db_conn), "go")
    assert out == "the plan"


@pytest.mark.asyncio
async def test_run_ingest_consumes_full_stream_not_first_result(tmp_path, db_conn, monkeypatch):
    # A `result` frame ends one TURN, not the run. run_ingest must NOT stop at the
    # first result (the orchestrator's "waiting on subagents" turn-end) — it must
    # keep consuming and return the FINAL result.
    from claude_agent_sdk import ResultMessage

    from study_notes.agent import engine
    from study_notes.agent.engine import run_ingest

    def _res(text):
        return ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            result=text,
        )

    async def fake_query(*, prompt, options):
        yield _res("waiting on subagents")  # first turn-end
        yield _res("final integrated plan")  # run truly done

    monkeypatch.setattr(engine, "query", fake_query)
    out = await run_ingest(_ctx(tmp_path, db_conn), "go")
    assert out == "final integrated plan"


@pytest.mark.asyncio
async def test_run_ingest_swallows_spurious_success_teardown(tmp_path, db_conn, monkeypatch):
    # The SDK occasionally raises a ProcessError at teardown with stderr
    # "error: Claude Code returned an error result: success" AFTER a terminal
    # success ResultMessage has already been observed. run_ingest must treat
    # that specific case as success, since the work substantively completed.
    from claude_agent_sdk import ProcessError, ResultMessage

    from study_notes.agent import engine
    from study_notes.agent.engine import run_ingest

    async def fake_query(*, prompt, options):
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            result="done ok",
        )
        raise ProcessError(
            "Claude Code returned an error result: success",
            exit_code=1,
            stderr="error: Claude Code returned an error result: success",
        )

    monkeypatch.setattr(engine, "query", fake_query)
    out = await run_ingest(_ctx(tmp_path, db_conn), "go")
    assert out == "done ok"


@pytest.mark.asyncio
async def test_run_ingest_reraises_process_error_without_prior_success(
    tmp_path,
    db_conn,
    monkeypatch,
):
    # If NO successful ResultMessage has been observed, even a "success"-shaped
    # ProcessError is a genuine failure — do not swallow it.
    from claude_agent_sdk import ProcessError

    from study_notes.agent import engine
    from study_notes.agent.engine import run_ingest

    async def fake_query(*, prompt, options):
        raise ProcessError(
            "boom", exit_code=1, stderr="error: Claude Code returned an error result: success"
        )
        yield  # pragma: no cover — makes this an async generator

    monkeypatch.setattr(engine, "query", fake_query)
    with pytest.raises(ProcessError):
        await run_ingest(_ctx(tmp_path, db_conn), "go")


@pytest.mark.asyncio
async def test_run_ingest_reraises_unrelated_process_error(tmp_path, db_conn, monkeypatch):
    # A ProcessError that does NOT match the spurious-teardown pattern must
    # propagate even if a success ResultMessage was already seen.
    from claude_agent_sdk import ProcessError, ResultMessage

    from study_notes.agent import engine
    from study_notes.agent.engine import run_ingest

    async def fake_query(*, prompt, options):
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            result="ok",
        )
        raise ProcessError("cli crashed", exit_code=137, stderr="Killed: 9")

    monkeypatch.setattr(engine, "query", fake_query)
    with pytest.raises(ProcessError):
        await run_ingest(_ctx(tmp_path, db_conn), "go")


@pytest.mark.asyncio
async def test_run_ingest_clears_frame_work_scratch(tmp_path, db_conn, monkeypatch):
    from claude_agent_sdk import ResultMessage

    from study_notes.agent import engine
    from study_notes.agent.engine import run_ingest

    async def fake_query(*, prompt, options):
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            result="done",
        )

    monkeypatch.setattr(engine, "query", fake_query)
    ctx = _ctx(tmp_path, db_conn)
    work = tmp_path / "Attachments" / "frames" / "_work"
    (work / "cands_x").mkdir(parents=True)
    (work / "video.mp4").write_text("scratch")
    await run_ingest(ctx, "go")
    assert not work.exists()
