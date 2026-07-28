# Video-Ingestion Upgrade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Two-phase frame handling (local scene-select+dedup → multimodal Claude decision) and a local key-free Whisper fallback, on the existing orchestrator-worker engine.

**Architecture:** Phase 1 = Docker ffmpeg `mpdecimate` selects visually-distinct candidate frames per topic window (validated); Phase 2 = the extractor subagent (given the `Read` tool) sees the candidates, transcribes visual info into the note text, and keeps the few worth embedding. `fetch_youtube_transcript` gains an mlx-whisper fallback. Reuses tools/vault/engine.

**Tech Stack:** Python 3.12+, Docker ffmpeg (existing), `mlx-whisper` + `soundfile` (new), the Agent SDK.

## Global Constraints

- Phase 1 is **local, free, no OCR** — visual selection only via `mpdecimate`. Validated ffmpeg: `-ss START -to END -i video -vf "mpdecimate,scale=512:-1,showinfo" -vsync vfr -q:v 3 cand_%03d.jpg`; parse `pts_time:` from stderr; subsample to budget in Python.
- Phase 2 = the extractor sees candidates via the built-in `Read` tool and decides (transcribe-into-text + keep the few worth embedding). No OCR/Tesseract.
- Whisper is **local, key-free, lazy**: audio → 16 kHz mono wav (Docker ffmpeg) → load to float32 numpy (`soundfile`) → `mlx_whisper.transcribe(array, path_or_hf_repo=<config model>)`. Do NOT rely on host ffmpeg (we only have Docker ffmpeg) — hence the wav→numpy hop.
- All frame/whisper failures degrade gracefully — the note is still written from the transcript.
- Reuse `download_video`, `_docker_ffmpeg`, `VaultWriter`, the engine. Vault safety / dedup / record-from-`notes.source` unchanged.
- No API keys. TDD; commit after green. DRY, YAGNI.

---

### Task 1: Phase-1 keyframe selection + keep_frame (frames.py)

**Files:** Modify `src/study_notes/tools/frames.py`; Create `tests/tools/test_keyframes.py`.

**Interfaces:**
- `select_keyframes(video_path: Path, start: str, end: str, budget: int, out_dir: Path) -> list[dict]` — returns `[{"path": Path, "timestamp": "HH:MM:SS"}]`, visually-distinct (mpdecimate), scoped to `[start,end]`, subsampled to ≤`budget`, 512px, written into `out_dir`.
- `keep_frame(candidate_path: Path, prefix: str, timestamp: str, frames_dir: Path) -> str` — copies a chosen candidate to `frames_dir` as `frame_filename(prefix, timestamp)`, returns that filename. Raises `FrameExtractionError` on failure.
- Reuse `_docker_ffmpeg`, `frame_filename`, `FrameExtractionError`.

- [ ] **Step 1: Write the failing test**

`tests/tools/test_keyframes.py`:
```python
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from study_notes.tools.frames import keep_frame, select_keyframes


def test_keep_frame_copies_into_frames_dir(tmp_path):
    cand = tmp_path / "cand_001.jpg"; cand.write_bytes(b"\xff\xd8\xff")
    frames_dir = tmp_path / "frames"; frames_dir.mkdir()
    name = keep_frame(cand, "raft", "00:01:23", frames_dir)
    assert name == "raft_00-01-23.jpg"
    assert (frames_dir / name).exists()


needs_docker = pytest.mark.skipif(shutil.which("docker") is None, reason="docker not installed")


@pytest.fixture
def work_dir():
    d = Path("tests/.work") / uuid4().hex
    d.mkdir(parents=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def scenes_video(work_dir):
    from study_notes.tools.frames import _docker_ffmpeg
    _docker_ffmpeg(work_dir, [
        "-f", "lavfi", "-i", "color=c=red:s=320x240:d=2,format=yuv420p",
        "-f", "lavfi", "-i", "color=c=green:s=320x240:d=2,format=yuv420p",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2,format=yuv420p",
        "-filter_complex", "[0][1][2]concat=n=3:v=1", "/work/scenes.mp4", "-y",
    ])
    return work_dir / "scenes.mp4"


@pytest.mark.docker
@needs_docker
def test_select_keyframes_dedups_distinct_scenes(scenes_video, work_dir):
    out = work_dir / "cands"; out.mkdir()
    cands = select_keyframes(scenes_video, "00:00:00", "00:00:06", budget=10, out_dir=out)
    assert 2 <= len(cands) <= 4          # ~3 distinct held scenes (deduped)
    assert all(c["path"].exists() for c in cands)
    assert all(c["timestamp"].count(":") == 2 for c in cands)


@pytest.mark.docker
@needs_docker
def test_select_keyframes_respects_budget(scenes_video, work_dir):
    out = work_dir / "c2"; out.mkdir()
    cands = select_keyframes(scenes_video, "00:00:00", "00:00:06", budget=2, out_dir=out)
    assert len(cands) <= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_keyframes.py::test_keep_frame_copies_into_frames_dir -v`
Expected: FAIL (`ImportError: select_keyframes`).

- [ ] **Step 3: Write minimal implementation**

Append to `src/study_notes/tools/frames.py`:
```python
import re
import shutil


def _fmt_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def select_keyframes(video_path: Path, start: str, end: str, budget: int,
                     out_dir: Path) -> list[dict]:
    """Phase 1: visually-distinct candidate frames (mpdecimate), window-scoped, budget-capped."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work = video_path.parent
    # Frames go to out_dir if it's the same mount; keep it under the video's dir for one mount.
    rel = out_dir.name
    proc = _docker_ffmpeg(work, [
        "-ss", start, "-to", end, "-i", f"/work/{video_path.name}",
        "-vf", "mpdecimate,scale=512:-1,showinfo", "-vsync", "vfr", "-q:v", "3",
        f"/work/{rel}/cand_%03d.jpg", "-y",
    ])
    if proc.returncode != 0:
        raise FrameExtractionError(
            f"select_keyframes failed: {proc.stderr.decode(errors='replace')[-300:]}")
    times = [float(t) for t in re.findall(r"pts_time:([0-9.]+)",
                                          proc.stderr.decode(errors="replace"))]
    frames = sorted(out_dir.glob("cand_*.jpg"))
    cands = [{"path": p, "timestamp": _fmt_ts(times[i] if i < len(times) else 0.0)}
             for i, p in enumerate(frames)]
    if len(cands) > budget:  # uniform subsample down to budget
        step = len(cands) / budget
        cands = [cands[int(i * step)] for i in range(budget)]
    return cands


def keep_frame(candidate_path: Path, prefix: str, timestamp: str, frames_dir: Path) -> str:
    frames_dir.mkdir(parents=True, exist_ok=True)
    name = frame_filename(prefix, timestamp)
    try:
        shutil.copyfile(candidate_path, frames_dir / name)
    except OSError as e:
        raise FrameExtractionError(f"keep_frame failed for {candidate_path}: {e}") from e
    return name
```
**Note:** `select_keyframes` requires `out_dir` to be a subdirectory of `video_path.parent` (single Docker mount). The caller (Task 3 tool) creates `out_dir` under the video's work dir. If the Step-5 run shows the frames didn't land, adjust the mount/paths so ffmpeg writes into the mounted `out_dir` and the glob finds them.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tools/test_keyframes.py -v`
Expected: PASS (4 passed; the 3 docker tests run if docker is up + image pulled).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/tools/frames.py tests/tools/test_keyframes.py
git commit -m "feat: Phase-1 select_keyframes (mpdecimate) + keep_frame"
```

---

### Task 2: Local Whisper fallback (youtube.py)

**Files:** Modify `pyproject.toml` (deps), `src/study_notes/tools/youtube.py`; Create `tests/tools/test_whisper.py`.

**Interfaces:**
- `_segments_to_result(url, video_id, title, upload_date, whisper_out: dict) -> TranscriptResult` — pure; maps mlx-whisper `{"segments":[{"start","end","text"}]}` to `TranscriptResult` (`start` → `"HH:MM:SS"`).
- `transcribe_audio_local(wav_path: Path, model: str) -> dict` — loads the 16 kHz mono wav to float32 numpy (`soundfile`) and calls `mlx_whisper.transcribe(array, path_or_hf_repo=model)`; lazy import.
- `fetch_youtube_transcript(url, *, tmp_dir=None, whisper_model: str | None = None)` — on `TranscriptUnavailable`, if `whisper_model` is set, download audio → Docker ffmpeg to 16 kHz mono wav → `transcribe_audio_local` → `_segments_to_result`. On any Whisper failure, re-raise `TranscriptUnavailable`.

- [ ] **Step 1: Add deps**

`pyproject.toml` dependencies: add `"mlx-whisper>=0.4"`, `"soundfile>=0.12"`. Run `uv pip install -e ".[dev]"`.

- [ ] **Step 2: Write the failing test**

`tests/tools/test_whisper.py`:
```python
from study_notes.tools.youtube import TranscriptResult, _segments_to_result


def test_segments_to_result_maps_seconds_to_hhmmss():
    out = {"segments": [{"start": 0.0, "end": 2.0, "text": "hello"},
                        {"start": 83.5, "end": 86.0, "text": "world"}]}
    r = _segments_to_result("u", "vid", "T", "2025-11-14", out)
    assert isinstance(r, TranscriptResult)
    assert r.segments[0].start == "00:00:00" and r.segments[0].text == "hello"
    assert r.segments[1].start == "00:01:23" and r.segments[1].text == "world"
    assert r.title == "T" and r.upload_date == "2025-11-14"


def test_segments_to_result_empty_raises():
    import pytest

    from study_notes.tools.youtube import TranscriptUnavailable
    with pytest.raises(TranscriptUnavailable):
        _segments_to_result("u", "v", "T", None, {"segments": []})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_whisper.py -v`
Expected: FAIL (`ImportError: _segments_to_result`).

- [ ] **Step 4: Write minimal implementation**

Add to `src/study_notes/tools/youtube.py` (reuse existing `TranscriptSegment`, `TranscriptResult`, `TranscriptUnavailable`, `_fmt_upload_date`):
```python
def _secs_to_hhmmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _segments_to_result(url: str, video_id: str, title: str,
                        upload_date: str | None, whisper_out: dict) -> TranscriptResult:
    segs = [TranscriptSegment(start=_secs_to_hhmmss(s["start"]), text=s["text"].strip())
            for s in whisper_out.get("segments", []) if s.get("text", "").strip()]
    if not segs:
        raise TranscriptUnavailable(url)
    return TranscriptResult(url=url, video_id=video_id, title=title,
                            upload_date=upload_date, segments=segs)


def transcribe_audio_local(wav_path: Path, model: str) -> dict:
    import mlx_whisper
    import soundfile as sf

    audio, _ = sf.read(str(wav_path), dtype="float32")  # 16 kHz mono
    return mlx_whisper.transcribe(audio, path_or_hf_repo=model)
```
Then wire the fallback into `fetch_youtube_transcript`: add param `whisper_model: str | None = None`; wrap the existing "no captions" raise so that, before raising `TranscriptUnavailable`, if `whisper_model`:
```python
        if whisper_model:
            from study_notes.tools._ytdlp import quiet_opts, stdout_to_stderr
            from study_notes.tools.frames import _docker_ffmpeg
            aopts = quiet_opts({"format": "bestaudio/best",
                                "outtmpl": str(work / "%(id)s.%(ext)s")})
            with stdout_to_stderr(), yt_dlp.YoutubeDL(aopts) as ydl:
                info = ydl.extract_info(url, download=True)
            src = sorted(work.glob(f"{info.get('id','')}*"))
            if src:
                wav = work / "audio16k.wav"
                _docker_ffmpeg(work, ["-i", f"/work/{src[0].name}", "-vn", "-ac", "1",
                                      "-ar", "16000", f"/work/{wav.name}", "-y"])
                try:
                    out = transcribe_audio_local(wav, whisper_model)
                    return _segments_to_result(url, info.get("id",""), info.get("title",""),
                                               _fmt_upload_date(info.get("upload_date")), out)
                except Exception:
                    pass  # fall through to TranscriptUnavailable
        raise TranscriptUnavailable(url)
```
(Place this at the point the function currently raises `TranscriptUnavailable` for missing captions. Keep the existing structured-caption path unchanged.)

- [ ] **Step 5: Run tests (mapping only; real transcription is manual)**

Run: `uv run pytest tests/tools/test_whisper.py -v`
Expected: PASS (2 passed). Do NOT run real mlx-whisper here (downloads a model).

- [ ] **Step 6: Register `[whisper]` config (Task 3 wires it into Config)**

Leave a note; the actual config field lands in Task 3.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/study_notes/tools/youtube.py tests/tools/test_whisper.py
git commit -m "feat: local mlx-whisper fallback for caption-less videos"
```

---

### Task 3: Config + swap the agent frame tools

**Files:** Modify `src/study_notes/config.py`, `config.toml`, `tests/fixtures/config_ok.toml`, `tests/test_config.py`, `src/study_notes/agent/tools.py`, `tests/agent/test_tools.py`.

**Interfaces:**
- `Config` gains `frames: dict` (from `[frames]`, e.g. `{"budget": 10, "enabled": True}`) and `whisper_model: str | None` (from `[whisper].model`). `load_config` reads both (defaults: `frames={}`, `whisper_model=None`).
- `agent/tools.py` `build_tool_server` replaces the `extract_frame` tool with three tools closing over `ctx`: `prepare_video(url) -> {"video_id","video_path"}` (download once into `<vault>/Attachments/frames/_work/<id>/`), `select_keyframes(video_path, start, end, budget) -> [{path,timestamp}]` (writes candidates under that work dir), `keep_frame(candidate_path, prefix, timestamp) -> {"embed_path"}` (into `Attachments/frames/`). `fetch_youtube_transcript` tool now passes `whisper_model=ctx.config.whisper_model`.

- [ ] **Step 1: Config — failing test**

In `tests/fixtures/config_ok.toml` add:
```toml
[frames]
budget = 10
enabled = true

[whisper]
model = "mlx-community/whisper-small"
```
In `tests/test_config.py::test_load_config_reads_all_fields` add:
```python
    assert cfg.frames["budget"] == 10
    assert cfg.whisper_model == "mlx-community/whisper-small"
```

- [ ] **Step 2: Run → RED**

Run: `uv run pytest tests/test_config.py -v` → FAIL.

- [ ] **Step 3: Config — implement**

In `src/study_notes/config.py`: add `frames: dict` and `whisper_model: str | None = None` fields (both defaulted so existing `Config(...)` calls don't break — put defaulted fields last), and in `load_config`:
```python
        frames=dict(data.get("frames", {})),
        whisper_model=data.get("whisper", {}).get("model"),
```
Add the same `[frames]`/`[whisper]` blocks to the real `config.toml`.

- [ ] **Step 4: Swap the frame tools — failing test**

In `tests/agent/test_tools.py`, replace the `extract_frame` expectations: add a test that `build_tool_server` exposes `prepare_video`, `select_keyframes`, `keep_frame` (and no longer `extract_frame`):
```python
def test_tool_server_has_new_frame_tools(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server
    _, fns = build_tool_server(_ctx(tmp_path, db_conn))
    assert {"prepare_video", "select_keyframes", "keep_frame"} <= set(fns)
    assert "extract_frame" not in fns
```
(Reuse the file's existing `_ctx` helper; if `_ctx`'s `Config(...)` needs the new fields, they default.)

- [ ] **Step 5: Run → RED**

Run: `uv run pytest tests/agent/test_tools.py::test_tool_server_has_new_frame_tools -v` → FAIL.

- [ ] **Step 6: Implement the tool swap**

In `src/study_notes/agent/tools.py`, remove the `extract_frame` tool and add three (all `async def`, wrapped via `tool(...)`, plain fns in `fns`), closing over `ctx`. Frames work dir: `ctx.config.vault_path / ctx.config.attachments_dir / ctx.config.frames_subdir`.
```python
    from pathlib import Path
    from study_notes.tools import frames as fr

    frames_dir = ctx.config.vault_path / ctx.config.attachments_dir / ctx.config.frames_subdir

    @tool("prepare_video", "Download the video once so frames can be selected.", {"url": str})
    async def prepare_video(args: dict) -> dict:
        work = frames_dir / "_work"
        video = fr.download_video(args["url"], work)
        return _ok({"video_id": video.stem, "video_path": str(video)})

    @tool("select_keyframes",
          "Phase 1: select visually-distinct candidate frames in a time window.",
          {"video_path": str, "start": str, "end": str, "budget": int})
    async def select_keyframes(args: dict) -> dict:
        vp = Path(args["video_path"])
        out = vp.parent / f"cands_{args['start'].replace(':','')}_{args['end'].replace(':','')}"
        cands = fr.select_keyframes(vp, args["start"], args["end"], int(args["budget"]), out)
        return _ok([{"candidate_path": str(c["path"]), "timestamp": c["timestamp"]} for c in cands])

    @tool("keep_frame", "Keep a chosen candidate frame (embed it in the vault).",
          {"candidate_path": str, "prefix": str, "timestamp": str})
    async def keep_frame(args: dict) -> dict:
        name = fr.keep_frame(Path(args["candidate_path"]), args["prefix"],
                             args["timestamp"], frames_dir)
        return _ok({"embed_path": f"{ctx.config.attachments_dir}/{ctx.config.frames_subdir}/{name}"})
```
Update the `fetch_youtube_transcript` tool to pass `whisper_model=ctx.config.whisper_model`. Update the `fns` dict (drop `extract_frame`, add the three). Note: `frames_dir/_work` must be under `$HOME` (Colima mount) — the vault is, so fine.

- [ ] **Step 7: Run tests + full offline suite**

Run: `uv run pytest tests/test_config.py tests/agent/test_tools.py -v` → PASS.
Run: `uv run pytest -m "not slow and not network and not ffmpeg and not docker and not e2e" -q` → PASS (fix any test still referencing the old `extract_frame` tool or missing config fields).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: [frames]/[whisper] config; swap extract_frame for prepare_video/select_keyframes/keep_frame"
```

---

### Task 4: Give the extractor vision + two-phase prompts

**Files:** Modify `src/study_notes/agent/agents.py`, `src/study_notes/agent/engine.py`, `prompts/orchestrator.md`, `prompts/note-writing.md`; Modify `tests/agent/test_agents.py`, `tests/agent/test_engine.py`, `tests/test_agent_prompts.py`.

**Interfaces:**
- Extractor `AgentDefinition.tools` becomes `["Read", "mcp__study-notes__select_keyframes", "mcp__study-notes__keep_frame"]` (it reads candidate images and keeps chosen ones).
- Engine `allowed_tools` updated: drop `extract_frame`, add `prepare_video`/`select_keyframes`/`keep_frame` + `Read`.
- `orchestrator.md`: add the frame-gating + `prepare_video` step. `note-writing.md`: add the two-phase visual behaviour (view candidates via Read → transcribe visual info into the note text → keep the few worth embedding).

- [ ] **Step 1: Update failing tests**

`tests/agent/test_agents.py`: assert `"Read" in agents["extractor"].tools` and `"mcp__study-notes__select_keyframes" in agents["extractor"].tools`.
`tests/agent/test_engine.py`: assert `"mcp__study-notes__prepare_video" in opts.allowed_tools`, `"mcp__study-notes__keep_frame" in opts.allowed_tools`, `"Read" in opts.allowed_tools`, and `"mcp__study-notes__extract_frame" not in opts.allowed_tools`.
`tests/test_agent_prompts.py`: assert `prompts/orchestrator.md` mentions `prepare_video` and "visual"; `prompts/note-writing.md` mentions `select_keyframes`/`Read`/"embed".

- [ ] **Step 2: Run → RED**

Run: `uv run pytest tests/agent/test_agents.py tests/agent/test_engine.py tests/test_agent_prompts.py -v` → FAIL.

- [ ] **Step 3: Implement**

`agents.py` — extractor tools:
```python
        tools=["Read", f"{_SN}select_keyframes", f"{_SN}keep_frame"],
```
`engine.py` — `_TOOLS` list: replace `"extract_frame"` with `"prepare_video"`, `"select_keyframes"`, `"keep_frame"`; and `allowed_tools=[*_TOOLS, "WebSearch", "WebFetch", "Read"]`.

`prompts/orchestrator.md` — replace the old frame step with:
```markdown
4. **Frames (only if visual).** Judge whether the source is visual enough to warrant frames —
   a talking-head or interview usually is NOT; a lecture with slides/whiteboard/code IS. If not,
   skip frames entirely. If yes, call `prepare_video(url)` ONCE, and pass each extractor its
   topic's `[start,end]` window and a frame budget (smaller for less-visual topics).
```
`prompts/note-writing.md` — append:
```markdown

## Visuals (when given a video window + frame budget)
1. Call `select_keyframes(video_path, start, end, budget)` for your topic's window — this returns
   visually-distinct candidate frames.
2. **Read** each candidate image. Transcribe the useful on-screen content INTO the note text —
   a diagram's structure, a slide's points, on-screen code/formulas. The note must stand alone
   without the images.
3. `keep_frame(candidate_path, prefix, timestamp)` for the FEW frames genuinely worth seeing (a
   clean diagram, a key slide) and embed each with `![[<embed_path>]]`. Discard the rest — do not
   embed redundant or low-value frames.
```

- [ ] **Step 4: Run → GREEN + full offline suite**

Run: `uv run pytest tests/agent/ tests/test_agent_prompts.py -v` → PASS.
Run: `uv run pytest -m "not slow and not network and not ffmpeg and not docker and not e2e" -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: extractor gains Read + keyframe tools; two-phase frame prompts + gating"
```

---

### Task 5: End-to-end validation (manual)

- [ ] Run a real dry-run on a slide/diagram-heavy video and confirm: the orchestrator gates frames sensibly, `select_keyframes` produces a small deduped candidate set, the extractor reads them and transcribes visual content into the note text, and only a few frames are kept. Then a real (non-dry) run writes the note + frames. Time it. (Whisper path validated separately on a caption-less video.)

## Self-Review

- Phase 1 (local visual selection, no OCR) → Task 1 (`select_keyframes` mpdecimate) + Task 4 (gating). ✓
- Phase 2 (Claude sees candidates, transcribes into text, keeps few) → Task 3 (`keep_frame` tool) + Task 4 (Read + note-writing guide). ✓
- Local key-free Whisper → Task 2 (mlx-whisper via wav→numpy, Docker ffmpeg) + Task 3 (config wiring). ✓
- Orchestrator gates frames; one download; budget → Tasks 3, 4. ✓
- Graceful degradation, vault safety unchanged → reused code; tools raise `FrameExtractionError`/`TranscriptUnavailable`, orchestrator/note still proceed. ✓
- Placeholder scan: the two "adjust at runtime" notes (Task 1 mount/glob, Task 2 fallback placement) are concrete, validated-recipe-backed checks. Type consistency: `select_keyframes`/`keep_frame` signatures consistent between frames.py (Task 1) and the tools (Task 3); tool names consistent across Tasks 3/4; `whisper_model` threaded config→tool→fetch.
