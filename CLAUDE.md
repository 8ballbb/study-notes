# CLAUDE.md — working notes for this repo

`study-notes`: a personal, local-first CLI that turns YouTube videos / documents into concise,
enriched Markdown study notes in an Obsidian vault. Built on the Claude Agent SDK as an
opus **orchestrator** + cheap parallel **extractor/enricher** subagents, with in-process tools.

## Commands

```bash
uv pip install -e ".[dev]"                               # install
uv run study-notes add <url|file> [--category C] [--note N] [--dry-run] [--force]
uv run study-notes reindex                               # rebuild search index + category MOCs from disk

uv run pytest -m "not slow and not docker and not e2e"   # fast, TOKEN-FREE suite (~3.5s) — use this
uv run pytest -m docker                                  # frame tests (needs Colima + jrottenberg/ffmpeg:6.1-alpine)
uv run pytest -m e2e                                     # live agentic ingest — SLOW + SPENDS CLAUDE TOKENS
```

⚠️ **`tests/test_engine_e2e.py` is `e2e`-marked and makes a real agentic run (~2 min, costs tokens).**
It is bundled in the suite unless you exclude it — always add `and not e2e` for routine runs.
**Ask the user before running the full suite or any e2e / real-ingest run.**

## Infra
- **Docker via Colima** (not Docker Desktop). Postgres 17 + pgvector (`docker compose up -d`) and
  ffmpeg run in containers; the Python app runs on the **host** because BGE-M3 and mlx-whisper need
  Apple **MPS**. Colima only bind-mounts under `$HOME`, so ffmpeg I/O must stay under home.
- **No API keys** — the agent run rides the user's Claude Code auth.

## Architecture map
- `src/study_notes/cli.py` — CLI entry; dedup gate → `run_ingest`.
- `src/study_notes/agent/` — the engine: `engine.py` (`run_ingest`, `build_options`), `agents.py`
  (extractor/enricher `AgentDefinition`s), `tools.py` (in-process MCP `@tool` wrappers), `context.py`.
- `src/study_notes/tools/` — `youtube.py` (yt-dlp captions + whisper fallback), `frames.py`
  (Docker ffmpeg download + `select_keyframes`/`keep_frame`), `frame_select.py` (numpy/Pillow blur
  filter + dHash dedup + montage), `vault_write.py` (non-destructive writer + OKF frontmatter),
  `search.py`, `_ytdlp.py`.
- `src/study_notes/` — `config.py`, `models.py`, `renderer.py`, `reindex.py`, `slop_check.py`,
  `vault_index.py` (BGE-M3 + pgvector hybrid retrieval), `ingest.py` (dedup log).
- `prompts/` — `orchestrator.md`, `note-writing.md` (structure **and** the Feynman-plain voice),
  `enrichment.md`, `anti-slop.md`. Editing these is how you change behavior; light content tests
  in `tests/test_agent_prompts.py` guard key phrases.
- `docs/superpowers/{specs,plans}/` — design specs (the *why*) and implementation plans (the *how*).

## Conventions & invariants
- **Vault writes are non-destructive** — new notes never overwrite; merges append a dated section.
- **Frames are best-effort** — any frame step may fail; the note is still written from the transcript.
- **Note frontmatter is OKF-aligned and deterministic** — `write_markdown` prepends a canonical block
  (`type`/`resource`/`timestamp`/`description`/`tags` + `category`/`source_type`/`source_date`);
  do not rely on the model to emit frontmatter. `reindex` reads OKF names with pre-OKF fallback.
- **SDK isolation** — `build_options` sets `setting_sources=[]` + `strict_mcp_config=True`. Do NOT
  remove these: without them the subprocess inherits the host `~/.claude` (hooks, MCP servers,
  background-task tooling) and multi-topic runs bail out early.
- **Stream consumption** — `run_ingest` must consume the full `query()` stream (no early `break`); a
  `result` frame ends one turn, not the run, while subagents are still in flight.
- **Prose** — Feynman-plain voice; `slop_check` is a soft backstop (cliché/em-dash/hedging rules),
  not a hard gate.

## Process
This project is built with the **superpowers** workflow: brainstorm → spec → plan → subagent-driven
implementation (TDD, per-task review, final whole-branch review) → finish. Follow it for non-trivial
changes; keep specs/plans under `docs/superpowers/`.
