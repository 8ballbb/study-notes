"""Feature 4: real agentic partial-capture run. Locates a region, confirms via the
interactive handshake (auto-answered), and extracts only that slice to a scoped note.
Marked e2e — SPENDS CLAUDE TOKENS, ~2 min. Vault is sandboxed to tmp_path."""

import asyncio
import os
from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


def test_partial_capture_writes_a_scoped_note(tmp_path, db_conn):
    from study_notes.agent.context import EngineContext
    from study_notes.agent.engine import _SN, _TOOLS, build_interactive_options, run_ingest
    from study_notes.config import load_config
    from study_notes.embedding import FakeEmbedder
    from study_notes.orchestrator import _input_prompt
    from study_notes.tools.vault_write import VaultWriter
    from study_notes.vault_index import VaultIndex

    os.environ.setdefault("MCP_TOOL_TIMEOUT", "3600000")
    # Self-contained config: the repo config with the vault_path placeholder filled in
    # and pointed at a sandbox, so the e2e doesn't depend on this machine's config.toml.
    vault = tmp_path / "vault"
    vault.mkdir()
    raw = (
        Path("config.toml")
        .read_text()
        .replace('vault_path = "REPLACE_ME"', f'vault_path = "{vault}"')
    )
    assert "REPLACE_ME" not in raw, "config.toml placeholder line changed; update this test"
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(raw)
    cfg = load_config(cfg_path)
    index = VaultIndex(db_conn, FakeEmbedder())
    ctx = EngineContext(
        config=cfg,
        index=index,
        writer=VaultWriter(cfg, index),
        ask_fn=lambda _q: "yes",  # auto-confirm the located region and each write
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

    # Smoke test: proves the interactive locate->confirm->extract pipeline runs end to
    # end and writes a note. It does not assert the note is *scoped* to the requested
    # region (hard to verify without pinning the video's content).
    notes = [p for p in (vault / cfg.notes_root).rglob("*.md") if p.stem != p.parent.name]
    assert notes, f"no scoped note was written; run output:\n{out}"
