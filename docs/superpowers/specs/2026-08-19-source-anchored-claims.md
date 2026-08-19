# Spec: Source-anchored claims (deep-linking)

## Why
A study note's claims currently trace back only to a whole-source `resource:` URL. For
learning, one-click "where did this come from?" — jumping to the exact moment in the source —
is high value and makes a future web viewer materially better than plain Obsidian. Backlog
item #5.

## Scope (this iteration)
- **YouTube only.** Second-accurate per-segment timestamps already flow to the orchestrator;
  the frames path proves the extractor can hold and use them. Deep-link each anchored claim
  to `https://youtu.be/<id>?t=<secs>`.
- **Webpage/file: graceful no-anchor.** trafilatura text is a flat blob with no positions;
  PDF page tracking doesn't exist yet. Notes from these sources are unchanged (no anchors).
  Paragraph/page anchoring is explicitly deferred to a follow-up.

## Design
Structural, not model-arithmetic: the model copies a link the tool already built.
1. `youtube_deeplink(video_id, hhmmss) -> str` in `tools/youtube.py` → `https://youtu.be/<id>?t=<secs>`,
   using a local `_hhmmss_to_secs` helper (mirror of the existing `_secs_to_hhmmss`).
2. The transcript tool (`agent/tools.py` `fetch_youtube_transcript`) adds a `"url"` field to
   each segment dict: `{"start", "text", "url"}`. Webpage/file tool outputs get no such field.
3. `prompts/orchestrator.md`: when handing an extractor its YouTube source slice, preserve
   each segment's `start`/`url` verbatim (same discipline already used for frame timestamps).
4. `prompts/note-writing.md`: anchor a claim to its source moment with a compact link **when
   the slice provides per-segment links**; omit anchors when it doesn't.

No renderer change (bodies are written verbatim). No new tool. No models change.

## Tests
- Pure: `youtube_deeplink` over sample ids + HH:MM:SS (incl. hours) → correct `?t=<secs>`.
- Tool: transcript tool output carries a `url` per segment.
- Prompt-content: note-writing/orchestrator carry the anchoring instruction.
- (Optional, token-spending) e2e: a written YouTube note contains a `?t=` link.

## Out of scope / follow-ups
- Webpage `#:~:text=` fragment anchors; PDF page anchors (needs page→slice plumbing).
- Removing the dead `Card`/`Topic` structs in `models.py` (separate cleanup).
