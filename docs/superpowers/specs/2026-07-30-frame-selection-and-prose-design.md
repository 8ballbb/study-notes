# Frame-Selection Quality, Frame Folders & Prose Voice — Design Spec

**Date:** 2026-07-30
**Status:** Approved (verbally); ready to plan.
**Builds on:** the video-ingestion upgrade (`2026-07-28-video-ingestion-upgrade-design.md`) and the
orchestrator-worker engine. Motivated by that feature's e2e observations.

## 1. Purpose

Three improvements to the video → notes pipeline:

1. **Smarter frame selection.** The current `select_keyframes` extracts candidates with ffmpeg
   `mpdecimate` then **uniformly subsamples** to the budget — blind to quality, duplication, or
   whether a diagram has finished animating.
2. **Cleaner frame storage.** Kept frames are dumped flat into `Attachments/frames/`, which is
   messy and impossible to clean per-source.
3. **Better prose.** The anti-slop layer is all negative (ban-lists) and its checker misses the
   biggest 2026 tells; there is no positive voice target. The chosen voice is **Feynman-plain**.

## 2. Non-goals

- No OCR / Tesseract (unchanged); frame selection stays visual + text-cue driven.
- No ML models or heavy deps; frame refinement is **numpy + Pillow**, local and key-free.
- No change to retrieval, the vault layout (beyond the frames subfolder), ingestion dedup, or the
  CLI shell.
- Edge-density ranking (frame idea #4) is **deferred** — not in this spec.

## 3. Stream A — Frame selection quality

### 3.1 Extraction (unchanged)
`select_keyframes` still runs Docker ffmpeg `mpdecimate,scale=512:-1,showinfo` over the window,
parsing `pts_time` into absolute timestamps → candidate JPEGs.

### 3.2 Refinement — new module `src/study_notes/tools/frame_select.py` (numpy + Pillow)
A pure, unit-testable pass over the candidate JPEGs, applied inside `select_keyframes` after
extraction:

- **Blur filter** — `laplacian_variance(img) -> float`; drop candidates below a sharpness floor
  (motion-blur / mid-transition frames).
- **Perceptual dedup + settled-frame** — `dhash(img) -> int`, `hamming(a, b) -> int`; walk
  candidates in time order and collapse near-duplicate runs (Hamming < `DUP_DISTANCE`). When
  collapsing a run, keep the **last** frame (the settled/held diagram) and, among ties, the
  **sharpest**. This combines "settled-frame" and "pHash dedup".
- **Budget cap** — if more than `budget` survive, keep the most visually-distinct set
  (greedy max-min dHash distance), not a uniform slice.

`refine_candidates(candidates: list[dict], budget: int) -> list[dict]` returns the kept
`[{path, timestamp}]`, most-informative first.

### 3.3 Contact-sheet selection
- `build_montage(candidates: list[dict], out_path: Path) -> Path` (Pillow) tiles the refined
  candidates into one labeled grid image, each cell numbered with its **index** and timestamp.
- `select_keyframes(...)` return shape **changes** to:
  `{"candidates": [{"candidate_path", "timestamp", "index"}], "montage_path": str}`.
- The extractor `Read`s the **single montage** (not each frame), compares side-by-side, picks the
  best index/indices, and `keep_frame`s those candidates. Fewer multimodal tokens + real
  comparison.

### 3.4 Cross-topic dedup in `keep_frame`
Before copying a chosen frame in, `keep_frame` dHash-compares it against frames already kept for
this video (its per-video folder). If a near-duplicate exists (Hamming < `DUP_DISTANCE`), it skips
the copy and returns the existing embed path — so the same slide never lands in two notes.

### 3.5 Interfaces (changed)
- `select_keyframes(video_path, start, end, budget, out_dir) -> {"candidates":
  [{"candidate_path": str, "timestamp": str, "index": int}], "montage_path": str}`
- `keep_frame(candidate_path, prefix, timestamp, video_id, frames_dir) -> str` — **`video_id`
  added**; returns the kept file name (embed path built by the tool wrapper).
- `frame_select`: `laplacian_variance(img)`, `dhash(img)`, `hamming(a,b)`,
  `refine_candidates(cands, budget)`, `build_montage(cands, out_path)`.
- In-process tools: `select_keyframes` returns candidates + `montage_path`; `keep_frame` gains
  `video_id`. `note-writing.md` Visuals section updated: read the montage, pick the best index,
  `keep_frame` it.

### 3.6 Thresholds (defaults, pinned in the plan; module constants, not config — YAGNI)
`BLUR_FLOOR` (variance-of-Laplacian), `DUP_DISTANCE` (dHash Hamming), montage grid width. Tuned
against synthetic tests and the short e2e.

## 4. Stream B — Frame folder structure

`keep_frame` writes to `Attachments/frames/<video_id>/<name>_<ts>.jpg` (was flat). One video →
one folder; deleting a source removes its whole frame folder. Embed path becomes
`Attachments/frames/<video_id>/<name>.jpg`. `video_id` is `video_path.stem` (yt-dlp `%(id)s`),
passed by the orchestrator from `prepare_video`. `_work` is unchanged and still auto-cleaned by
`clean_frame_work`.

## 5. Stream C — Prose (Feynman-plain)

### 5.1 Extend `slop_check` (`src/study_notes/slop_check.py`)
Three new rule groups the current regexes miss:
- **cliché-word** — high-signal AI tells: `delve`, `tapestry`, `leverage`, `seamless`, `elevate`,
  `in the realm of`, `it's important to note`, `boasts`, `underscores`, `a rich tapestry`. (Pick
  high-signal words + multiword phrases; avoid legitimately-technical words like "robust"/
  "navigate"/"crucial" to limit false positives. `slop_check` is a soft backstop, not a hard gate.)
- **em-dash-overuse** — one finding if the note has more than `MAX_EM_DASHES` em-dashes.
- **hedging** — `it's worth noting`, `it is worth noting`, `arguably`, `to some extent`,
  `in many ways`.
Includes **negative** tests: ordinary technical prose must not trip these.

### 5.2 Positive voice in `prompts/note-writing.md`
Add a concrete **Feynman-plain** voice description (plain words; build one mental picture; short
declaratives; concrete nouns; warm, not chatty; no meta-commentary) plus the approved exemplar as
a few-shot. Point the existing "Do this" rules at the voice.

### 5.3 Keep guide and checker in sync (`prompts/anti-slop.md`)
Add the cliché wordlist + hedging to the guide (em-dash restraint is already there).

## 6. Dependencies
Add **`pillow`** (image read, Laplacian, dHash, montage). `numpy` is already present.

## 7. Error handling (all best-effort — never block a note)
- Unreadable/failed candidate image → skip it with a warning; continue with the rest.
- `keep_frame` dedup hash error → fall back to keeping the frame (never lose a frame to a hash
  error).
- Any frame step failing → the note is still written from the transcript, as today.

## 8. Testing

**Unit (synthetic images via Pillow — no LLM, no agentic run):**
- `frame_select`: blur filter drops a Gaussian-blurred copy of a sharp frame; dedup collapses a
  duplicated frame and keeps the settled/sharper one; `refine_candidates` respects budget;
  `build_montage` yields an image with the expected cell count.
- `keep_frame`: writes under `<video_id>/`; skips a pHash-duplicate and returns the existing path.
- `slop_check`: each new rule flags its pattern; negative tests confirm clean technical prose is
  not flagged.
- Prompt-content: `note-writing.md` contains the voice exemplar and the montage/index instruction.

**Docker:** update the existing `select_keyframes` docker test for the new return shape.

**End-to-end (agentic — ONLY with the user's explicit go-ahead, to conserve tokens):** a single
dry-run on a **short** visual, captioned video —
`https://www.youtube.com/watch?v=wbh3SjzydnQ` ("What does the liver do?", TED-Ed, **3:25**,
animated, English captions). Confirms the montage flow, per-video folder, deduped/settled embeds,
and the Feynman voice. Duration was verified via yt-dlp metadata (no token cost).

## 9. Open items folded into implementation
- Exact threshold values (`BLUR_FLOOR`, `DUP_DISTANCE`, `MAX_EM_DASHES`, montage width) pinned in
  the plan with defaults and tuned against the synthetic tests + short e2e.
- Final cliché wordlist pinned in the plan (high-signal only, to bound false positives).
