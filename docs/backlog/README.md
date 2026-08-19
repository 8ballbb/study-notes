# Backlog

Future feature ideas and known follow-ups. Nothing here is blocking — the tool works end to end.

**How to use:** add a bullet under the right section. If an item grows big enough to need its own design notes, give it a file in this folder (`docs/backlog/<slug>.md`) and link it from its bullet. Move items to **Done** (or delete them) when shipped.

Rough priority: 🔴 worth doing soon · 🟡 nice to have · 🟢 someday / maybe.

**Priority ordering (reviewed 2026-08-03).** A considered ranking of the features below; it
supersedes the coarse 🔴/🟡/🟢 dots for planning. Logic: cheap retrieval and connection wins
first, then capture quality for hard sources (a shared timed-segments cluster), then vault
coherence and note trustworthiness, then reach. (Items 1–4 are implemented on
`feat/retrieval-and-capture`, pending merge.)

1. **Contextual-prefix on embedded text**: near-free, sharpens all retrieval (query, placement, linking).
2. **Auto-link notes into a knowledge graph**: the point of an Obsidian vault; reuses the index and improves as more notes are added.
3. **Chapter-aware segmentation for long sources**: fixes the thin-summary collapse on 2-hour sources.
4. **Partial / region capture**: NL-guided find-then-confirm (the standing 🔴).
5. **Source-anchored claims (deep-linking)**: learning value, and unlocks a much better web viewer.
6. **Reconcile-on-merge**: stop merged notes accreting into dated append-logs.
7. **Source transparency & confidence**: cheap (mostly note-writing guide), core to a *learning* tool.
8. **Batch & playlist ingestion**: real studying happens in batches; dedup already guards repeats.
9. **More video hosts + podcasts**: near-free reach via the existing yt-dlp path and shipped Whisper fallback.
10. **Content-type-aware capture templates**: lifts capture relevance; the safe, template-driven counterpart to `--inspired`.

---

## Deferred from the design (spec §16)

- 🟡 **Temporal conflict handling.** Detect when a new note updates or contradicts an existing one (e.g. tracking a company's numbers over quarters) and reconcile via the dated-update mechanism. The provenance metadata (`source_date`, `captured_at`, `supersedes: []`) already exists as the foundation. *Vault-coherence cluster — see Reconcile-on-merge and Cross-source topic de-duplication under Enhancements.*
- 🟢 **BGE-M3 learned-sparse vectors / `pg_search`.** The lexical half of retrieval currently uses Postgres full-text search. Swapping in BGE-M3's learned-sparse vectors (or ParadeDB `pg_search` for true BM25) would sharpen keyword matching. Hidden behind the `VaultIndex` seam already.
- 🟡 **Better frame extraction (adopt claude-video's technique).** Frame capture is naive today (one frame at a card's timestamp). Adopt their proven approach instead of reinventing: keyframes via `ffmpeg -skip_frame nokey`, scene-change selection with uniform-sampling fallback, a **frame-delta dedup pass** (drops held slides / paused video), a **frame budget scaled by duration** (~12–80 frames), height-capped at 1998px. Consider using claude-video's `/watch` scripts directly as the frame/transcript primitive rather than rebuilding it.
- 🟢 **Public product surface.** GUI, hosting, multi-device — the deliberately-deferred "maybe later" chapter. The core pipeline is reusable if this is ever pursued.

## Maintenance & polish (flagged during the build)

- 🟡 **Category intelligence.** The model names categories and tries to reuse existing ones, but near-duplicates accumulate over time (`Web APIs` / `APIs` / `HTTP`). Make categories carry a description the model maintains, feed those descriptions + representative notes into the placement decision so it reuses categories better, and add `study-notes categories` (list) and `study-notes merge-category <from> <to>` (move notes + re-point the index). Manual merges in Obsidian are already picked up by `reindex`. *Keeps the vault coherent as it grows.*
- 🟡 **Vault health check — `study-notes lint`.** A read-only report of vault rot: dead `[[wikilinks]]`, orphaned notes (nothing links in), notes missing OKF frontmatter fields, and MOC entries pointing at deleted/renamed files. `reindex` already prunes stale MOC links when it rebuilds; this splits the *reporting* out as a standalone pass that changes nothing, so rot is visible without a full reindex. *(From [AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian)'s `wiki-lint`.)*
  - 🟡 **Near-duplicate note detection (diagnostic).** An all-pairs cosine pass over the note embeddings we already store, flagging pairs above a high threshold (~0.9) as candidate duplicates for review. Catches redundant ingests that whole-source dedup can't — same content, different URL. The write-time merge is **Cross-source topic de-duplication** under Enhancements; this is the standalone report. *(From claude-obsidian's `tiling-check`.)*
- 🟡 **Per-category frame subfolders.** All frames land in one flat `Attachments/frames/` pile. Group them per category or per note as the vault grows.
- 🟢 **Note filename slug collisions.** Two notes whose titles slug to the same filename would raise `VaultWriteConflict`. Rare, but a disambiguation suffix (or including a short hash) would make it robust.
- 🟢 **Top-level vault index (`Home.md`).** A generated home note linking all category index notes, for navigation.
- 🟢 **Run observability.** The Agent SDK returns `total_cost_usd` / `num_turns` per run — surface a one-line cost/timing summary after each `add`.

## Enhancements

### Capture (getting better notes out of sources)

- 🔴 **Partial / region capture — natural-language-guided, with a confirmation stage.** Capture only
  part of a source. Crucially this is driven by the user's prompt in plain language ("just the part
  about backpressure", "the second half"), **not** raw timestamps — so the flow must be:
  user specifies → the LLM locates the matching span in the transcript/document → it **shows what it
  found (range + a snippet) and asks the user to confirm or adjust** → only then extract. The
  find-then-confirm handshake is the whole point; guessing silently would capture the wrong slice.
  Reuses timed transcript segments; pairs with chapter segmentation below.
- 🟡 **Multi-source synthesis into one note.** Point several sources at one topic and get **one**
  authoritative, reconciled note (citing each source), not N notes. Genuine synthesis means the model
  must *study all the sources and derive a structure from the content itself* rather than slot them
  into a fixed template — i.e. it inherently uses the `--inspired` capability below. Distinct from
  batch-ingest (many→many) and cross-source topic dedup (merge after the fact); this is intentional
  **many→one** capture.
- 🟡 **`--inspired` — emergent, content-derived note structure (exploratory capture).** An optional
  mode where, instead of following a fixed note template, the model *studies the material, explores
  it (incl. web research), and designs a bespoke structure* — aiming to produce a **better-organised
  note than the source's own ordering** ("be inspired by it, then improve on it"). Applies to a
  single source as much as to multi-source synthesis (which requires it inherently). This is the
  exploratory counterpart to content-type templates below — worth designing the two as selectable
  structuring strategies: **templates** = fast, safe, predictable; **`--inspired`** = higher
  cost/latency, higher ceiling, bespoke.
- 🟡 **Content-type-aware capture templates.** A conference talk, a coding tutorial, a news article,
  and a lecture want different note shapes. Auto-detect (or `--type`) and switch the note-writing
  structure accordingly — a tutorial gets ordered steps + a code block; a talk gets thesis +
  arguments; news gets who/what/claims. The **template-driven** counterpart to `--inspired`: fast and
  predictable where `--inspired` is exploratory. Reuses the note-writing guide, parameterised. Lifts
  capture *relevance*.
- 🟡 **Chapter-aware segmentation for long sources.** Extract long videos/articles section-by-section
  (YouTube chapters / headings / auto-segmentation) then assemble, so a 2-hour lecture keeps
  granularity instead of collapsing to a thin summary. Reuses the extractor per-segment; also
  underpins partial capture above.
- 🟡 **Source-anchored claims (deep-linking).** Every claim links back to its exact origin — a
  YouTube `&t=` timestamp, PDF page, or article paragraph — for one-click verify/re-watch. Only
  frames carry a timestamp today. Reuses timed transcript segments; makes a web viewer materially
  better than plain Obsidian.
- 🟡 **A structured technical-document pipeline (papers / slides / repos).** A genuinely *new*
  pipeline, not just another `yt-dlp` host: structure-aware ingestion for academic PDFs/arXiv
  (sections, equations→LaTeX, tables→Markdown, references), slide decks (`.pptx`/Google Slides), and
  code repos (README + key files → a "how this works" note). Extends the pandoc/PDF path with
  structure parsing. Distinct from the generic "more video sources" item above.
- 🟡 **A web app viewer/exporter — so Obsidian isn't the only reader.** Export/serve the vault as a
  browsable, searchable web app (a natural fit for the `impeccable` skill) so notes can be read
  beautifully outside Obsidian. *Deliberately left unspecified — design it properly if/when we decide
  to build it.* The BGE-M3 hybrid index and OKF frontmatter are ready to back it; source-anchored
  deep-links (above) would make it genuinely better than Obsidian for source-grounded reading.

### Other

- 🟡 **Contextual-prefix on embedded text (Anthropic Contextual Retrieval).** Prepend a one-line frame ("part of {source}, covering {scope}") to the text we *embed* — not the displayed note — so an isolated note keeps its parent-document context and retrieval sharpens. The extractor already holds this context when it writes each note, so it's nearly free. Anthropic reports 35–49% retrieval-failure reduction, and the LLM-Wiki pattern in CLAUDE.md already endorses the approach. *(claude-obsidian applies this at ingest via `contextual-prefix.py`.)*
- 🟡 **Auto-link notes into a knowledge graph.** Notes sit siloed in category folders; the payoff of Obsidian is connections. Use the existing BGE-M3 + hybrid index — at write time and as a `study-notes link` pass — to insert `[[wikilinks]]` to genuinely related existing notes, **including across categories** (unlike the placement search, which is deliberately category-scoped). Compounds in value as the vault grows. *High leverage, reuses infrastructure already built.*
- 🟡 **Ingest more than YouTube — more video hosts & podcasts.** Web articles (Playwright render + `trafilatura`) and local files (text/Markdown/PDF, pandoc for `.docx`) already ingest, and `resolve_source` is already source-type-aware — so "study anything you read, watch, or listen to" is mostly real. Remaining: more `yt-dlp` *video* hosts (TikTok, Vimeo, X, Instagram — nearly free to enable) and podcasts/audio (→ transcript, reusing the local-Whisper fallback that already shipped).
- 🟡 **Combine notes — merge a chosen list into one larger note.** Provide a list of existing notes (e.g. several related status-code notes) and have them synthesised into a single coherent note, keeping each source's provenance and de-duplicating overlap. Also **iterative** — Claude confirms which notes, proposes an outline for the combined note, and asks you to agree before writing; originals are kept (or archived) non-destructively. Distinct from **Multi-source synthesis** above (that combines input *sources* into one note; this combines already-written *notes* on your explicit say-so) and from **Cross-source topic de-duplication** (automatic; this is user-driven).
- 🟡 **Batch & playlist ingestion — a study queue.** Feed a list of URLs, a YouTube playlist, or a watch-later file and process them all (dedup already prevents repeats). Real studying happens in batches. *Small for a URL list; medium for playlist expansion + progress.*
- 🟡 **Reconcile-on-merge — integrate updates, don't just append.** Merging into an existing note currently appends a dated `## Update` section, so notes accrete into append-logs. Have an extractor *rewrite* the note to fold new material into the body (keeping provenance) so notes stay coherent and current. *Vault-coherence cluster with Temporal conflict handling (Deferred) and Cross-source topic de-duplication.*
- 🟡 **Cross-source topic de-duplication.** Dedup is whole-source only, so two different videos on the same concept still create two notes on e.g. "HTTP 429". Use the hybrid index at write time to detect *topic-level* overlap and merge into one authoritative note. The hard part is judging "same topic vs. merely related". *Prevents a vault built from overlapping sources filling with redundant notes.* *Diagnostic complement: Near-duplicate note detection under Maintenance & polish.*
- 🟡 **Source transparency & confidence in notes.** Source-derived material and researched additions blur together, and nothing signals model uncertainty. Structure each note so the source-derived core, the "verified additions / further reading" (enrichment), and any low-confidence claims are distinguishable. *For a learning tool, knowing what's solid vs. inferred vs. externally-sourced is part of learning it correctly. Mostly a note-writing-guide + enrichment-integration change.*
- 🟡 **Learning-path / prerequisite ordering.** Notes in a category are an unordered set. Detect dependencies ("understand status-code families before the specific codes") and generate a suggested path — a `study-notes path <category>` or an ordering in the category index note. *Turns a pile of notes into a curriculum.*
- 🟡 **Interactive / "Claude drives the tools" mode.** An optional interactive mode for exploring the vault by chat, with Claude driving the in-process tools directly. (An earlier standalone `mcp_server.py` for this was removed as dead code; build it fresh on the in-process `@tool` server the CLI already uses, rather than a separate stdio MCP subprocess.)
- 🟢 **Anki export.** As an alternative to in-vault Spaced-Repetition cards, export drill-worthy cards to an `.apkg`/CSV.
- 🟢 **Enrichment controls.** Config knobs for how aggressive web research is (max additions, trusted-domain allowlist).
- 🟢 **Ollama / local-LLM option.** Dropped early for simplicity; could return as an opt-in backend for users who want fully local generation.

## Prior art / references

- **[bradautomates/claude-video](https://github.com/bradautomates/claude-video)** (11.6k★) — a Claude Code `/watch` **skill** for *conversational, ephemeral* video analysis: yt-dlp captions (Whisper fallback), sophisticated ffmpeg frame extraction (scene detection + dedup + duration-scaled budgets + detail modes), frames streamed into Claude's multimodal context. **Complementary, not competing** — it's a video-*understanding primitive*, we're a persistent study-*knowledge-base builder* (Obsidian notes, categories, hybrid retrieval, enrichment, dedup). It does the ingestion/frame layer better than us; we do everything after. **Takeaway:** borrow its frame + Whisper technique (or reuse its scripts), and steal its multimodal-frame idea outright (see the 🔴 item). Don't rebuild the knowledge-base parts — it has none.

- **[AgriciDaniel/claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian)** — a local-first Claude Code **plugin** (15 skills) that builds a source-cited Obsidian vault. Roughly the **inverse** of us: it does almost no content extraction (URL/YouTube/PDF are consent-gated *plans* needing an external runner — no yt-dlp/Whisper/Playwright bundled), but it's far ahead on **reuse and durability** — a read-only `wiki-query`, a `wiki-lint` health check, ingest-time contextual prefixes, semantic dup detection (`tiling-check`), source/claim provenance ledgers, and a journaled transaction+Git-checkpoint engine. **Takeaway:** the four items credited above (query, lint, contextual-prefix, dup-detection) are cheap because they reuse our existing index; its heavier machinery (transaction/rollback engine, claim ledger, multi-host packaging) is over-engineering for a single-user CLI and deliberately **not** adopted. We already beat it on extraction, dense-vector RRF retrieval, and prose voice.

## Done

_(Move shipped items here, newest first.)_

- ✅ Read-only `query` command — cross-category hybrid retrieval + grounded, cited answer — 2026-08-03
- ✅ Iterative capture (`add --interactive`) — proposes a plan, asks via `ask_user`, per-write approval hook — 2026-08-03
- ✅ Interactive note refinement (`refine <path>`) — feedback → propose → approve → lossless in-place rewrite — 2026-08-03
- ✅ Multimodal frames — extractor now sees candidate frames (montage) and embeds the chosen ones (0→16 on the test video) — 2026-08-03

- ✅ Local Whisper fallback for caption-less videos (`mlx-whisper`, `whisper-large-v3-turbo`) — 2026-08-03
- ✅ Simpler vault folder names (`Notes/` + `Attachments/`) — 2026-07-28
- ✅ `reindex` rebuilds category index notes (prunes stale links) — 2026-07-28
- ✅ `add`/`reindex` auto-create the DB schema (no manual init) — 2026-07-28
- ✅ Orchestrator-worker redesign on the Claude Agent SDK (adaptive notes + web-research enrichment) — 2026-07-28
