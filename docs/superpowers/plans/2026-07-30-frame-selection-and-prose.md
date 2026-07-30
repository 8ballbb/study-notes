# Frame-Selection Quality, Frame Folders & Prose Voice — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve keyframe selection (settled + sharp + de-duplicated, chosen from a montage), store frames per-video for easy cleanup, and give notes a concrete Feynman-plain voice with a stronger slop checker.

**Architecture:** ffmpeg still extracts candidates; a new pure `tools/frame_select.py` (numpy + Pillow) filters blur, de-duplicates via dHash keeping the settled/sharpest frame, caps to budget, and builds one labeled montage. `select_keyframes` returns candidates + montage; the extractor reads the single montage and keeps the best index. `keep_frame` writes under `Attachments/frames/<video_id>/` and skips perceptual duplicates. `slop_check` gains cliché/em-dash/hedging rules; `note-writing.md` gains the voice.

**Tech Stack:** Python 3.13, numpy, Pillow, Docker ffmpeg (`jrottenberg/ffmpeg:6.1-alpine`), pytest, claude-agent-sdk.

## Global Constraints

- Frame refinement is **local, key-free**: numpy + Pillow only. No OCR/Tesseract, no ML models, no network.
- Every frame step is **best-effort**: on any failure, skip frames and still write the note from the transcript.
- Constants (module-level, not config): `BLUR_FLOOR = 100.0`, `DUP_DISTANCE = 10` (dHash 64-bit Hamming), `MONTAGE_COLS = 3`, `MAX_EM_DASHES = 4`.
- Frame folder layout is `Attachments/frames/<video_id>/<name>_<ts>.jpg`; `<video_id>` is `video_path.stem`.
- `slop_check` is a **soft backstop**, not a hard gate — cliché list is high-signal only, and every new rule has a negative test proving ordinary technical prose is not flagged.
- Voice is **Feynman-plain**; the exemplar is fixed in Task 6.
- Docker/e2e: unit tests are synthetic and token-free. The single agentic e2e (`wbh3SjzydnQ`, 3:25) runs **only with explicit user go-ahead**.

---

### Task 1: `frame_select` metrics + refinement

**Files:**
- Create: `src/study_notes/tools/frame_select.py`
- Modify: `pyproject.toml:6-16` (add deps)
- Test: `tests/tools/test_frame_select.py`

**Interfaces:**
- Produces: `laplacian_variance(img: Image.Image) -> float`; `dhash(img: Image.Image, size: int = 8) -> int`; `hamming(a: int, b: int) -> int`; `refine_candidates(candidates: list[dict], budget: int) -> list[dict]` where each candidate is `{"path": Path, "timestamp": str}` and the returned list is filtered/deduped/budget-capped, ordered by timestamp.

- [ ] **Step 1: Add dependencies.** In `pyproject.toml`, add to the `dependencies` list:
```
    "numpy>=1.26",
    "pillow>=10.0",
```
Run: `uv sync` (Expected: resolves, installs pillow + numpy).

- [ ] **Step 2: Write failing tests** at `tests/tools/test_frame_select.py`:
```python
from pathlib import Path

from PIL import Image
import numpy as np


def _sharp(tmp: Path, name: str, seed: int) -> Path:
    rng = np.random.default_rng(seed)
    arr = (rng.integers(0, 256, size=(64, 64, 3))).astype("uint8")
    p = tmp / name
    Image.fromarray(arr).save(p)
    return p


def _blurred(tmp: Path, name: str, seed: int) -> Path:
    from PIL import ImageFilter
    rng = np.random.default_rng(seed)
    arr = (rng.integers(0, 256, size=(64, 64, 3))).astype("uint8")
    p = tmp / name
    Image.fromarray(arr).filter(ImageFilter.GaussianBlur(6)).save(p)
    return p


def test_laplacian_variance_sharp_beats_blurred(tmp_path):
    from study_notes.tools.frame_select import laplacian_variance
    sharp = laplacian_variance(Image.open(_sharp(tmp_path, "s.png", 1)))
    blur = laplacian_variance(Image.open(_blurred(tmp_path, "b.png", 1)))
    assert sharp > blur


def test_dhash_identical_zero_distance(tmp_path):
    from study_notes.tools.frame_select import dhash, hamming
    a = Image.open(_sharp(tmp_path, "a.png", 7))
    assert hamming(dhash(a), dhash(a.copy())) == 0


def test_dhash_distinct_images_have_distance(tmp_path):
    from study_notes.tools.frame_select import dhash, hamming
    a = dhash(Image.open(_sharp(tmp_path, "a.png", 1)))
    b = dhash(Image.open(_sharp(tmp_path, "b.png", 2)))
    assert hamming(a, b) > 10


def test_refine_drops_blurry_and_dedups_keeping_last(tmp_path):
    from study_notes.tools.frame_select import refine_candidates
    sharp1 = _sharp(tmp_path, "t1.png", 1)
    # near-duplicate of sharp1 (same seed, tiny brightness shift) at a later ts
    dup = _sharp(tmp_path, "t2.png", 1)
    blur = _blurred(tmp_path, "t3.png", 9)
    distinct = _sharp(tmp_path, "t4.png", 5)
    cands = [
        {"path": sharp1, "timestamp": "00:00:01"},
        {"path": dup, "timestamp": "00:00:02"},
        {"path": blur, "timestamp": "00:00:03"},
        {"path": distinct, "timestamp": "00:00:05"},
    ]
    out = refine_candidates(cands, budget=10)
    stamps = [c["timestamp"] for c in out]
    assert "00:00:03" not in stamps          # blurry dropped
    assert "00:00:01" not in stamps          # dedup kept the LAST of the run
    assert "00:00:02" in stamps and "00:00:05" in stamps


def test_refine_respects_budget(tmp_path):
    from study_notes.tools.frame_select import refine_candidates
    cands = [{"path": _sharp(tmp_path, f"f{i}.png", i), "timestamp": f"00:00:0{i}"}
             for i in range(1, 6)]
    out = refine_candidates(cands, budget=2)
    assert len(out) == 2
```
Run: `uv run pytest tests/tools/test_frame_select.py -q` (Expected: FAIL, module missing).

- [ ] **Step 3: Implement** `src/study_notes/tools/frame_select.py`:
```python
"""Local, key-free image refinement for keyframe candidates (numpy + Pillow)."""
from pathlib import Path

import numpy as np
from PIL import Image

BLUR_FLOOR = 100.0   # variance-of-Laplacian below this = blur/transition
DUP_DISTANCE = 10    # dHash (64-bit) Hamming distance below this = near-duplicate


def laplacian_variance(img: Image.Image) -> float:
    a = np.asarray(img.convert("L"), dtype=np.float64)
    if a.shape[0] < 3 or a.shape[1] < 3:
        return 0.0
    lap = (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1]
           + a[1:-1, :-2] + a[1:-1, 2:])
    return float(lap.var())


def dhash(img: Image.Image, size: int = 8) -> int:
    a = np.asarray(img.convert("L").resize((size + 1, size)), dtype=np.int16)
    diff = a[:, 1:] > a[:, :-1]
    bits = 0
    for v in diff.flatten():
        bits = (bits << 1) | int(v)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _load(path: Path):
    """Return (sharpness, dhash) or None if the image cannot be read."""
    try:
        with Image.open(path) as im:
            im.load()
            return laplacian_variance(im), dhash(im)
    except Exception:
        return None


def refine_candidates(candidates: list[dict], budget: int) -> list[dict]:
    scored = []
    for c in candidates:
        m = _load(c["path"])
        if m is not None:
            scored.append({**c, "sharp": m[0], "hash": m[1]})
    if not scored:
        return []
    # Blur filter — but never drop everything: if none clear the floor, keep the sharpest.
    sharp = [c for c in scored if c["sharp"] >= BLUR_FLOOR]
    if not sharp:
        sharp = [max(scored, key=lambda c: c["sharp"])]
    sharp.sort(key=lambda c: c["timestamp"])
    # Settled dedup: collapse consecutive near-duplicate runs, keep the LAST (settled).
    deduped = []
    for c in sharp:
        if deduped and hamming(deduped[-1]["hash"], c["hash"]) < DUP_DISTANCE:
            deduped[-1] = c  # keep the later, settled frame of the run
        else:
            deduped.append(c)
    # Budget cap: greedy farthest-point on dHash so we keep the most distinct set.
    if budget > 0 and len(deduped) > budget:
        chosen = [max(deduped, key=lambda c: c["sharp"])]
        while len(chosen) < budget:
            nxt = max((c for c in deduped if c not in chosen),
                      key=lambda c: min(hamming(c["hash"], s["hash"]) for s in chosen))
            chosen.append(nxt)
        deduped = sorted(chosen, key=lambda c: c["timestamp"])
    return [{"path": c["path"], "timestamp": c["timestamp"]} for c in deduped]
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/tools/test_frame_select.py -q` (Expected: PASS).

- [ ] **Step 5: Commit**
```bash
git add pyproject.toml uv.lock src/study_notes/tools/frame_select.py tests/tools/test_frame_select.py
git commit -m "feat(frames): frame_select metrics + blur/dedup/budget refinement"
```

---

### Task 2: `build_montage`

**Files:**
- Modify: `src/study_notes/tools/frame_select.py`
- Test: `tests/tools/test_frame_select.py`

**Interfaces:**
- Produces: `build_montage(candidates: list[dict], out_path: Path, cols: int = MONTAGE_COLS) -> Path`. Each candidate is `{"path": Path, "timestamp": str, "index": int}`; writes a labeled grid JPEG to `out_path` and returns it.

- [ ] **Step 1: Write failing test** (append to `tests/tools/test_frame_select.py`):
```python
def test_build_montage_creates_image_with_cells(tmp_path):
    from study_notes.tools.frame_select import build_montage
    cands = [{"path": _sharp(tmp_path, f"m{i}.png", i), "timestamp": f"00:00:0{i}",
              "index": i} for i in range(3)]
    out = build_montage(cands, tmp_path / "montage.jpg", cols=2)
    assert out.exists()
    from PIL import Image
    w, h = Image.open(out).size
    assert w > 0 and h > 0
```
Run: `uv run pytest tests/tools/test_frame_select.py::test_build_montage_creates_image_with_cells -q` (Expected: FAIL).

- [ ] **Step 2: Implement** — add `MONTAGE_COLS` constant and function to `frame_select.py`:
```python
MONTAGE_COLS = 3

from PIL import ImageDraw  # noqa: E402  (grouped with other PIL imports at top in practice)

_THUMB = 256


def build_montage(candidates: list[dict], out_path: Path,
                  cols: int = MONTAGE_COLS) -> Path:
    thumbs = []
    for c in candidates:
        with Image.open(c["path"]) as im:
            im = im.convert("RGB")
            im.thumbnail((_THUMB, _THUMB))
            cell = Image.new("RGB", (_THUMB, _THUMB + 18), (20, 20, 20))
            cell.paste(im, ((_THUMB - im.width) // 2, 0))
            ImageDraw.Draw(cell).text(
                (4, _THUMB + 3), f"[{c['index']}] {c['timestamp']}", fill=(255, 255, 255))
            thumbs.append(cell)
    if not thumbs:
        Image.new("RGB", (_THUMB, _THUMB), (20, 20, 20)).save(out_path)
        return out_path
    rows = (len(thumbs) + cols - 1) // cols
    cw, ch = thumbs[0].size
    sheet = Image.new("RGB", (cols * cw, rows * ch), (20, 20, 20))
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * cw, (i // cols) * ch))
    sheet.save(out_path, quality=85)
    return out_path
```
(Move `ImageDraw` into the top import line `from PIL import Image, ImageDraw` when implementing; shown inline here for clarity.)

- [ ] **Step 3: Run test** — Expected: PASS.

- [ ] **Step 4: Commit**
```bash
git add src/study_notes/tools/frame_select.py tests/tools/test_frame_select.py
git commit -m "feat(frames): labeled contact-sheet montage builder"
```

---

### Task 3: `select_keyframes` uses refinement + returns montage

**Files:**
- Modify: `src/study_notes/tools/frames.py:74-101` (`select_keyframes`)
- Test: `tests/tools/test_keyframes.py` (update for new return shape)

**Interfaces:**
- Consumes: `frame_select.refine_candidates`, `frame_select.build_montage`.
- Produces: `select_keyframes(video_path, start, end, budget, out_dir) -> dict` = `{"candidates": [{"path": Path, "timestamp": str, "index": int}], "montage_path": Path}`.

- [ ] **Step 1: Update the docker tests** in `tests/tools/test_keyframes.py` to the new shape (these are `@pytest.mark.docker`). Replace the three assertions that read the list directly:
```python
# was: cands = select_keyframes(...); assert 1 <= len(cands) <= 10
res = select_keyframes(scenes_video, "00:00:00", "00:00:06", budget=10, out_dir=out)
cands = res["candidates"]
assert 1 <= len(cands) <= 10
assert res["montage_path"].exists()
assert all("index" in c for c in cands)
```
Apply the same `res["candidates"]` swap to the budget test and the absolute-timestamp test.

- [ ] **Step 2: Run** `uv run pytest tests/tools/test_keyframes.py -q -m docker` (Expected: FAIL — select_keyframes still returns a list).

- [ ] **Step 3: Implement.** In `frames.py`, add `from study_notes.tools import frame_select` at the top, and change the tail of `select_keyframes` (after `cands = [...]` is built and budget-subsampled) to refine + montage + index:
```python
    # (existing) cands: list[{"path": Path, "timestamp": str}] from ffmpeg + pts parse
    refined = frame_select.refine_candidates(cands, budget)
    for i, c in enumerate(refined):
        c["index"] = i
    montage_path = out_dir / "montage.jpg"
    frame_select.build_montage(refined, montage_path)
    return {"candidates": refined, "montage_path": montage_path}
```
Remove the old uniform-subsample block (`if budget > 0 and len(cands) > budget: ...`) — `refine_candidates` now owns budgeting.

- [ ] **Step 4: Run** `uv run pytest tests/tools/test_keyframes.py -q -m docker` (Expected: PASS).

- [ ] **Step 5: Commit**
```bash
git add src/study_notes/tools/frames.py tests/tools/test_keyframes.py
git commit -m "feat(frames): select_keyframes refines candidates and returns a montage"
```

---

### Task 4: `keep_frame` — per-video folder + perceptual dedup

**Files:**
- Modify: `src/study_notes/tools/frames.py:104-111` (`keep_frame`)
- Test: `tests/tools/test_keyframes.py`

**Interfaces:**
- Consumes: `frame_select.dhash`, `frame_select.hamming`, `frame_select.DUP_DISTANCE`.
- Produces: `keep_frame(candidate_path, prefix, timestamp, video_id, frames_dir) -> str` — copies into `frames_dir/<video_id>/`, skips a near-duplicate already there, returns the file name.

- [ ] **Step 1: Write failing tests** (append to `tests/tools/test_keyframes.py`, NOT docker-marked — pure Pillow):
```python
def test_keep_frame_writes_under_video_id(tmp_path):
    from PIL import Image
    import numpy as np
    from study_notes.tools.frames import keep_frame
    src = tmp_path / "cand.jpg"
    Image.fromarray(np.random.default_rng(1).integers(0, 256, (64, 64, 3)).astype("uint8")).save(src)
    frames_dir = tmp_path / "frames"
    name = keep_frame(src, "liver", "00:00:05", "vid123", frames_dir)
    assert (frames_dir / "vid123" / name).exists()


def test_keep_frame_skips_perceptual_duplicate(tmp_path):
    from PIL import Image
    import numpy as np
    from study_notes.tools.frames import keep_frame
    arr = np.random.default_rng(2).integers(0, 256, (64, 64, 3)).astype("uint8")
    a = tmp_path / "a.jpg"; Image.fromarray(arr).save(a)
    b = tmp_path / "b.jpg"; Image.fromarray(arr).save(b)  # identical -> duplicate
    frames_dir = tmp_path / "frames"
    n1 = keep_frame(a, "liver", "00:00:05", "vid1", frames_dir)
    n2 = keep_frame(b, "liver", "00:00:09", "vid1", frames_dir)
    assert n1 == n2  # dedup returned the existing frame, no second file
    assert len(list((frames_dir / "vid1").glob("*.jpg"))) == 1
```
Run: `uv run pytest tests/tools/test_keyframes.py -q -k keep_frame` (Expected: FAIL — signature mismatch).

- [ ] **Step 2: Implement** — replace `keep_frame` in `frames.py`:
```python
def keep_frame(candidate_path: Path, prefix: str, timestamp: str,
               video_id: str, frames_dir: Path) -> str:
    from PIL import Image

    from study_notes.tools import frame_select

    target_dir = frames_dir / video_id
    target_dir.mkdir(parents=True, exist_ok=True)
    # Perceptual dedup: if a near-identical frame is already kept for this video, reuse it.
    try:
        with Image.open(candidate_path) as im:
            im.load()
            new_hash = frame_select.dhash(im)
        for existing in sorted(target_dir.glob("*.jpg")):
            with Image.open(existing) as ex:
                ex.load()
                if frame_select.hamming(new_hash, frame_select.dhash(ex)) < frame_select.DUP_DISTANCE:
                    return existing.name
    except Exception:
        pass  # hash failure must never lose a frame — fall through and keep it
    name = frame_filename(prefix, timestamp)
    try:
        shutil.copyfile(candidate_path, target_dir / name)
    except OSError as e:
        raise FrameExtractionError(f"keep_frame failed for {candidate_path}: {e}") from e
    return name
```

- [ ] **Step 3: Run** `uv run pytest tests/tools/test_keyframes.py -q -k keep_frame` (Expected: PASS).

- [ ] **Step 4: Commit**
```bash
git add src/study_notes/tools/frames.py tests/tools/test_keyframes.py
git commit -m "feat(frames): keep_frame writes per-video and skips perceptual duplicates"
```

---

### Task 5: Wire the new frame tools into the agent

**Files:**
- Modify: `src/study_notes/agent/tools.py:45-54` (select_keyframes + keep_frame wrappers), `:84-88` (tool schemas)
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `frames.select_keyframes` (dict return), `frames.keep_frame` (video_id arg).
- Produces (MCP tools): `select_keyframes(video_path, start, end, budget) -> {"candidates":[{candidate_path, timestamp, index}], "montage_path"}`; `keep_frame(candidate_path, prefix, timestamp, video_id) -> {"embed_path"}` where embed path is `<attachments_dir>/<frames_subdir>/<video_id>/<name>`.

- [ ] **Step 1: Write failing test** in `tests/test_tools.py` (follow the file's existing fixture pattern for building the server / calling `fns`):
```python
def test_keep_frame_tool_embed_path_includes_video_id(tmp_path, monkeypatch):
    # keep_frame tool returns an embed path scoped under the video_id folder
    import json
    from study_notes.agent import tools as t

    monkeypatch.setattr(t.fr, "keep_frame",
                        lambda cp, prefix, ts, vid, fd: "liver_00-00-05.jpg")
    server, fns = t.build_tool_server(_ctx(tmp_path))   # reuse this module's ctx helper
    out = asyncio.run(fns["keep_frame"]({"candidate_path": "/x/c.jpg", "prefix": "liver",
                                         "timestamp": "00:00:05", "video_id": "vidABC"}))
    payload = json.loads(out["content"][0]["text"])
    assert payload["embed_path"] == "Attachments/frames/vidABC/liver_00-00-05.jpg"
```
(If `test_tools.py` lacks a `_ctx`/config helper, copy the minimal `Config`/`EngineContext` construction from `tests/agent/test_engine.py`.)
Run: `uv run pytest tests/test_tools.py -q -k embed_path` (Expected: FAIL).

- [ ] **Step 2: Implement** — update the two wrappers in `agent/tools.py`:
```python
    async def select_keyframes(args: dict) -> dict:
        vp = Path(args["video_path"])
        out = vp.parent / f"cands_{args['start'].replace(':', '')}_{args['end'].replace(':', '')}"
        res = fr.select_keyframes(vp, args["start"], args["end"], int(args["budget"]), out)
        return _ok({
            "candidates": [{"candidate_path": str(c["path"]), "timestamp": c["timestamp"],
                            "index": c["index"]} for c in res["candidates"]],
            "montage_path": str(res["montage_path"]),
        })

    async def keep_frame(args: dict) -> dict:
        name = fr.keep_frame(Path(args["candidate_path"]), args["prefix"],
                             args["timestamp"], args["video_id"], frames_dir)
        return _ok({"embed_path":
                    f"{ctx.config.attachments_dir}/{ctx.config.frames_subdir}/{args['video_id']}/{name}"})
```
And update the `keep_frame` tool schema to add `video_id`:
```python
        tool("keep_frame", "Keep a chosen candidate frame (embed it in the vault).",
             {"candidate_path": str, "prefix": str, "timestamp": str, "video_id": str})(keep_frame),
```

- [ ] **Step 3: Run** `uv run pytest tests/test_tools.py -q -k embed_path` (Expected: PASS).

- [ ] **Step 4: Commit**
```bash
git add src/study_notes/agent/tools.py tests/test_tools.py
git commit -m "feat(agent): wire montage select_keyframes + per-video keep_frame tools"
```

---

### Task 6: Note-writing prompt — montage flow + Feynman-plain voice

**Files:**
- Modify: `prompts/note-writing.md`
- Test: `tests/test_agent_prompts.py`

**Interfaces:** none (prompt content).

- [ ] **Step 1: Write failing test** (append to `tests/test_agent_prompts.py`):
```python
def test_note_writing_has_montage_flow_and_voice():
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "montage" in t                 # contact-sheet selection
    assert "index" in t                   # pick the best index
    assert "video_id" in t                # keep_frame gets video_id
    assert "mental picture" in t          # Feynman-plain voice cue
```
Run: `uv run pytest tests/test_agent_prompts.py::test_note_writing_has_montage_flow_and_voice -q` (Expected: FAIL).

- [ ] **Step 2: Implement.** In `prompts/note-writing.md`, replace the numbered Visuals steps that read candidates one-by-one with the montage flow, and add a Voice section. Visuals steps become:
```markdown
3. **Extract only around each cue (narrow windows).** For each cue, call
   `select_keyframes(video_path, start, end, budget)` on a TIGHT window using transcript segment
   timestamps verbatim. It returns `candidates` (each with an `index`) and a `montage_path`.
4. **Pick from the montage.** `Read` the single `montage_path` image — a numbered grid of the
   candidates. Compare them and choose the one (rarely two) index that best shows the finished
   diagram/slide. Prefer a clean, settled frame.
5. **Backstop (only if told the topic is strongly visual)** and step-2 found no cues: take one
   light sample across the window the same way.
6. **Keep and transcribe.** For each chosen index, `keep_frame(candidate_path, prefix, timestamp,
   video_id)` (pass the `video_id` you were given) and embed with `![[<embed_path>]]`. Transcribe
   the frame's useful on-screen content INTO the note text so it stands alone; discard the rest.
```
Add a Voice section after `## Rules`:
```markdown
## Voice (Feynman-plain)
Write like a sharp person explaining an idea to a friend at a whiteboard — warm, not chatty.
- Plain words. Build ONE clear mental picture and extend it; don't stack metaphors.
- Short declaratives. Concrete nouns and numbers. No meta-commentary ("in this note we'll…").
- Exemplar of the target voice:
  > Think of every wire between two neurons as carrying a dial: its weight. A neuron adds up what
  > the layer below sends, each signal turned up or down by its dial. Paint those dials onto the
  > image: green where positive, red where negative. A green blob over one spot makes the neuron
  > light up when that spot is bright. Ring the green with red and it fires only when the middle
  > glows and the edges stay dark: you've built an edge finder.
```

- [ ] **Step 3: Run** `uv run pytest tests/test_agent_prompts.py -q` (Expected: PASS — new test + existing prompt tests).

- [ ] **Step 4: Commit**
```bash
git add prompts/note-writing.md tests/test_agent_prompts.py
git commit -m "feat(prompt): montage-based frame selection + Feynman-plain voice"
```

---

### Task 7: Extend `slop_check` + anti-slop guide

**Files:**
- Modify: `src/study_notes/slop_check.py`
- Modify: `prompts/anti-slop.md`
- Test: `tests/test_slop_check.py`

**Interfaces:**
- Consumes/Produces: `slop_check(text: str) -> list[SlopFinding]` (unchanged signature; new patterns `cliche-word`, `em-dash-overuse`, `hedging`).

- [ ] **Step 1: Write failing tests** (append to `tests/test_slop_check.py`):
```python
def test_flags_cliche_words():
    from study_notes.slop_check import slop_check
    pats = {f.pattern for f in slop_check("We delve into the rich tapestry of it.")}
    assert "cliche-word" in pats


def test_flags_em_dash_overuse():
    from study_notes.slop_check import slop_check
    text = "A — b — c — d — e — f."  # 5 em dashes > MAX_EM_DASHES
    assert any(f.pattern == "em-dash-overuse" for f in slop_check(text))


def test_flags_hedging():
    from study_notes.slop_check import slop_check
    assert any(f.pattern == "hedging" for f in slop_check("It's worth noting this is arguably true."))


def test_clean_technical_prose_not_flagged():
    from study_notes.slop_check import slop_check
    clean = ("A neuron sums the previous layer's activations, each scaled by a weight, then adds "
             "a bias and applies the sigmoid. The network has about 13,000 parameters.")
    assert slop_check(clean) == []
```
Run: `uv run pytest tests/test_slop_check.py -q` (Expected: new tests FAIL).

- [ ] **Step 2: Implement.** In `slop_check.py`, add three rules to `_RULES` and an em-dash count in `slop_check`:
```python
    ("cliche-word",
     re.compile(r"\b(delve|delving|tapestry|leverage|leveraging|seamless(ly)?|elevate|elevates|"
                r"boasts|underscore|underscores)\b|in the realm of|it'?s important to note|"
                r"a rich tapestry", re.I)),
    ("hedging",
     re.compile(r"\b(it'?s worth noting|it is worth noting|arguably|to some extent|"
                r"in many ways)\b", re.I)),
```
Add `MAX_EM_DASHES = 4` near the top, and at the end of `slop_check`, before `return findings`:
```python
    em = text.count("—")
    if em > MAX_EM_DASHES:
        findings.append(SlopFinding(pattern="em-dash-overuse", snippet=f"{em} em dashes"))
```

- [ ] **Step 3: Update the guide.** In `prompts/anti-slop.md`, under "Cut these patterns" add:
```markdown
- **Cliché words:** delve, tapestry, leverage, seamless, elevate, boasts, underscore, "in the realm of," "it's important to note." Use plain words.
- **Hedging:** "it's worth noting," "arguably," "to some extent," "in many ways." Commit to the claim.
```

- [ ] **Step 4: Run** `uv run pytest tests/test_slop_check.py -q` (Expected: PASS).

- [ ] **Step 5: Commit**
```bash
git add src/study_notes/slop_check.py prompts/anti-slop.md tests/test_slop_check.py
git commit -m "feat(slop): cliche-word, em-dash-overuse, hedging rules + guide"
```

---

## End-to-end validation (gated — do NOT run without explicit user go-ahead)

After all tasks, a single dry-run confirms the full flow on a **short** video (token-conscious):
```bash
uv run study-notes add "https://www.youtube.com/watch?v=wbh3SjzydnQ" --dry-run --category "Biology"
```
Confirm from the run + `~/vault/Attachments/frames/wbh3SjzydnQ/`: frames land under the `<video_id>`
folder, are deduped/settled, a montage was produced per window, the note prose reads Feynman-plain,
and `check_slop` stays clean. This run costs tokens — ask first.

## Notes for the executor
- Do NOT run the full pytest suite; it bundles the live-agentic `tests/test_engine_e2e.py::` test
  which spends tokens. Run only each task's named tests (all synthetic/Docker, token-free).
- `git clean` will wipe `.superpowers/sdd` scratch; the ledger lives there.
