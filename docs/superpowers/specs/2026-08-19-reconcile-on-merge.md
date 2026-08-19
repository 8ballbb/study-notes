# Spec: Reconcile-on-merge

## Why
Backlog item #6. Merging a new source into an existing note should fold the new material
into the note's body (keeping provenance), not stack dated `## Update` sections that turn
notes into append-logs.

## Finding (reshapes the work)
The dated-append path is **already gone** — it lived only in the removed
`write_merge`/`render_update_section`/`mcp_server` code. Worse, merges currently have **no
working path**: `--note "Title"` only adds an English directive; the add path's sole writer,
`vault_write`→`write_markdown`, refuses to overwrite (`VaultWriteConflict`); and the
fold-into-body primitive that already exists — `rewrite_note`→`VaultWriter.rewrite_markdown`
— is not exposed to the add path (only `refine`/`linker` use it). So this feature both
delivers reconcile-on-merge **and repairs the broken `--note` merge**. No new write method.

## Design (tool-exposure + prompt; model-driven)
1. Add `rewrite_note` to the orchestrator tool set `_TOOLS` (`agent/engine.py`) so both the
   non-interactive and interactive add paths can call it.
2. In interactive add, add `rewrite_note` to the approve list (`cli.py`) so the human
   write-approval hook gates a merge rewrite (the hook already labels a `path` arg).
3. `prompts/orchestrator.md`: on a forced `target_note` or a strong `vault_search` match,
   resolve the path, `Read` the existing note (search returns only `{path, score}`), fold
   the new material into the body preserving provenance, and call `rewrite_note(path, markdown)`
   **instead of** `vault_write`. Reconcile into the prose — do not append a dated section.
4. Update the CLAUDE.md "non-destructive writes" invariant to describe reconcile-on-merge.

Reuses `VaultWriter.rewrite_markdown` and the `rewrite_note` tool unchanged.

## Tests
- `build_options` exposes `rewrite_note` in `allowed_tools`.
- Prompt-content: orchestrator instructs read-then-`rewrite_note` reconcile on merge.
- (Optional, token-spending) e2e: ingest A into a note, then ingest B with `--note "A"`;
  assert one note, provenance kept, rewritten in place, no `## Update` block.

## Invariant preserved
`vault_write` still refuses to overwrite (new notes never clobber). `rewrite_note` remains
the only in-place primitive and still preserves frontmatter/provenance and rejects title
renames.
