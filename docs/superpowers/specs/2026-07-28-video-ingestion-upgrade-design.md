# Video-Ingestion Upgrade — Design Spec

**Date:** 2026-07-28
**Status:** Approved (verbally); implementing.
**Builds on:** the orchestrator-worker engine (`2026-07-27-notes-orchestrator-redesign-design.md`). Reuses Plans 1/2/2.5 + the Agent SDK engine. Prior art: [bradautomates/claude-video](https://github.com/bradautomates/claude-video) — techniques adopted, its skill **not** used.

## 1. Purpose

Two improvements to how video is turned into notes:

1. **Two-phase frame handling.** Replace the naive "grab one frame at a card's timestamp, embed a screenshot the model never sees" with: **Phase 1** — cheap local *visual* selection of candidate frames (scene-detect + dedup, no OCR); **Phase 2** — the extractor subagent *sees* the candidates (multimodal) and decides everything: transcribes the useful on-screen content **into the note text** (so notes are self-contained and searchable) and embeds only the handful of frames worth keeping.
2. **Local, key-free Whisper fallback** for caption-less videos, so they no longer fail.

## 2. Non-goals

- No OCR / Tesseract (Claude reads on-screen text far better in Phase 2). Frame *selection* is by visual distinctness, not text presence.
- No paid transcription APIs (Groq/OpenAI). Whisper is local.
- No change to retrieval, the vault, enrichment, ingestion dedup, or the CLI shell.
- Not routing through claude-video's `/watch` skill — we adopt its ffmpeg technique only.

## 3. Two-phase frame handling

### Phase 1 — candidate selection (local, free, no Claude)
For a topic's `[start, end]` window, extract a small set of visually-distinct candidate frames via Docker ffmpeg: **scene-change selection + `mpdecimate` dedup** (drops near-identical held-slide/paused frames, keeps one clean representative), capped at a per-topic **budget**, at ~512px width. Pure ffmpeg; no OCR, no model.

### Phase 2 — Claude decides (multimodal)
The extractor subagent, for its topic, **views** the candidates (via the built-in `Read` tool), then:
- transcribes the useful visual content into the note text (a diagram's structure, a slide's points, on-screen code/formulas) — **choice C: self-contained notes**;
- **keeps** the few frames genuinely worth seeing (a clean diagram, a key slide) by embedding them, and discards the rest.

### Cost control
- **Orchestrator gates frames.** Having read the transcript, it judges whether a source/topic is visual enough to warrant frames; a talking-head gets none (and no video download). This is the primary lever.
- **Phase 1 bounds what Claude sees** — a small deduped candidate set per topic, budget-capped (default ~8–12, scaled down by the orchestrator for less-visual topics).
- **One video download** shared by all parallel extractors; ~512px frames; `--no-frames` flag / config to disable.

## 4. Components

Replace the single `extract_frame` tool with three focused in-process tools, and give the extractor vision:

- **`prepare_video(url) -> video_id`** — downloads the video once (reuses `download_video`) into a shared work area, so parallel extractors don't each re-download. The orchestrator calls it only when it decides frames are warranted.
- **`select_keyframes(video_id, start, end, budget) -> [{candidate_path, timestamp}]`** — Phase 1. Docker ffmpeg scene-detect + `mpdecimate`, window-scoped, budget-capped, ~512px, into a temp candidates dir.
- **`keep_frame(candidate_path, prefix) -> {embed_path}`** — moves a chosen candidate into the vault `Attachments/frames/` (stable name), returns the `Attachments/frames/<name>` embed path. Unchosen candidates are cleaned up when the run ends.
- **Extractor subagent** gains the built-in **`Read`** tool and two-phase instructions (its note-writing guide adds the visual-transcription behaviour). Model stays cheap (sonnet does vision).
- The old `extract_frame` tool is removed from the tool set (the underlying `frames.extract_frame` may stay for tests or be superseded by `select_keyframes`).

## 5. Local Whisper fallback

`fetch_youtube_transcript` gains a fallback branch:
- **Trigger:** the existing "no English captions" path (`TranscriptUnavailable`) — rare.
- **Audio:** extract mono 16 kHz via Docker ffmpeg (`-vn -ac 1 -ar 16000`) from the downloaded audio/video.
- **Transcribe:** **`mlx-whisper`** with a **small/base** model (config-selectable, e.g. `mlx-community/whisper-small`), **lazy-loaded** on first use — GPU-accelerated on Apple Silicon, key-free, offline, light.
- **Output:** map mlx-whisper segments (`start`/`end` seconds + text) to our `TranscriptSegment` (`"HH:MM:SS"`) → same `TranscriptResult`. The rest of the pipeline is untouched.
- **Config:** an `[whisper]` section (`model = "mlx-community/whisper-small"`).
- New dependency: `mlx-whisper` (pip). No API keys.

## 6. Data flow

```
orchestrator (opus): decompose → topics with [start,end]; judge "is this visual?"
  ├─ transcript: fetch_youtube_transcript  (captions → else local Whisper fallback)
  └─ if visual: prepare_video(url)  [once]
per topic in parallel — extractor (sonnet, multimodal):
  select_keyframes(video, start, end, budget)   # Phase 1: local, deduped candidates
  Read the candidates                            # Phase 2: Claude sees them
  write note: transcribe visual info into text; keep_frame(...) the few worth embedding
```

## 7. Error handling (all graceful — never blocks the note)

- No captions **and** Whisper fails/unavailable → clean `TranscriptUnavailable`, logged; that source is skipped.
- `prepare_video` / `select_keyframes` / `keep_frame` failure → skip frames for that topic with a warning; the note is still written from the transcript.
- Whisper model load/download failure → falls back to `TranscriptUnavailable` with a clear message.
- Vault safety (non-destructive, atomic, read-back), ingestion dedup, and record-from-`notes.source` unchanged.

## 8. Testing

- **`select_keyframes`** — against a generated sample clip with scene changes (Docker ffmpeg); assert deduped + budget-capped candidate set. (`docker`)
- **`keep_frame`** — moves a candidate into the vault frames dir, returns the embed path; refuses to escape the vault. (unit)
- **Whisper segment→`TranscriptResult` mapping** — pure, unit-tested; real `mlx-whisper` transcription against a tiny generated audio clip → `slow`.
- **In-process tool wrappers** (prepare_video/select_keyframes/keep_frame) — unit/integration as their I/O allows.
- **Multimodal extractor behaviour + orchestrator frame-gating** — validated by the `e2e` run (agentic; not unit-tested).
- **Prompt updates** (orchestrator frame-gating step; extractor two-phase + visual-transcription in the note-writing guide) — light content tests.

## 9. Config additions

```toml
[frames]
budget = 10            # default per-topic candidate cap; orchestrator scales down
enabled = true         # --no-frames overrides per run

[whisper]
model = "mlx-community/whisper-small"   # local, lazy
```

## 10. Open items folded into implementation

- Exact ffmpeg filter strings for scene-detect + `mpdecimate` + budget capping (pinned in the plan; validated against a sample clip).
- The exact `mlx-whisper` transcribe call + segment shape (verified against the installed package).
- How the extractor is handed candidate paths (via `select_keyframes` result in its own turn) and enabling `Read` for that subagent in the SDK options.
