import argparse
import json
import sys
import tempfile
from pathlib import Path

from study_notes.claude_runner import build_command, mcp_config_dict, run
from study_notes.config import Config, load_config
from study_notes.orchestrator import add


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


def build_system_prompt(config: Config, dry_run: bool) -> str:
    procedure = Path(config.prompts["procedure"]).read_text()
    anti_slop = Path(config.prompts["anti_slop"]).read_text()
    return f"{procedure}\n\n{anti_slop}"


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
    ingest_log = IngestLog(index.conn)

    def run_claude(payload) -> str:
        prompt, system_prompt, dry_run = payload
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(mcp_config_dict(str(Path(ns.config).resolve())), f)
            mcp_path = f.name
        cmd = build_command(
            input_prompt=prompt, model=config.agent_model, system_prompt=system_prompt,
            mcp_config_path=mcp_path, add_dirs=[str(config.vault_path)], dry_run=dry_run,
        )
        return run(cmd)

    res = add(ns.input, config=config, index=index, ingest_log=ingest_log,
              run_claude=run_claude,
              build_system_prompt=lambda dry: build_system_prompt(config, dry),
              category=ns.category, note=ns.note, dry_run=ns.dry_run, force=ns.force)
    print(res.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
