# Backlog

Future feature ideas and known follow-ups. Nothing here is blocking — the tool works end to end.

**How to use:** add a bullet under the right section. If an item grows big enough to need its own design notes, give it a file in this folder (`docs/backlog/<slug>.md`) and link it from its bullet. Move items to **Done** (or delete them) when shipped.

Rough priority: 🔴 worth doing soon · 🟡 nice to have · 🟢 someday / maybe.

---

## Deferred from the design (spec §16)

- 🟡 **Whisper transcription for caption-less videos.** Today a video without captions is a clean, logged failure. Add a local/whisper fallback so those still work.
- 🟡 **Temporal conflict handling.** Detect when a new note updates or contradicts an existing one (e.g. tracking a company's numbers over quarters) and reconcile via the dated-update mechanism. The provenance metadata (`source_date`, `captured_at`, `supersedes: []`) already exists as the foundation.
- 🟢 **BGE-M3 learned-sparse vectors / `pg_search`.** The lexical half of retrieval currently uses Postgres full-text search. Swapping in BGE-M3's learned-sparse vectors (or ParadeDB `pg_search` for true BM25) would sharpen keyword matching. Hidden behind the `VaultIndex` seam already.
- 🟢 **Richer "important visual moment" frame selection.** Currently a frame is grabbed at a card's timestamp. Could actively detect diagram/slide moments worth capturing.
- 🟢 **Public product surface.** GUI, hosting, multi-device — the deliberately-deferred "maybe later" chapter. The core pipeline is reusable if this is ever pursued.

## Maintenance & polish (flagged during the build)

- 🟡 **Category management helpers.** The model names categories and tries to reuse existing ones, but near-duplicates can accumulate over time (`Web APIs` / `APIs` / `HTTP`). Add `study-notes categories` (list) and `study-notes merge-category <from> <to>` (move notes + re-point the index). Manual merges in Obsidian are already picked up by `reindex`.
- 🟡 **Per-category frame subfolders.** All frames land in one flat `Attachments/frames/` pile. Group them per category or per note as the vault grows.
- 🟢 **Note filename slug collisions.** Two notes whose titles slug to the same filename would raise `VaultWriteConflict`. Rare, but a disambiguation suffix (or including a short hash) would make it robust.
- 🟢 **Top-level vault index (`Home.md`).** A generated home note linking all category index notes, for navigation.
- 🟢 **Run observability.** The Agent SDK returns `total_cost_usd` / `num_turns` per run — surface a one-line cost/timing summary after each `add`.

## Enhancements

- 🟡 **Interactive / "Claude drives the tools" mode.** The MCP server (`mcp_server.py`) is retained but unused by the CLI. Wire it up as an optional interactive mode for exploring the vault by chat.
- 🟢 **Anki export.** As an alternative to in-vault Spaced-Repetition cards, export drill-worthy cards to an `.apkg`/CSV.
- 🟢 **Enrichment controls.** Config knobs for how aggressive web research is (max additions, trusted-domain allowlist).
- 🟢 **Ollama / local-LLM option.** Dropped early for simplicity; could return as an opt-in backend for users who want fully local generation.

## Done

_(Move shipped items here, newest first.)_

- ✅ Simpler vault folder names (`Notes/` + `Attachments/`) — 2026-07-28
- ✅ `reindex` rebuilds category index notes (prunes stale links) — 2026-07-28
- ✅ `add`/`reindex` auto-create the DB schema (no manual init) — 2026-07-28
- ✅ Orchestrator-worker redesign on the Claude Agent SDK (adaptive notes + web-research enrichment) — 2026-07-28
