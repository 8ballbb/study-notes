import argparse
import asyncio
import sys
from pathlib import Path

from study_notes.agent.context import EngineContext
from study_notes.agent.engine import run_ingest
from study_notes.config import Config, load_config
from study_notes.orchestrator import add
from study_notes.tools.vault_write import VaultWriter


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="study-notes")
    p.add_argument("--config", default="config.toml")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="ingest one source")
    a.add_argument("input")
    a.add_argument("--category")
    a.add_argument("--note")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--force", action="store_true")

    sub.add_parser("reindex", help="rebuild the index from the vault")
    return p.parse_args(argv)


def _make_index(config: Config):
    from study_notes.db import connect
    from study_notes.embedding import BGEM3Embedder
    from study_notes.vault_index import VaultIndex

    return VaultIndex(connect(config.database_url), BGEM3Embedder(config.embedding_model))


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    config = load_config(Path(ns.config))

    if ns.command == "reindex":
        from study_notes.reindex import reindex
        n = reindex(config, _make_index(config))
        print(f"reindexed {n} note(s)")
        return 0

    from study_notes.ingest import IngestLog
    index = _make_index(config)
    ctx = EngineContext(config=config, index=index, writer=VaultWriter(config, index))
    ingest_log = IngestLog(index.conn)

    def run_engine(prompt: str) -> str:
        return asyncio.run(run_ingest(ctx, prompt))

    try:
        res = add(ns.input, config=config, index=index, ingest_log=ingest_log,
                  run_engine=run_engine,
                  category=ns.category, note=ns.note, dry_run=ns.dry_run, force=ns.force)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(res.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
