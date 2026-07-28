# Backlog

Future feature ideas and known follow-ups. Nothing here is blocking — the tool works end to end.

**How to use:** add a bullet under the right section. If an item grows big enough to need its own design notes, give it a file in this folder (`docs/backlog/<slug>.md`) and link it from its bullet. Move items to **Done** (or delete them) when shipped.

Rough priority: 🔴 worth doing soon · 🟡 nice to have · 🟢 someday / maybe.

---

## Deferred from the design (spec §16)

- 🟡 **Whisper transcription for caption-less videos.** Today a video without captions is a clean, logged failure. Add a Whisper fallback. Proven recipe from [claude-video](https://github.com/bradautomates/claude-video): extract audio with `ffmpeg -vn -ac 1 -ar 16000 -b:a 64k` (~0.5 MB/min) → Groq `whisper-large-v3` (default) or OpenAI `whisper-1`, auto-chunking over the 25 MB API cap.
- 🟡 **Temporal conflict handling.** Detect when a new note updates or contradicts an existing one (e.g. tracking a company's numbers over quarters) and reconcile via the dated-update mechanism. The provenance metadata (`source_date`, `captured_at`, `supersedes: []`) already exists as the foundation.
- 🟢 **BGE-M3 learned-sparse vectors / `pg_search`.** The lexical half of retrieval currently uses Postgres full-text search. Swapping in BGE-M3's learned-sparse vectors (or ParadeDB `pg_search` for true BM25) would sharpen keyword matching. Hidden behind the `VaultIndex` seam already.
- 🔴 **Multimodal frame analysis (let the extractor SEE the video).** The biggest lesson from [claude-video](https://github.com/bradautomates/claude-video) (11.6k★): it streams frames *into Claude's context* so the model grounds its output in what's actually on screen. We only *embed a screenshot* — the model never looks at it, so notes can only describe the transcript, not the diagram/slide/code shown. Feed selected frames into the extractor (the Agent SDK supports images) so notes can describe diagrams, capture on-screen code, etc. Bigger and better than OCR. *The single highest-value idea this research surfaced, and it targets exactly the visual/technical content this tool is for.*
- 🟡 **Better frame extraction (adopt claude-video's technique).** Frame capture is naive today (one frame at a card's timestamp). Adopt their proven approach instead of reinventing: keyframes via `ffmpeg -skip_frame nokey`, scene-change selection with uniform-sampling fallback, a **frame-delta dedup pass** (drops held slides / paused video), a **frame budget scaled by duration** (~12–80 frames), height-capped at 1998px. Consider using claude-video's `/watch` scripts directly as the frame/transcript primitive rather than rebuilding it.
- 🟢 **Public product surface.** GUI, hosting, multi-device — the deliberately-deferred "maybe later" chapter. The core pipeline is reusable if this is ever pursued.

## Maintenance & polish (flagged during the build)

- 🟡 **Category intelligence.** The model names categories and tries to reuse existing ones, but near-duplicates accumulate over time (`Web APIs` / `APIs` / `HTTP`). Make categories carry a description the model maintains, feed those descriptions + representative notes into the placement decision so it reuses categories better, and add `study-notes categories` (list) and `study-notes merge-category <from> <to>` (move notes + re-point the index). Manual merges in Obsidian are already picked up by `reindex`. *Keeps the vault coherent as it grows.*
- 🟡 **Per-category frame subfolders.** All frames land in one flat `Attachments/frames/` pile. Group them per category or per note as the vault grows.
- 🟢 **Note filename slug collisions.** Two notes whose titles slug to the same filename would raise `VaultWriteConflict`. Rare, but a disambiguation suffix (or including a short hash) would make it robust.
- 🟢 **Top-level vault index (`Home.md`).** A generated home note linking all category index notes, for navigation.
- 🟢 **Run observability.** The Agent SDK returns `total_cost_usd` / `num_turns` per run — surface a one-line cost/timing summary after each `add`.

## Enhancements

- 🟡 **Auto-link notes into a knowledge graph.** Notes sit siloed in category folders; the payoff of Obsidian is connections. Use the existing BGE-M3 + hybrid index — at write time and as a `study-notes link` pass — to insert `[[wikilinks]]` to genuinely related existing notes, **including across categories** (unlike the placement search, which is deliberately category-scoped). Compounds in value as the vault grows. *High leverage, reuses infrastructure already built.*
- 🟡 **Ingest more than YouTube — more video sources, articles & podcasts.** `yt-dlp` already supports TikTok, Vimeo, X, Instagram, and local files (per claude-video), so more *video* sources are nearly free to enable. Still missing: web articles (non-YouTube URL → fetch + readability) and podcasts/audio (→ transcript, shares the Whisper item above). Make the pipeline source-type-aware so "study anything you read, watch, or listen to" is real.
- 🟡 **Conversational refinement — `study-notes refine <note> "<instruction>"`.** Shape an existing note in place ("make this more concise", "add a worked example", "expand the 4xx/5xx part") by re-running an extractor on the current note + instruction, non-destructively. Beats hand-editing or re-ingesting; makes the tool feel like a study partner. *Reuses the extractor + vault_write.*
- 🟡 **Batch & playlist ingestion — a study queue.** Feed a list of URLs, a YouTube playlist, or a watch-later file and process them all (dedup already prevents repeats). Real studying happens in batches. *Small for a URL list; medium for playlist expansion + progress.*
- 🟡 **Reconcile-on-merge — integrate updates, don't just append.** Merging into an existing note currently appends a dated `## Update` section, so notes accrete into append-logs. Have an extractor *rewrite* the note to fold new material into the body (keeping provenance) so notes stay coherent and current.
- 🟡 **Cross-source topic de-duplication.** Dedup is whole-source only, so two different videos on the same concept still create two notes on e.g. "HTTP 429". Use the hybrid index at write time to detect *topic-level* overlap and merge into one authoritative note. The hard part is judging "same topic vs. merely related". *Prevents a vault built from overlapping sources filling with redundant notes.*
- 🟡 **Source transparency & confidence in notes.** Source-derived material and researched additions blur together, and nothing signals model uncertainty. Structure each note so the source-derived core, the "verified additions / further reading" (enrichment), and any low-confidence claims are distinguishable. *For a learning tool, knowing what's solid vs. inferred vs. externally-sourced is part of learning it correctly. Mostly a note-writing-guide + enrichment-integration change.*
- 🟡 **Learning-path / prerequisite ordering.** Notes in a category are an unordered set. Detect dependencies ("understand status-code families before the specific codes") and generate a suggested path — a `study-notes path <category>` or an ordering in the category index note. *Turns a pile of notes into a curriculum.*
- 🟡 **Interactive / "Claude drives the tools" mode.** The MCP server (`mcp_server.py`) is retained but unused by the CLI. Wire it up as an optional interactive mode for exploring the vault by chat.
- 🟢 **Anki export.** As an alternative to in-vault Spaced-Repetition cards, export drill-worthy cards to an `.apkg`/CSV.
- 🟢 **Enrichment controls.** Config knobs for how aggressive web research is (max additions, trusted-domain allowlist).
- 🟢 **Ollama / local-LLM option.** Dropped early for simplicity; could return as an opt-in backend for users who want fully local generation.

## Prior art / references

- **[bradautomates/claude-video](https://github.com/bradautomates/claude-video)** (11.6k★) — a Claude Code `/watch` **skill** for *conversational, ephemeral* video analysis: yt-dlp captions (Whisper fallback), sophisticated ffmpeg frame extraction (scene detection + dedup + duration-scaled budgets + detail modes), frames streamed into Claude's multimodal context. **Complementary, not competing** — it's a video-*understanding primitive*, we're a persistent study-*knowledge-base builder* (Obsidian notes, categories, hybrid retrieval, enrichment, dedup). It does the ingestion/frame layer better than us; we do everything after. **Takeaway:** borrow its frame + Whisper technique (or reuse its scripts), and steal its multimodal-frame idea outright (see the 🔴 item). Don't rebuild the knowledge-base parts — it has none.

## Done

_(Move shipped items here, newest first.)_

- ✅ Simpler vault folder names (`Notes/` + `Attachments/`) — 2026-07-28
- ✅ `reindex` rebuilds category index notes (prunes stale links) — 2026-07-28
- ✅ `add`/`reindex` auto-create the DB schema (no manual init) — 2026-07-28
- ✅ Orchestrator-worker redesign on the Claude Agent SDK (adaptive notes + web-research enrichment) — 2026-07-28
