"""Feature 4: real agentic partial-capture run. Locates a region, confirms via the
interactive handshake (auto-answered), and extracts only that slice to a scoped note.
Marked e2e — SPENDS CLAUDE TOKENS, ~2 min. Vault is sandboxed to tmp_path."""

import asyncio
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


class _AskSpy:
    """Records every confirmation question so the test can prove the locate->confirm
    handshake actually ran — the falsifiable core of partial capture."""

    def __init__(self, answer="yes"):
        self.answer = answer
        self.calls: list[str] = []

    def __call__(self, question: str) -> str:
        self.calls.append(question)
        return self.answer


def test_partial_capture_writes_a_scoped_note(tmp_path, db_conn):
    from study_notes.agent.context import EngineContext
    from study_notes.agent.engine import _SN, _TOOLS, build_interactive_options, run_ingest
    from study_notes.config import load_config
    from study_notes.embedding import FakeEmbedder
    from study_notes.orchestrator import _input_prompt
    from study_notes.tools.vault_write import VaultWriter
    from study_notes.vault_index import VaultIndex

    os.environ.setdefault("MCP_TOOL_TIMEOUT", "3600000")
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = load_config(Path("config.toml"))
    cfg = type(cfg)(**{**cfg.__dict__, "vault_path": vault})  # sandbox the vault
    index = VaultIndex(db_conn, FakeEmbedder())
    ask = _AskSpy("yes")  # auto-confirm the located region and each write, but record calls
    ctx = EngineContext(
        config=cfg,
        index=index,
        writer=VaultWriter(cfg, index),
        ask_fn=ask,
    )

    url = "https://www.youtube.com/watch?v=772CUg2xYAo"
    system_prompt = "\n\n".join(
        [
            Path(cfg.prompts["orchestrator"]).read_text(),
            Path("prompts/interactive-capture.md").read_text(),
            Path("prompts/partial-capture.md").read_text(),
        ]
    )
    opts = build_interactive_options(
        ctx,
        system_prompt=system_prompt,
        allowed=[*_TOOLS, f"{_SN}ask_user"],
        approve_tools=[f"{_SN}vault_write"],
    )
    prompt = _input_prompt(url, "youtube", None, None, False, only="the opening section")
    out = asyncio.run(run_ingest(ctx, prompt, options=opts))

    # Falsifiable: --only must drive a locate->confirm handshake, so ask_user (routed to
    # our spy) MUST have been called. If --only were ignored the model would ingest the
    # whole source without ever asking us to confirm a region, and this fails.
    assert ask.calls, (
        "the locate->confirm handshake never called ask_user — --only was likely "
        f"ignored and the whole source ingested.\nrun output:\n{out}"
    )
    # Region capture yields a single scoped note, not a full-video multi-topic decomposition.
    notes = [p for p in (vault / cfg.notes_root).rglob("*.md") if p.stem != p.parent.name]
    assert len(notes) == 1, (
        f"partial capture should write exactly one scoped note, got {len(notes)}: "
        f"{[p.name for p in notes]}\nrun output:\n{out}"
    )
