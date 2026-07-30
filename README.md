# Study Notes

Turn educational YouTube videos (and documents) into concise, well-written study notes in your own [Obsidian](https://obsidian.md) vault — enriched with cited web research, organised into categories, and searchable.

It's a personal, **local-first** command-line tool: your notes are plain Markdown you own, not rows in someone else's SaaS. Give it a link, and a few minutes later you have study-ready notes that are often *better than the source*.

```bash
uv run study-notes add https://www.youtube.com/watch?v=<id>
```

---

## What it does

Point it at a source and it will:

- **Fetch the transcript** (YouTube captions, with a local **Whisper** fallback for caption-less videos) or read the document directly.
- **Split it into distinct topics** — one long video can become several focused notes.
- **Write each note in whatever structure fits the content** — an explanation, a comparison table, a step-by-step, a worked example, a decision guide — composed as the material warrants, not forced into flashcards, in a plain, teaching **Feynman-plain voice** (with an anti-slop checker that flags AI-filler phrasing).
- **Research each topic online** and fold in authoritative context, corrections, and examples the source skipped, with a **source URL on every external claim** (gathered under a `## Citations` section).
- **Decide where each note belongs** — reuse an existing category or create a new one — and write it **non-destructively** (never overwrites; merges append a dated section).
- **Pull the frames that actually help** — for visual moments a note references, it selects candidate frames locally (scene-dedup + blur filter + perceptual de-duplication, keeping the *settled* frame of an animation), then *reads* them and embeds only the few that add something the text can't, transcribing their on-screen content into the note so it stands alone.
- **Remember what it has ingested**, so re-adding the same URL/file is skipped.

Everything lands as Markdown in your vault, indexed for semantic search.

## How it works

A single agentic run, structured as an **orchestrator with workers**:

```
study-notes add <url>
  │  (Python: dedup check → skip if already ingested)
  ▼
opus ORCHESTRATOR   reads & decomposes the source, decides categories/placement,
  │                 integrates results, screens for slop, writes, verifies
  ├─▶ extractor subagents  (parallel, cheaper model) — write one note per topic
  └─▶ enricher subagents   (parallel) — web research with cited sources
  │
  ▼  (Python: record what was written)
notes in your Obsidian vault
```

The orchestrator keeps a lean context and delegates the bulky per-topic work to workers that each run in an isolated context and in parallel — so a multi-topic source doesn't crawl through one giant sequential run. It's built on the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/python); the tools it calls (transcript fetch, vault search, frame extraction, note writing) run **in-process**.

## Requirements

- **macOS on Apple Silicon** (the BGE-M3 embedding model uses Apple's MPS/GPU).
- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/).
- **[Claude Code](https://claude.com/claude-code)**, installed and authenticated — the agent run rides that auth (no API key needed).
- **Docker** (via [Colima](https://github.com/abiosoft/colima) — no Docker Desktop required) for PostgreSQL + `pgvector` and for `ffmpeg`.

## Setup

```bash
# 1. Docker runtime + the database (Postgres 17 + pgvector)
brew install colima docker docker-compose
colima start
docker compose up -d                 # starts the study_notes database
docker pull jrottenberg/ffmpeg:6.1-alpine   # for frame extraction

# 2. The tool
uv venv && uv pip install -e ".[dev]"

# 3. Point config.toml at your vault (a folder under your home directory)
#    vault_path = "/Users/you/vault"
```

The database schema is created automatically on first run — no manual step.

In Obsidian, install the community **Spaced Repetition** plugin if you want to review the cards a note may contain (enable FSRS in its settings).

## Usage

```bash
# Ingest a YouTube video (auto-categorised)
uv run study-notes add https://www.youtube.com/watch?v=<id>

# Force a category, or merge into a specific note
uv run study-notes add paper.pdf --category "Machine Learning"
uv run study-notes add https://youtu.be/<id> --note "Existing Note Title"

# Preview the plan without writing anything
uv run study-notes add https://youtu.be/<id> --dry-run

# Re-ingest something already seen
uv run study-notes add https://youtu.be/<id> --force

# Rebuild the search index from the current vault
uv run study-notes reindex
```

## Configuration

`config.toml` at the repo root:

```toml
vault_path = "/Users/you/vault"
notes_root = "Notes"                   # categories are folders under here
attachments_dir = "Attachments"
frames_subdir = "frames"

[database]
url = "postgresql://postgres:postgres@localhost:5432/study_notes"

[embedding]
model = "BAAI/bge-m3"                   # local, dense + sparse, on MPS

[models]                               # per-role model selection
orchestrator = "claude-opus-4-8"       # decompose / judge / integrate
extractor    = "claude-sonnet-5"       # per-topic note writing
enricher     = "claude-sonnet-5"       # per-topic web research

[prompts]                              # versioned, editable
orchestrator = "prompts/orchestrator.md"
note_writing = "prompts/note-writing.md"   # how notes are written — tune "how I learn" (and the voice) here
enrichment   = "prompts/enrichment.md"
anti_slop    = "prompts/anti-slop.md"       # bans AI-filler phrasing

[frames]
budget = 4                             # candidate frames per visual moment (montage the model picks from)
enabled = true                         # frame extraction on/off

[whisper]
model = "mlx-community/whisper-small"   # local, key-free fallback for caption-less videos (Apple MPS)

[run]
dry_run = false
```

The **`prompts/note-writing.md`** guide is the single place to tune how notes read — it's a plain file you can edit.

## Vault layout

The tool owns a simple, PARA-informed structure. Categories are folders, each with a Map-of-Content index note; study notes live inside them; frames go in the attachments folder.

```
<vault>/
  Notes/
    <Category>/
      <Category>.md        # category index (MOC) — links every note in the category
      <Note>.md            # a study note (Markdown + frontmatter)
  Attachments/
    frames/
      <video_id>/          # kept frames, grouped per source video (easy to clean up)
```

Every note carries **[OKF](https://cloud.google.com/blog/products/data-analytics/how-the-open-knowledge-format-can-improve-data-sharing)-aligned** frontmatter — Google Cloud's Open Knowledge Format conventions: a required `type`, plus `resource` (the source URI), `timestamp`, `description`, and `tags`, alongside project fields (`category`, `source_type`, `source_date`) — so a note's origin, and any future updates, stay traceable and portable. `study-notes reindex` resyncs both the search index **and** the category index notes from what's actually on disk, so it doubles as a "clean up the vault" command if you've moved, renamed, or deleted notes in Obsidian.

## Architecture

- **Retrieval** — [BGE-M3](https://huggingface.co/BAAI/bge-m3) embeddings + PostgreSQL/`pgvector` do **category-scoped hybrid search** (dense + full-text, fused with Reciprocal Rank Fusion). A search never crosses categories.
- **Tools** — transcript fetch (`yt-dlp`, + local `mlx-whisper` fallback), frame candidate selection (`ffmpeg` in a container) with local refinement (`numpy`/`Pillow`: blur filter, perceptual dedup, contact-sheet montage), non-destructive vault writes, hybrid search, and an anti-slop linter — all exposed to the agents as in-process functions.
- **Runtime** — the Python app runs on the host (BGE-M3 and Whisper need Apple's GPU); only Postgres and ffmpeg are containerised.
- **Isolation** — the agent subprocess runs with `setting_sources=[]` + `strict_mcp_config=True`, so it does **not** inherit your host `~/.claude` settings/hooks/MCP servers; each ingest sees only this tool's prompt, agents, and in-process tools.

The design and build history live under [`docs/superpowers/`](docs/superpowers/) — specs describe the *why*, plans the *how*, built test-first with review at each step.

## Development

```bash
uv run pytest -m "not slow and not docker and not e2e"   # fast, token-free suite (~3.5s)
uv run pytest -m docker                                   # frame tests (needs Colima + ffmpeg image)
uv run pytest -m e2e                                      # real end-to-end agentic run — SPENDS Claude tokens
```

> **Note:** the `e2e` test drives a real agentic ingest (~2 min, costs tokens), so the default suite excludes it — run the token-free command above unless you specifically want the live end-to-end check.

See [`README-dev.md`](README-dev.md) for the full test matrix and the Docker/Colima details.

## Roadmap

Deliberately deferred, not blocking:

- Temporal conflict handling (detecting when new material updates or contradicts an existing note).
- BGE-M3 learned-sparse vectors for stronger lexical retrieval.
- An optional OKF *export* (converting the vault into a fully-conformant OKF bundle for other agents/tools).

Recently shipped: local Whisper fallback for caption-less videos; targeted, montage-based frame selection with per-video storage; OKF-aligned note frontmatter; a Feynman-plain writing voice.
