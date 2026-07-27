# Study Notes — Run-Layer Redesign: Orchestrator–Workers

**Date:** 2026-07-27
**Status:** Draft for review
**Supersedes:** the single-agentic-run design in `2026-07-26-study-notes-design.md` §8 and §11 (`[agent]` single model, `procedure.md` single run) and the `claude_runner`/single-`claude -p` core of Plan 3. Everything else in Plans 1, 2, and 2.5 stands.

## 1. Why redesign

**Primary motivation — product.** The shipped single-run design produces notes that (a) are a mere distillation of the source rather than **enriched with online research** (better than the source), and (b) default to **summary-plus-Q&A cards**, a format that doesn't fit how the user learns. Both are explicit user requirements the single-run shape serves poorly, and both are the real reasons to redesign.

**Secondary motivation — efficiency.** The single run processes topics strictly sequentially and re-sends the whole transcript plus every prior turn on each turn, so it has no parallelism and its context grows monotonically. A scoped, parallel, model-per-role decomposition improves cost and latency.

**Correction — what the "slowness" actually was.** Early testing showed a run taking *hours*, initially misattributed to context accumulation. The dominant cause was in fact a **tool bug**: `yt-dlp` wrote progress to stdout, which corrupted the MCP server's stdio JSON-RPC channel and hung the transcript-fetch call for 30–43 minutes at a time (~2h40m total). **That bug is now fixed** (yt-dlp output suppressed; see commit `b99cc4b`), so the single run is no longer pathologically slow. This redesign therefore proceeds on the **product** grounds above — enrichment and adaptive notes — with parallelism/cost a genuine but *secondary* benefit, not a slowness cure. The bug fix, not this redesign, is what makes ingestion fast.

## 2. Goals

Ordered after the bug correction (all three matter; quality now leads):
- **Quality (primary)** — adaptive, well-written, research-enriched notes that match how the user learns.
- **Cost** — cheap/fast models on the mechanical volume, the expensive model only where judgment lives.
- **Speed** — parallel workers keep a multi-topic ingest quick; the pathological slowness is already resolved by the tool fix, so this is incremental, not the driver.

## 3. What stays vs. what changes

- **Unchanged (reused as-is):** Plan 1 (config, models, renderer, BGE-M3 embedder, Postgres/pgvector, category-scoped hybrid `VaultIndex`); Plan 2 tool *functions* (`fetch_youtube_transcript`, `vault_search`, `extract_frame`, non-destructive `VaultWriter`, `list_categories`); Plan 2.5 (`IngestLog` dedup, `slop_check`, anti-slop guide); the deterministic CLI shell (`study-notes add/reindex`), the **step-0 dedup gate**, **IngestLog recording**, and **recovering written note paths from `notes.source`**.
- **Replaced:** the single `claude -p` run (`procedure.md` + `claude_runner`) becomes an **orchestrator–workers engine**. `[agent]` single-model config becomes per-role model config. `procedure.md` is superseded by an orchestrator prompt plus a note-writing guide.
- **The MCP server becomes optional.** In the new engine the app calls tool functions directly (or exposes them to workers as SDK tools); the MCP wrapper is retained only for an interactive "Claude drives the tools" mode, not the CLI path.

## 4. Architecture: orchestrator–workers

A **lead orchestrator (opus)** coordinates; **specialized workers (cheaper/faster models)** do the bulky, scoped work in **isolated context windows**, **in parallel**. The load-bearing principle (from Anthropic's multi-agent research system): the orchestrator never ingests raw material into its own context — it trafficks in structure and compact results, so its context stays small and fast regardless of source length.

### Lead orchestrator (opus) — judgment + coordination

1. **Decompose (read + split).** Opus reads the source (this one bounded pass is where it *understands* the material) and splits it into distinct topic-chunks, each a compact spec: a title, a scope, and the slice of source it covers. Splitting well needs understanding, which is why opus does it rather than a cheap worker.
2. **Resolve placement (judgment).** For each topic, decide category (existing vs. new) via `vault_search`/`list_categories`, and new-note vs. merge — the same category-scoped, non-destructive rules as today.
3. **Dispatch workers** with scoped inputs (see below) and collect their compact results.
4. **Integrate + verify.** Assemble the final notes from worker outputs, run the closing checks (grounded, well-formed, correctly placed, slop-clean), and drive the writes via `vault_write`.
5. **Do a task itself when suited** — small judgment-heavy steps (final placement, reconciling a conflict) stay with opus rather than being delegated.

Opus's context holds topic specs, category info, and compact worker results — never the full transcript across many turns.

### Workers (cheap/fast models, fresh isolated context, parallel)

- **Extractor (one per topic, run in parallel).** Input: that topic's source slice + the **note-writing guide** (§5) + optionally one neighbor note for style consistency (§5). Output: the finished note markdown for that topic. Workers never see the orchestrator's history or each other.
- **Enricher (one per topic, parallel; see §6).** Input: the topic's draft/key claims. Does targeted **web research** to verify, add authoritative context, supply a missing example, flag outdated/incorrect points, and surface related ideas — returning compact, cited additions the orchestrator merges.
- **Frame-picker (optional, YouTube only).** Given a topic's timestamps, selects the frame(s) worth embedding; the deterministic `extract_frame` tool does the capture.

### Data flow

```
source ──▶ [Python] dedup gate (IngestLog) ──▶ ORCHESTRATOR (opus)
                                                   │ decompose + split (1 read pass)
                                                   │ per topic: resolve category/placement
                                                   ▼
                        ┌───────── parallel, isolated-context workers ─────────┐
                        │  Extractor(topic_i)      Enricher(topic_i)  [Frame]   │
                        └───────────────────────────────────────────────────────┘
                                                   │ compact results
                                                   ▼
                                        ORCHESTRATOR integrates + verifies
                                                   │ vault_write (non-destructive)
                                                   ▼
                        [Python] recover paths from notes.source ──▶ IngestLog.record
```

## 5. Note-writing guide (replaces the format catalog + metadata)

There is **no format enum, no per-note format field, no inheritance tracking.** Instead a single **versioned note-writing guide** (`prompts/note-writing.md`, same pattern as the anti-slop guide) encodes *how to write a good study note*, and the extractor applies it with judgment. Rationale: formats compose within one note (an analogy, then prose, then a comparison table), so pinning one mode per note fights good writing; a guide is more adaptable and removes a whole tracking layer.

The guide encodes:
- **Understanding-first, concise.** Explain ideas so they're understood and retained, not padded. Conciseness is a rule *within* whatever structure fits.
- **A format toolbox to compose from as the content warrants** — explanatory/teaching, structured breakdown, step-by-step, comparison table, worked example, decision guide, analogy/mental-model, cause→effect, timeline, cheat-sheet, claim→evidence. These are tools to combine, not mutually-exclusive modes. Rote-drill Q&A is available but not the default.
- **The user's learning style** — this guide is the single place to tune "how I learn"; it is expected to iterate.
- **Anti-slop** — composes with / references `anti-slop.md`.

**Soft consistency without tracking.** When a note is added to an existing category, the orchestrator hands the extractor **one existing note from that category as a style reference** ("match this note's shape"), fetched via `vault_search`. Consistency comes from *showing a neighbor*, not a stored tag, and degrades gracefully for new categories.

## 6. Enrichment via web research

Notes should be *better than the source*. An **enrichment worker** per topic performs targeted web research and returns compact, **cited** additions for the orchestrator to merge:
- verify key claims; flag where the source is outdated or wrong;
- add authoritative context or a concrete example the source skipped;
- surface closely related ideas worth a link.

Guardrails: **meaningful, not padding** (the guide caps additions and requires each to earn its place); **every external claim carries a source URL**, recorded in the note (a `sources:`/`references:` section and/or provenance), so enrichment is auditable and distinguishable from the original material. Enrichment needs a **web-search/fetch tool** available to that worker. If research fails or finds nothing solid, the note is still written from the source alone (graceful degradation).

## 7. Build mechanism

**Recommended: the Claude Agent SDK (Python).** It runs the same agent harness programmatically and gives what this design needs: define the orchestrator and each worker as agents **with per-role models**, **subagent delegation**, **parallel fan-out**, tools as in-process Python functions (reusing `study_notes/tools/*`), and structured outputs — with real control over parallelism, context scoping, retries, and testing. It replaces the `claude_runner` subprocess approach; the deterministic Python edges (dedup gate, IngestLog, paths-from-DB, vault-safety) wrap it unchanged.

**Alternative considered: Claude Code headless subagents** (`.claude/agents/*.md` with `model:` frontmatter, dispatched via the Task tool from an opus `claude -p`). Less code, but weaker programmatic control over parallelism, context, error handling, and testing. Chosen against for a maintainable, testable app, but a viable fallback if the SDK proves awkward.

Per-role model config (superseding `[agent].model`):
```toml
[models]
orchestrator = "claude-opus-4-8"     # decompose, placement judgment, integrate, verify
extractor    = "claude-sonnet-5"     # per-topic note writing
enricher     = "claude-sonnet-5"     # per-topic web research
```

## 8. Error handling

- **Worker failures are isolated.** A failed extractor/enricher is retried by the orchestrator (safe — workers *produce*, they don't touch the vault); if it keeps failing, that topic is dropped with a warning and the rest proceed. Retries are safe here precisely because writes are centralized in the orchestrator, unlike the old whole-run retry that risked duplicate writes.
- **Web research failures degrade gracefully** — the note is written from the source alone.
- **Vault safety is unchanged** — writes happen last, via the non-destructive `vault_write` (clobber-refusal, dated merges, vault-confinement, atomic + read-back).
- **Dedup and recording unchanged** — the Python gate runs before any model work; paths are recovered from `notes.source`; `IngestLog` is recorded only after a successful non-dry-run.

## 9. Testing

- **Workers in isolation** — each is a scoped `input → output` function of (slice, guide) → note, or (claims) → cited additions; unit-testable with stubbed models, and validated with structural checks (grounded, cited, slop-clean via `slop_check`).
- **Orchestrator logic** — decomposition into topic specs, placement decisions, and integration are testable with stubbed workers; the deterministic edges keep their existing tests.
- **The note-writing + enrichment guides** — light tests that they cover the intended principles; quality is judged by iteration on real sources.
- **End-to-end** — a marked `e2e` run over a caption-bearing video, asserting parallel workers fire, notes land, enrichment carries sources, and a re-add is dedup-skipped. Also the manual "is it fast now?" check the redesign exists to satisfy.

## 10. Non-goals (this redesign)

- No change to retrieval, embeddings, the vault schema, or the tool functions.
- No format-tracking metadata, format enum, or per-category format inheritance (deliberately removed).
- No agent-to-agent chatter — workers talk only to the orchestrator (hub-and-spoke), matching the proven pattern.
- Whisper transcription, temporal conflict resolution, and BGE-M3 learned-sparse remain deferred (spec §16).

## 11. Open items folded into implementation

- Exact Claude Agent SDK API for defining agents/tools/models and awaiting parallel workers (pinned during planning).
- The web-search/fetch tool for the enricher (which provider/tool; must be available in the SDK worker context).
- First drafts of `prompts/note-writing.md` and the orchestrator prompt (iterated on real content).
