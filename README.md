<div align="center">

# 📚 Study Notes

**Turn educational YouTube videos, webpages & documents into concise, enriched study notes in your own [Obsidian](https://obsidian.md) vault.**

Local-first · agentic · plain Markdown you own — not rows in someone else's SaaS.<br>
Give it a link, and a few minutes later you have study-ready notes that are often *better than the source*.

<p>
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Built%20with-Claude%20Agent%20SDK-D97757?style=flat-square&logo=anthropic&logoColor=white" alt="Built with Claude Agent SDK">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-000000?style=flat-square&logo=apple&logoColor=white" alt="macOS · Apple Silicon">
  <img src="https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL + pgvector">
  <img src="https://img.shields.io/badge/Local--first-100%25-16A34A?style=flat-square" alt="Local-first">
</p>

</div>

```bash
uv run study-notes add https://www.youtube.com/watch?v=<id>
```

---

## What it does

Point it at a source and it will:

- **Fetch the source** — YouTube captions (with a local **Whisper** fallback for caption-less videos), a webpage (rendered with **Playwright**, including JS-heavy and paywalled pages behind a one-time login, then extracted with **trafilatura**), or a local document read directly.
- **Split it into distinct topics** — one long video can become several focused notes.
- **Write each note in whatever structure fits the content** — an explanation, a comparison table, a step-by-step, a worked example, a decision guide — composed as the material warrants, not forced into flashcards, in a plain, teaching **Feynman-plain voice** (with an anti-slop checker that flags AI-filler phrasing).
- **Research each topic online** and fold in authoritative context, corrections, and examples the source skipped, with a **source URL on every external claim** (gathered under a `## Citations` section).
- **Decide where each note belongs** — reuse an existing category or create a new one — and write it **non-destructively** (never overwrites; merges append a dated section).
- **Pull the frames that actually help** — for visual moments a note references, it selects candidate frames locally (scene-dedup + blur filter + perceptual de-duplication, keeping the *settled* frame of an animation), then *reads* them and embeds only the few that add something the text can't, transcribing their on-screen content into the note so it stands alone.
- **Remember what it has ingested**, so re-adding the same URL/file is skipped.

Everything lands as Markdown in your vault, indexed for semantic search.

## How it works

A single agentic run, structured as an **orchestrator with workers**. The orchestrator keeps a lean context and delegates the bulky per-topic work to workers that each run in an isolated context and in parallel, so a multi-topic source doesn't crawl through one long sequential run. It's built on the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/python); the tools it calls (transcript fetch, vault search, frame extraction, note writing) run **in-process**.

The pipeline runs in four stages.

### 1. Ingest and route

![Ingest and route](docs/architecture-1-ingest.svg)

`study-notes add` is the front door. A dedup gate (the ingest log) drops anything already captured, then the input is routed by type to one of three fetchers: `yt-dlp` captions with a local Whisper fallback for YouTube, a Playwright render into `trafilatura` for webpages, or a direct read for local files. Each returns clean text; YouTube also returns timed segments and chapters.

### 2. Decompose, place, and dispatch

![Decompose, place, and dispatch](docs/architecture-2-decompose.svg)

The orchestrator reads the source once and splits it into distinct topics (using chapters or headings as anchors), each with a title, scope, and source slice. For every topic it checks the existing categories and searches the vault to choose between a new note and a dated merge, decides whether the source is visual enough to pull frames (preparing one downscaled video if so), then dispatches the topics to run in parallel.

### 3. The two workers

![Extractor and enricher workers](docs/architecture-3-workers.svg)

Each topic runs two workers in isolated contexts. The **extractor** drafts the note from its slice in a Feynman-plain voice, self-screens with `check_slop`, and for visual sources pulls frames: it finds visual-cue moments, calls `select_keyframes` (ffmpeg samples candidates, then a local blur filter and perceptual dedup lay them out as a contact sheet), picks the useful ones, and calls `keep_frame`. The **enricher** runs WebSearch/WebFetch to add externally-cited claims. Frames are best-effort: if any step fails, the note is still written from the transcript.

### 4. Integrate and persist

![Integrate and persist](docs/architecture-4-persist.svg)

The orchestrator folds the enricher's citations into a single note, runs a final `check_slop` pass, and writes it. Writes are non-destructive (new notes never overwrite; updates append a dated section), carry deterministic OKF frontmatter, link into the category MOC, and upsert into Postgres/`pgvector`. The ingest log records what was written.

<sup>Diagram sources: [`docs/architecture-1-ingest.excalidraw`](docs/architecture-1-ingest.excalidraw) · [`-2-decompose`](docs/architecture-2-decompose.excalidraw) · [`-3-workers`](docs/architecture-3-workers.excalidraw) · [`-4-persist`](docs/architecture-4-persist.excalidraw). Export each to the matching `.svg`.</sup>

## Requirements

- **macOS on Apple Silicon** (the BGE-M3 embedding model uses Apple's MPS/GPU).
- **Python 3.12+** and [`uv`](https://docs.astral.sh/uv/).
- **[Claude Code](https://claude.com/claude-code)**, installed and authenticated — the agent run rides that auth (no API key needed).
- **Docker**, served by a lima-based daemon that bind-mounts `$HOME` — [Colima](https://github.com/abiosoft/colima) or [Rancher Desktop](https://rancherdesktop.io/) both work (Docker Desktop works too if `$HOME` file-sharing is enabled). Used for PostgreSQL + `pgvector` and for `ffmpeg`.

## Setup

**On a new machine, run the doctor first** — it checks every prerequisite and service and prints exactly what's missing plus the fix for each. It's **read-only**: it installs, starts, and changes nothing.

```bash
git clone https://github.com/8ballbb/study-notes && cd study-notes
./scripts/doctor.sh
```

**Then set it all up with one command** — it prints its plan, asks once, then installs/starts only what's missing (Homebrew deps, a Docker daemon — reusing Colima/Rancher Desktop if already running — the database + ffmpeg image, Python deps, Chromium) and finishes by re-running the doctor:

```bash
make setup          # or: ./scripts/setup.sh
```

<details><summary>Or do it by hand (what <code>make setup</code> runs)</summary>

```bash
# 1. Docker runtime — any lima-based daemon that bind-mounts $HOME.
#    If Rancher Desktop (or Colima) is already running, skip the next two lines.
brew install colima docker docker-compose     # only if you have no Docker daemon yet
colima start                                   # or just launch Rancher Desktop instead
docker compose up -d                          # Postgres 17 + pgvector (container: study_notes_db)
docker pull jrottenberg/ffmpeg:6.1-alpine     # frame extraction

# 2. The Python tool
uv sync --group dev
uv run playwright install chromium            # for webpage ingestion (JS-heavy pages, screenshots)

# 3. Point config.toml at your Obsidian vault. The tracked config.toml ships with
#    vault_path = "REPLACE_ME" — set it to an ABSOLUTE path UNDER $HOME (the Docker VM
#    only bind-mounts $HOME, and the app does NOT expand ~).
mkdir -p "$HOME/vault"                         # then set in config.toml:
#    vault_path = "/Users/you/vault"           # <- your real home dir, not the literal "you"

# 4. Verify — should be all [ok]
./scripts/doctor.sh
```

</details>

The database schema is created automatically on first run — no manual step.

Paywalled sites need a one-time login before their pages can be ingested: `uv run study-notes login <url>` opens a real browser window against a dedicated Playwright profile (not your everyday Chrome profile) — log in there once and the session is reused for later fetches of that site.

Alternatively, for sites covered by a public reader/mirror, the `[paywall]` config (see Configuration) routes matching hosts through it automatically — e.g. Medium and Medium-hosted publications via **Freedium**. The page is *fetched* through the mirror, but the note's recorded source stays the original article URL. Mirror domains rotate, so the base is config, not hardcoded.

> **Setting up with Claude Code?** It reads [`CLAUDE.md`](CLAUDE.md), runs `./scripts/doctor.sh`, and — for anything missing — tells you what and **asks before installing or starting it**. So on a fresh machine you can open the repo in Claude Code and say *"get this running"*: it will detect the gaps and walk you through them, with your permission at each step.

In Obsidian, install the community **Spaced Repetition** plugin if you want to review the cards a note may contain (enable FSRS in its settings).

## Usage

```bash
# Ingest a YouTube video (auto-categorised)
uv run study-notes add https://www.youtube.com/watch?v=<id>

# Ingest a webpage (paywalled sites need a one-time `study-notes login <url>` first)
uv run study-notes add https://example.com/some-article

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

`config.toml` at the repo root. It is tracked in git and ships with `vault_path = "REPLACE_ME"` — you **must** edit that to an absolute path under `$HOME` before the first run (the app does not expand `~`, and the doctor/setup will refuse to proceed while it is still the placeholder). Your local edit is expected to show as an uncommitted change; don't commit your machine-specific path back.

```toml
vault_path = "/Users/you/vault"        # absolute, under $HOME (edit the shipped REPLACE_ME)
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

[browser]
profile = "~/.study-notes/browser"      # dedicated Playwright profile — logins persist here, not your everyday Chrome
timeout_ms = 30000
headless = true                        # set false to watch a fetch run; `study-notes login` always opens a visible window

[paywall]                              # fetch matching hosts via a reader/mirror; the note's source stays the ORIGINAL URL
rules = [
  { hosts = ["medium.com", "towardsdatascience.com"], via = "https://freedium-mirror.cfd/{url}" },
]                                      # add news hosts via archive.today (https://archive.ph/newest/{url}) or SMRY (https://smry.ai/{url})

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
uv run pytest -m docker                                   # frame tests (needs a Docker daemon + ffmpeg image)
uv run pytest -m e2e                                      # real end-to-end agentic run — SPENDS Claude tokens
```

> **Note:** the `e2e` test drives a real agentic ingest (~2 min, costs tokens), so the default suite excludes it — run the token-free command above unless you specifically want the live end-to-end check.

See [`README-dev.md`](README-dev.md) for the full test matrix and the Docker/Colima details.

**Project conventions & AI workflow.** [`CLAUDE.md`](CLAUDE.md) is the portable brief for working in
this repo (with [Claude Code](https://claude.com/claude-code) or by hand): the command reference,
architecture map, invariants (non-destructive writes, OKF frontmatter, SDK isolation), and how to get
oriented on a fresh clone. The design history — why each piece exists and how it was built — lives as
specs and plans under [`docs/superpowers/`](docs/superpowers/).

> **Occasional retry:** an ingest sometimes ends with `Claude Code returned an error result: success`
> — a transient SDK teardown error, not a failed ingest. Re-run it; a failed *real* run isn't recorded,
> so the retry proceeds fresh. (Tracked in `CLAUDE.md` → Known issues.)

## Roadmap

Deliberately deferred, not blocking:

- Temporal conflict handling (detecting when new material updates or contradicts an existing note).
- BGE-M3 learned-sparse vectors for stronger lexical retrieval.
- An optional OKF *export* (converting the vault into a fully-conformant OKF bundle for other agents/tools).

Recently shipped: local Whisper fallback for caption-less videos; targeted, montage-based frame selection with per-video storage; OKF-aligned note frontmatter; a Feynman-plain writing voice.
