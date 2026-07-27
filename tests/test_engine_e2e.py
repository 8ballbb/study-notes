import asyncio

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


def test_dry_run_ingest_produces_a_plan(tmp_path, db_conn):
    from study_notes.agent.context import EngineContext
    from study_notes.agent.engine import run_ingest
    from study_notes.config import load_config
    from study_notes.embedding import BGEM3Embedder
    from study_notes.tools.vault_write import VaultWriter
    from study_notes.vault_index import VaultIndex
    from pathlib import Path

    cfg = load_config(Path("config.toml"))
    cfg = type(cfg)(**{**cfg.__dict__, "vault_path": tmp_path})  # sandbox the vault
    index = VaultIndex(db_conn, BGEM3Embedder(cfg.embedding_model))
    ctx = EngineContext(config=cfg, index=index, writer=VaultWriter(cfg, index))
    prompt = ("Ingest this youtube source. Source: https://www.youtube.com/watch?v=772CUg2xYAo "
              "Use exactly this string as the note source: "
              "https://www.youtube.com/watch?v=772CUg2xYAo. This is a DRY RUN: do not call "
              "vault_write; report your plan.")
    out = asyncio.run(run_ingest(ctx, prompt))
    assert out and len(out) > 50  # produced a plan
