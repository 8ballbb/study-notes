# Study Notes — Design Spec

**Date:** 2026-07-26
**Status:** Draft for review

## 1. Purpose

A personal command-line tool that ingests educational content — documents and YouTube
videos — understands it, and writes concise study notes with review-ready flashcards into
an Obsidian vault. The tool extracts core ideas, splits multi-topic sources into separate
notes, decides which **category** each topic belongs to (choosing an existing one or creating
a new one), then decides whether it is a new note or extends an existing note within that
category, and (for videos) embeds the relevant video frame alongside timestamped cards.

This is a personal tool. It targets the author's own workflow and machine, not a public
product. A public product may be a later chapter; nothing here forecloses it, but no design
decision is made to serve it.

### Strategic position

The "content → AI notes + flashcards" market is saturated with cloud SaaS (RemNote, Knowt,
Coconote, Turbolearn, StudyFetch, and others). The deliberate, differentiated position here
is **local-first, plain-markdown, you-own-the-data**, targeting Obsidian — the gap those
products leave open. Obsidian has no native semantic search, so the local hybrid index we
build is genuinely additive, not redundant.

## 2. Non-goals (v1)

- No human-in-the-loop confirmation gate. Correctness is enforced by a structured,
  self-verifying agent procedure plus non-destructive tools (see §8).
- No Whisper/local transcription. Videos without captions are a clear, logged failure; local
  transcription is a v2 item.
- No active temporal conflict *resolution*. v1 lays the metadata foundation only (see §9).
- No Ollama / alternative LLM backend. The tool is built around Claude Code (`claude -p`).
- No public/hosted product, auth, billing, or GUI.

## 3. Target machine

- MacBook Pro, Apple M4, 10 cores, 16 GB unified memory, macOS 15, arm64.
- Claude Code installed and authenticated (the tool rides this auth; no API key handling).
- PostgreSQL 17 + `pgvector`, run in a Docker container (`pgvector/pgvector:pg17`) via Colima — reproducible and free of host build-version mismatches.

## 4. Vault structure & conventions

The tool **owns and imposes** the vault structure (the vault holds this tool's output; a
consistent, machine-owned layout gives the agent strong placement/retrieval guarantees). It
creates the skeleton on first run. It still reads the **live vault state** on every run as the
source of truth for existing categories, so manual reorganization in Obsidian is adapted to,
not duplicated.

Grounded in 2026 Obsidian best practice: **folders answer "where does this live?" (one home
per note), tags answer "what is this about?" (many per note), MOCs handle navigation.** Keep
nesting shallow (≤ 3–4 levels); links replace deep folders.

### Skeleton (PARA-informed)

```
<vault>/
  00 - Inbox/            # transient; not used by auto-writes in v1
  02 - Areas/            # optional ongoing domains
  04 - Resources/        # DEFAULT notes_root — study material lives here
      <Category>/        # one folder per category (a "domain")
          <Category>.md  # the category MOC (index note; links its notes)
          <Note>.md      # atomic topic notes
  06 - Attachments/
      frames/            # extracted video frames
  07 - Archive/
  Templates/
  README.md              # documents the structure (authoritative for humans + agent)
```

- A **category** = a folder under `notes_root` (default `04 - Resources/`) **+ a MOC index
  note + a `category:` frontmatter field** on every note in it.
- The MOC (`<Category>/<Category>.md`) carries a short **description** in its frontmatter, used
  by the agent to judge category fit semantically (not just by name), and a maintained list of
  links to the category's notes.
- `notes_root` and the skeleton folder names are configurable (§11).
- Tags are used for cross-cutting properties (`#youtube`, topic tags), never as the primary
  category mechanism.

## 5. High-level architecture

A Python CLI orchestrates a pipeline of small, single-purpose stages. Anything with variants
(input type, note output) sits behind an interface so it is independently testable and
swappable. **Reasoning** (segment, extract, categorize) is delegated to Claude Code running
agentically; **precision-critical mechanics** (embeddings, frame extraction, vault writes,
retrieval) stay deterministic Python.

```
  Input (file path or YouTube URL)   [+ optional --category / --note overrides]
        │
   Python orchestrator (owns control flow, venv, config, dry-run)
        │
        ├── launches: claude -p  (agentic: reads input, segments, extracts,
        │      resolves category, resolves note placement, writes)
        │         │
        │         └── calls MCP tools (study-notes-tools, running in our venv):
        │                • fetch_youtube_transcript(url)  -> timed segments + metadata
        │                • list_categories()              -> categories + descriptions
        │                • vault_search(query, category)  -> related notes (scoped, hybrid)
        │                • extract_frame(video_ref, ts)   -> image path
        │                • vault_write(note, placement)   -> non-destructive write
        │
        └── local libraries (used by the MCP tools):
               BGE-M3 (FlagEmbedding/MPS), PostgreSQL+pgvector, yt-dlp, ffmpeg
```

### Division of labour

- **Python owns:** orchestration, config, the venv (home of all local libraries), the MCP
  server process, the optional dry-run, and final exit status.
- **Claude Code (`claude -p`) owns:** reading and understanding inputs (native multimodal
  reading of PDFs/images — no local parser, no GPU), segmentation, extraction of summaries and
  cards, category resolution, note-placement judgment, and driving the write via tools — all
  under a strict, self-verifying procedure.

## 6. Components

Each component has one job, a defined interface, and is testable in isolation.

- **Orchestrator (`cli`)** — parses the command (incl. `--category`/`--note` overrides), loads
  config, starts the MCP server, invokes `claude -p` per task with the right model/prompt/tool
  scope, handles dry-run and exit codes.
- **MCP server (`study-notes-tools`)** — a local MCP server running in the project venv,
  exposing typed tools to Claude Code. Single seam through which Claude reaches local
  capabilities: typed I/O and scoped safety instead of improvised Bash.
  - `fetch_youtube_transcript(url)` → `{ timed_segments[], metadata }` (via `yt-dlp`).
  - `list_categories()` → `[{ name, description, note_titles[] }]` (from Postgres, derived from
    the live vault).
  - `vault_search(query, category)` → ranked related notes **within a category** (BGE-M3 +
    PostgreSQL hybrid). Category scoping is mandatory — retrieval never crosses categories.
  - `extract_frame(video_ref, timestamp)` → saved image path (via `ffmpeg`).
  - `vault_write(note, placement)` → non-destructive write; creates category folder + MOC if
    the placement names a new category; updates the category MOC's link list; returns the
    written content for read-back verification.
- **VaultIndex** — wraps BGE-M3 embedding + PostgreSQL hybrid retrieval behind
  `find_related(query, category)`, `list_categories()`, and `upsert(note)`. All retrieval
  internals and category bookkeeping live here.
- **NoteRenderer** — pure function: a topic (summary + cards + frames + provenance + category)
  → Obsidian markdown in Spaced Repetition syntax. No side effects; exhaustively table-testable.

## 7. Data model

Plain objects carry state so stages never reach into each other's internals.

- **`Source`** — `{ text?, timed_transcript?, provenance }`. Documents may be read directly by
  Claude; YouTube sources carry a timed transcript. `provenance = { origin, input_type,
  captured_at, source_date? }`.
- **`Topic`** — `{ title, tags[], summary, cards[], source_span }`. One `Source` yields N topics.
- **`Card`** — `{ question, answer, cloze?, timestamp? }`. `timestamp` present only for
  YouTube-derived cards; it drives frame extraction.
- **`Category`** — `{ name, description }`. Resolved per topic before note placement.
- **`Placement`** — `{ category: Category, action: new_note | merge, target_note? }`.

## 8. Processing flow (single agentic run, self-verifying)

There is no human confirmation gate. Correctness is a property of the procedure and the tools.
A single `claude -p` run per input follows an ordered, checklisted procedure (encoded in the
task system prompt), with self-checks between steps:

1. **Ingest** — for a document, Claude reads the file directly (multimodal; `.docx` converted
   in one line via `textutil`/`pandoc`). For a YouTube URL, Claude calls
   `fetch_youtube_transcript`.
2. **Segment** — split the source into distinct topics.
   *Self-check:* topics are mutually distinct and every meaningful section maps to a topic
   (no dropped content, no overlap).
3. **Extract** — per topic, produce a concise `## Core ideas` summary and study cards.
   *Self-check:* each card's answer is grounded in the source; each timestamped card cites a
   real transcript timestamp.
4. **Frame** — for each timestamped card, call `extract_frame` and embed the image (multi-line
   card form; see §10).
5. **Resolve category (first placement step).** If `--category` was supplied, use it (create if
   new) and skip to step 6. Otherwise call `list_categories()`, then decide per topic: does it
   fit an existing category, or is it genuinely distinct enough to warrant a new one?
   *Fixed criteria:* prefer an existing category when clearly related; create a new category
   only on genuine non-overlap, to avoid near-duplicate categories.
6. **Resolve note placement, scoped to the category.** If `--note` was supplied, merge into it.
   Otherwise call `vault_search(query, category)` — **filtered to the resolved category** — and
   decide new note vs merge, stating explicit reasoning against fixed criteria. Because search
   is category-scoped, an unrelated topic in another category is never a merge candidate.
7. **Write** — call `vault_write`. New notes never clobber an existing path; new categories get
   a folder + MOC; the category MOC's link list is updated; merges append a dated
   `## Update (YYYY-MM-DD)` section and mark superseded claims — never a blind rewrite.
8. **Verify (closing gate)** — Claude re-reads what it wrote via the tool's returned content and
   confirms it against the plan (well-formed, correctly categorized and placed, complete). The
   run is not "done" until this passes.

**`--dry-run` (off by default):** runs steps 1–6 and prints proposed topics, categories, and
placements without writing. An escape hatch for previewing on unfamiliar content.

**Safety invariant:** writes are the last step, are non-destructive, and are read-back
verified. A crash mid-run leaves the vault untouched or appended-only — never half-rewritten.

## 9. Temporal foundation (v1 scope)

- Every note and card carries provenance: `source`, `source_type`, `source_date`,
  `captured_at`, and a `supersedes: []` frontmatter field (empty in v1).
- Because the vector index and this metadata both live in PostgreSQL, later temporal features
  (conflict detection, "how did my notes on X evolve", superseded-claim tracking) can be built
  with plain SQL over one store — the reason Postgres was chosen over Qdrant.
- No conflict detection or resolution ships in v1. The foundation is the metadata that cannot
  be cleanly retrofitted; the logic is a later chapter.

## 10. Note & card format

One topic → one markdown file in its category folder.

```markdown
---
title: Raft Consensus
category: Distributed Systems
type: study-note
tags: [distributed-systems, consensus, youtube]
source: https://youtube.com/watch?v=abc123
source_type: youtube
source_date: 2025-11-14      # video upload date
captured_at: 2026-07-26      # when this note was generated
supersedes: []               # temporal foundation; empty in v1
---

## Core ideas
- Concise bullet summary; one idea per line, tightened to essentials.

## Study cards
Short question about leader election?::Concise grounded answer.

What triggers a new term in Raft?
?
A failed leader election or leader timeout.
![[frames/raft_00-14-32.jpg]]
```

Rules:
- **Target plugin:** Obsidian **Spaced Repetition** (`st3v3nmw/obsidian-spaced-repetition`).
  It supports **FSRS** (opt-in in settings), keeps data in-vault, and supports cloze,
  multi-line, reversed, and rich media.
- **Card syntax:**
  - Inline `Question::Answer` for short cards; `Question:::Answer` for reversed.
  - **Multi-line `?` form is required whenever a card carries a frame or a longer answer** — the
    image embed must live inside the answer block, which inline `::` cannot do.
  - Cloze via `==highlight==`, `**bold**`, or `{{curly}}` for definition-style recall.
- **Frontmatter** carries `category` and `type` (machine-readability) plus provenance.
- **Frames:** stored in `06 - Attachments/frames/`, filename keyed to timestamp, embedded with
  Obsidian `![[...]]`. Only YouTube cards with a timestamp get a frame.
- **We do not write scheduling metadata.** The plugin owns review scheduling and appends its
  own metadata on first review. Our renderer writes only card content, category/provenance
  frontmatter, and the fixed section order.
- **Merge behavior:** "fits existing note" appends new ideas/cards under a dated
  `## Update (YYYY-MM-DD)` section rather than rewriting.
- **Category MOC:** each category folder holds `<Category>.md` with a description in frontmatter
  and a maintained list of links to its notes; `vault_write` keeps this current.
- **Setup note:** enabling FSRS in the plugin is a one-time recommended step, documented in the
  shipped README.

## 11. Configuration

A single `config.toml` plus a PostgreSQL connection. No LLM secrets — the tool rides Claude
Code auth.

```toml
vault_path = "/Users/andrewpoole/vault"
notes_root = "04 - Resources"      # categories are folders under here
attachments_dir = "06 - Attachments"
frames_subdir = "frames"

[database]
url = "postgresql://postgres:postgres@localhost:5432/study_notes"   # docker: pgvector/pgvector:pg17

[embedding]
model = "BAAI/bge-m3"              # local, dense + sparse, via FlagEmbedding on MPS

[models]                           # per-task model selection, tunable without touching code
segment    = "claude-haiku-4-5"
extract    = "claude-fable-5"
categorize = "claude-opus-4-8"

[prompts]                          # versioned prompt files, diffable over time
segment    = "prompts/segment.md"
extract    = "prompts/extract.md"
categorize = "prompts/categorize.md"

[run]
dry_run = false
```

- **Model-per-task** and **prompt-per-task** are data, not code. Each `claude -p` invocation
  passes `--model <task model>` and the task's system prompt (`--append-system-prompt`, body
  loaded from the prompt file), plus `--allowedTools` scoped to that step and `--add-dir` for
  input/vault access, and `--output-format json` for parseable results.
- CLI flags override config per run.

### CLI surface

- `study-notes add <path-or-url> [--category "<name>"] [--note "<title>"] [--dry-run]` —
  the primary command; ingest one source. `--category` forces the domain (skips category
  resolution, creating the category if new); `--note` forces a merge target (skips note search).
- `study-notes reindex` — (re)build the PostgreSQL index and category registry from the current
  vault.

## 12. Embedding & retrieval details

- **Model:** BGE-M3 (568M), MIT-licensed, dense + sparse + ColBERT in one model. Confirmed to
  run comfortably on M4 / 16 GB (~7.8 GB at F16, with headroom).
- **Runtime:** via **`FlagEmbedding` (BGEM3FlagModel)** on PyTorch **MPS** (Metal).
  **Not** Ollama — Ollama's embedding endpoint returns dense only, losing the sparse vectors the
  hybrid retrieval depends on.
- **Store:** PostgreSQL.
  - Dense: `pgvector` (`vector` column, HNSW index) from BGE-M3 dense output.
  - Lexical/sparse: start with **native Postgres full-text search** (`tsvector` + GIN). Upgrade
    path (behind `VaultIndex`): BGE-M3 learned-sparse in `sparsevec`, or `pg_search`/ParadeDB
    for true BM25.
  - Fusion: **Reciprocal Rank Fusion** in a single SQL query.
  - **Category scoping:** each embedded chunk row carries its `category`; `vault_search` filters
    by category in SQL, so retrieval is both hybrid and category-bounded.
- **Why Postgres over Qdrant:** unifies the vector index, category registry, and
  provenance/temporal relational data in one store, queryable with plain SQL and transactions.

## 13. Testing strategy

The seams are the point.

- **MCP tools / loaders** — deterministic, unit-tested against fixture files and recorded
  `yt-dlp`/`ffmpeg` outputs. Frame extraction tested against a tiny sample clip.
- **VaultIndex** — tested against a real local PostgreSQL (test schema): insert known notes
  across categories; assert hybrid search ranks the expected note first **and never returns a
  note from another category**; verify RRF fusion; verify `list_categories` reflects the vault.
- **NoteRenderer** — pure function, table-tested: `Topic` → exact markdown (Spaced Repetition
  syntax, category/provenance frontmatter, frame embeds, inline vs multi-line selection).
- **Category & MOC bookkeeping** — `vault_write` creates a new category folder + MOC correctly,
  updates an existing MOC's link list, and refuses to clobber existing note paths.
- **Agentic reasoning stages** — not asserted for exact wording (non-deterministic). Tested via
  golden-transcript smoke runs plus structural validators: output JSON matches schema, every
  timestamped card cites a real transcript time, segmentation covers the source without overlap,
  each topic resolves to exactly one category. These validators are the same checks the in-run
  procedure performs (§8).
- **Override flags** — `--category`/`--note` bypass the corresponding resolution step and land
  content where specified.
- **`--dry-run`** doubles as a manual integration harness.

## 14. Error handling

Fail loud and safe; never corrupt the vault.

- **Input failures** (no captions on a video, unreadable file, unsupported type) → clear
  message, non-zero exit, nothing written. (Whisper transcription is v2.)
- **LLM failures** (invalid JSON, `claude -p` non-zero, schema mismatch) → one retry, then
  abort that input with the raw output saved for inspection. No partial note written.
- **Tool failures** (`ffmpeg` can't grab a frame) → skip the frame with a warning; the note is
  still written without that image. (DB unreachable → abort before any write.)
- **Vault safety invariant** (§8): writes are last, non-destructive, and read-back verified.

## 15. Dependencies

- Python 3.12+, `uv`/`venv`.
- Claude Code CLI (authenticated).
- `FlagEmbedding` + PyTorch (MPS), `BAAI/bge-m3`.
- PostgreSQL 17 + `pgvector`, via Docker (`pgvector/pgvector:pg17`) on a Colima runtime; `docker-compose.yml` at the repo root.
- `yt-dlp` (pip). **ffmpeg runs via Docker** (`jrottenberg/ffmpeg:6.1-alpine`, throwaway `docker run`) — not a host install. The Python app itself stays on the host because BGE-M3 uses Apple MPS, which Docker on Mac cannot access; only services/binaries (Postgres, ffmpeg) are containerized. ffmpeg file I/O must be under a Colima-mounted path (`$HOME`).
- Python MCP server framework (e.g. the official `mcp` package).
- `textutil` (macOS built-in) or `pandoc` for `.docx` → text conversion.

## 16. Open items deferred to later chapters

- Whisper transcription for caption-less videos.
- Active temporal conflict detection and resolution.
- BGE-M3 learned-sparse vectors / `pg_search` for the lexical side.
- Richer "important visual moment" frame selection (v1 grabs the frame at a card's timestamp).
- Cross-category linking suggestions (MOCs currently stay within a category).
- Any public-product surface (GUI, hosting, multi-device).
