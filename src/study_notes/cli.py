import argparse
import asyncio
import os
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
    a.add_argument(
        "--interactive",
        action="store_true",
        help="plan with you first: ask questions and confirm each note before writing",
    )
    a.add_argument(
        "--only",
        metavar="DESCRIPTION",
        help="capture only the part matching this description, e.g. 'the section on backpressure'; "
        "locates it, shows you the range, and confirms before extracting (implies --interactive)",
    )

    r = sub.add_parser("refine", help="interactively improve an existing note from your feedback")
    r.add_argument("path", help="vault-relative path of the note, e.g. 'Notes/API Design/Foo.md'")

    q = sub.add_parser("query", help="ask a question answered from your vault notes")
    q.add_argument("question")
    q.add_argument("--category", help="scope to one category (default: search all categories)")
    q.add_argument("--k", type=int, default=5, help="how many notes to retrieve")

    sub.add_parser("reindex", help="rebuild the index from the vault")

    sub.add_parser(
        "link", help="rebuild each note's related-links (a managed '## Related' section) vault-wide"
    )

    login_p = sub.add_parser("login", help="log into a site for later paywalled fetches")
    login_p.add_argument("url", nargs="?")
    ns = p.parse_args(argv)
    if getattr(ns, "only", None) and getattr(ns, "dry_run", False):
        p.error(
            "--only cannot be combined with --dry-run (--only locates, confirms, and writes a slice)"
        )
    return ns


def _make_index(config: Config):
    from study_notes.db import connect_and_prepare
    from study_notes.embedding import BGEM3Embedder
    from study_notes.vault_index import VaultIndex

    return VaultIndex(
        connect_and_prepare(config.database_url), BGEM3Embedder(config.embedding_model)
    )


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    config = load_config(Path(ns.config))

    if ns.command == "reindex":
        from study_notes.reindex import reindex

        n = reindex(config, _make_index(config))
        print(f"reindexed {n} note(s)")
        return 0

    if ns.command == "link":
        from study_notes.linker import run_link

        notes_linked, total_links = run_link(config, _make_index(config))
        print(f"linked {notes_linked} note(s) ({total_links} related-link(s))")
        return 0

    if ns.command == "query":
        from study_notes.query import answer_question

        answer = answer_question(
            config, _make_index(config), ns.question, category=ns.category, k=ns.k
        )
        print(answer)
        return 0

    if ns.command == "login":
        from study_notes.tools.webpage import browser_login

        profile_dir = os.path.expanduser(config.browser["profile"])
        browser_login(profile_dir, ns.url)
        print("Session saved.")
        return 0

    if ns.command == "refine":
        abs_note = (config.vault_path / ns.path).resolve()
        if not (abs_note.is_file() and abs_note.is_relative_to(config.vault_path.resolve())):
            print(f"error: note not found under the vault: {ns.path}", file=sys.stderr)
            return 1
        from study_notes.agent.engine import _SN, build_interactive_options

        os.environ.setdefault("MCP_TOOL_TIMEOUT", "3600000")  # ms; allow long human approval waits
        index = _make_index(config)
        ctx = EngineContext(
            config=config, index=index, writer=VaultWriter(config, index), ask_fn=input
        )
        system_prompt = (
            Path(config.prompts["refine"]).read_text()
            + "\n\n"
            + Path(config.prompts["anti_slop"]).read_text()
        )
        opening = (
            f"Refine this note. Its vault path is: {ns.path}\n\n"
            f"--- CURRENT NOTE ---\n{abs_note.read_text()}\n--- END CURRENT NOTE ---\n\n"
            "Ask me what I want improved, propose your changes, and rewrite it once I agree."
        )
        opts = build_interactive_options(
            ctx,
            system_prompt=system_prompt,
            allowed=[
                f"{_SN}rewrite_note",
                f"{_SN}ask_user",
                f"{_SN}vault_search",
                f"{_SN}check_slop",
                f"{_SN}list_categories",
            ],
            approve_tools=[f"{_SN}rewrite_note"],
        )
        asyncio.run(run_ingest(ctx, opening, options=opts))
        print("Done.")
        return 0

    from study_notes.ingest import IngestLog

    index = _make_index(config)
    ctx = EngineContext(config=config, index=index, writer=VaultWriter(config, index))
    ingest_log = IngestLog(index.conn)

    def run_engine(prompt: str) -> str:
        if ns.interactive or ns.only:
            from study_notes.agent.engine import _SN, _TOOLS, build_interactive_options

            os.environ.setdefault("MCP_TOOL_TIMEOUT", "3600000")
            ctx.ask_fn = input
            parts = [
                Path(config.prompts["orchestrator"]).read_text(),
                Path(config.prompts["interactive_capture"]).read_text(),
            ]
            if ns.only:
                parts.append(Path(config.prompts["partial_capture"]).read_text())
            system_prompt = "\n\n".join(parts)
            opts = build_interactive_options(
                ctx,
                system_prompt=system_prompt,
                allowed=[*_TOOLS, f"{_SN}ask_user"],
                approve_tools=[f"{_SN}vault_write", f"{_SN}rewrite_note"],
            )
            return asyncio.run(run_ingest(ctx, prompt, options=opts))
        return asyncio.run(run_ingest(ctx, prompt))

    try:
        res = add(
            ns.input,
            config=config,
            index=index,
            ingest_log=ingest_log,
            run_engine=run_engine,
            category=ns.category,
            note=ns.note,
            dry_run=ns.dry_run,
            force=ns.force,
            only=ns.only,
        )
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(res.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
