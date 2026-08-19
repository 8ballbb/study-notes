# CLAUDE.md — working notes for this repo

`study-notes`: a personal, local-first CLI that turns YouTube videos, webpages, and local
documents into concise, enriched Markdown study notes in an Obsidian vault. Built on the Claude
Agent SDK as an opus **orchestrator** + cheap parallel **extractor/enricher** subagents, with
in-process tools.

Three input types: **YouTube URL** (yt-dlp captions + local Whisper fallback), **webpage URL**
(Playwright renders the page — headless, using a dedicated login profile at `[browser].profile`
so paywalled/JS-heavy sites work after a one-time `study-notes login <url>` — then `trafilatura`
extracts the article text), and **local file** (read directly: text/Markdown/PDF, pandoc for
`.docx`).

Webpages may also route through a reader/mirror via the `[paywall]` config (`rules` of
`{hosts, via}`) — `webpage.rewrite_for_paywall` fetches matching hosts through the mirror (e.g.
Medium → Freedium) while the note's source stays the ORIGINAL URL. Mirror domains rotate, so the
`via` base is config, never hardcoded.

## Commands

```bash
make setup                                               # one-command setup (plan→confirm→run); or ./scripts/setup.sh
make doctor                                              # read-only env check; make test / make db also exist
uv sync --group dev                                      # (manual install, if not using make setup)
uv run playwright install chromium                       # for webpage ingestion
uv run study-notes add <url|file> [--category C] [--note N] [--dry-run] [--force] [--interactive] [--only DESC]
uv run study-notes query "<question>" [--category C] [--k N]   # read-only: answer from your vault, grounded + cited
uv run study-notes refine <vault-relative-note-path>     # interactively improve an existing note from your feedback
uv run study-notes link                                  # rebuild each note's managed '## Related' wikilink section
uv run study-notes login <url>                            # one-time login for a paywalled site (opens a real browser)
uv run study-notes reindex                               # rebuild search index + category MOCs from disk

uv run pytest -m "not slow and not docker and not e2e"   # fast, TOKEN-FREE suite (~3.5s) — use this
uv run pytest -m docker                                  # frame tests (needs a Docker daemon + jrottenberg/ffmpeg:6.1-alpine)
uv run pytest -m e2e                                     # live agentic ingest — SLOW + SPENDS CLAUDE TOKENS
```

⚠️ **`tests/test_engine_e2e.py` is `e2e`-marked and makes a real agentic run (~2 min, costs tokens).**
It is bundled in the suite unless you exclude it — always add `and not e2e` for routine runs.
**Ask the user before running the full suite or any e2e / real-ingest run.**

## Working preferences (how the user wants Claude Code to operate)
- **Ask before running tests or any long agentic run.** The pytest suite (with the e2e) and any
  real ingest cost time and Claude tokens — make the change, say exactly what you'd verify, then
  ask. Reading files, web research, and non-test shell commands are fine without asking.
- **Check `config.toml` for unset placeholders before any run.** The tracked `config.toml` ships
  with placeholders (currently `vault_path = "REPLACE_ME"`). Before an ingest or any run, verify
  they've been replaced; if `vault_path` is still `REPLACE_ME`, stop, tell the user, and offer to
  update `config.toml` with the real absolute vault path (must be under `$HOME`). Never run against a
  placeholder, and never commit a machine-specific path back.
- **Prefer Docker for services.** Run Postgres/infra in Docker, never a host install — see
  `docker-compose.yml` (pinned images). The user interrupted a host `brew install postgresql` to
  insist on this. (Runtime is any lima-based Docker daemon — see Infra.)
- **Follow the superpowers workflow** for non-trivial changes (see Process below), and **branch
  before implementing** — don't build directly on `master`.
- Prose/notes voice is **Feynman-plain**; keep it (see `prompts/note-writing.md`).

## Infra
- **Docker runtime.** Requirement: *a Docker daemon backed by a Linux VM that bind-mounts `$HOME`*
  (so Postgres/ffmpeg run in containers, not on the host, and container I/O under `$HOME` works). Any
  of these satisfy it on macOS: **Colima**, **Rancher Desktop** (both lima-based, bind-mount `$HOME`
  by default), or Docker Desktop with `$HOME` file-sharing enabled. Postgres 17 + pgvector
  (`docker compose up -d`) and ffmpeg run in containers; the Python app runs on the **host** because
  BGE-M3 and mlx-whisper need Apple **MPS**. Because the VM only bind-mounts `$HOME`, all container
  I/O (ffmpeg, the vault) must stay under home.
- **No API keys** — the agent run rides the user's Claude Code auth.

## Architecture map
- `src/study_notes/cli.py` — CLI entry; dedup gate → `run_ingest`.
- `src/study_notes/agent/` — the engine: `engine.py` (`run_ingest`, `build_options`), `agents.py`
  (extractor/enricher `AgentDefinition`s), `tools.py` (in-process MCP `@tool` wrappers), `context.py`.
- `src/study_notes/tools/` — `youtube.py` (yt-dlp captions + whisper fallback), `webpage.py`
  (Playwright render with a dedicated login profile + `browser_login` → `trafilatura` extraction),
  `frames.py` (Docker ffmpeg download + `select_keyframes`/`keep_frame`), `frame_select.py`
  (numpy/Pillow blur filter + dHash dedup + montage), `vault_write.py` (non-destructive writer +
  OKF frontmatter), `search.py`, `_ytdlp.py`.
- `src/study_notes/` — `config.py`, `models.py`, `renderer.py`, `reindex.py`, `slop_check.py`,
  `vault_index.py` (BGE-M3 + pgvector hybrid retrieval), `ingest.py` (dedup log),
  `query.py` (read-only `query` synthesis), `linker.py` (`link` auto-wikilink pass).
- `prompts/` — `orchestrator.md`, `note-writing.md` (structure **and** the Feynman-plain voice),
  `enrichment.md`, `anti-slop.md`. Editing these is how you change behavior; light content tests
  in `tests/test_agent_prompts.py` guard key phrases.
- `docs/superpowers/{specs,plans}/` — design specs (the *why*) and implementation plans (the *how*).

## Conventions & invariants
- **Vault writes are non-destructive** — new notes never overwrite (`vault_write` refuses to clobber);
  a merge reconciles new material into the existing note's body via `rewrite_note` (frontmatter and
  provenance preserved, no dated append-log).
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

## New machine / resuming (self-checking onboarding)
Claude Code's per-project **auto-memory** (`~/.claude/projects/<path>/memory/`) is machine-local and
does **not** travel with the repo — this `CLAUDE.md`, the `README`, `docs/superpowers/` (design
specs + plans), `scripts/doctor.sh`, and git history are what port. On a fresh clone:

1. Read this file, then `README.md` (setup) and `README-dev.md` (test matrix); skim
   `docs/superpowers/specs/` and `docs/superpowers/plans/` for the design rationale.
2. **Run `./scripts/doctor.sh`** — a read-only check of every prerequisite and service (Homebrew,
   uv, the Docker daemon — any lima-based runtime, Colima or Rancher Desktop — the `study_notes_db`
   Postgres container, the ffmpeg image, the Python deps including Playwright/trafilatura, the
   optional Chromium browser install, and `config.toml`'s `vault_path`, including a check that it
   isn't still the `REPLACE_ME` placeholder). It prints the exact fix for each gap and changes nothing.
3. **For each `[MISS]` item: tell the user what's missing and the suggested fix, and ASK PERMISSION
   before installing or starting anything** (per Working preferences — never install/start infra
   unprompted). Either run the approved fixes yourself, or point them at **`make setup`**
   (`./scripts/setup.sh`) — it prints its plan, asks once, then installs/starts everything missing
   and re-runs the doctor. Re-run the doctor until everything is `[ok]`.
4. Confirm with the token-free suite: `make test` (`uv run pytest -m "not slow and not docker and not e2e and not browser"`).

When you add a new prerequisite or service, **add a matching check to `scripts/doctor.sh`** (and, if
it needs installing/starting, a step in `scripts/setup.sh`) so the
onboarding stays complete. Keep this file and the doctor current — together they are the project's
portable, self-checking memory.
