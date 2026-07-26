# Study Notes — Plan 2: MCP Tool Server

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the tool the agent (Claude Code) will call — a local MCP server offering typed tools for YouTube transcript fetching, category listing, category-scoped vault search, video-frame extraction, and non-destructive vault writes — built on Plan 1's core.

**Architecture:** Tool *logic* lives in plain, directly-testable functions under `src/study_notes/tools/`; the MCP server (`mcp_server.py`) is a thin adapter that wires config + a shared `VaultIndex` and registers each function as an `@mcp.tool()`. Network/binary-dependent pieces (yt-dlp, ffmpeg) are split into a pure, unit-tested core (VTT parsing, path/MOC logic) plus a thin integration wrapper, so most tests run offline and deterministically.

**Tech Stack:** Python 3.12+, `mcp` (official SDK, `FastMCP`, pinned `<2`), `yt-dlp`, `ffmpeg` (system binary), plus Plan 1's `psycopg`/`pgvector`/`FlagEmbedding`. Builds on `study_notes.{config,models,renderer,embedding,db,vault_index}`.

## Global Constraints

- Python 3.12+; macOS/arm64.
- MCP server uses `from mcp.server.fastmcp import FastMCP`; pin `mcp>=1.2,<2` (a v2 rework lands ~2026-07-27; avoid the churn).
- Transcripts via **yt-dlp in VTT format** (not json3 — it has `_UnsafeExtensionError` bugs in 2026). Timestamps preserved as `"HH:MM:SS"`.
- **Retrieval stays category-scoped** — `vault_search` must pass a category through to `VaultIndex.find_related`; never expose an unscoped search.
- **Vault writes are non-destructive:** a new note never overwrites an existing path; a merge appends a dated `## Update (YYYY-MM-DD)` section (never a blind rewrite); creating a category also creates its folder + MOC and keeps the MOC's link list current. Every write is followed by a read-back and a `VaultIndex` upsert so search stays consistent.
- Reuse Plan 1 code — do NOT reimplement rendering, embedding, or SQL. `vault_write` calls `study_notes.renderer` and `study_notes.vault_index`.
- No LLM API keys anywhere (the LLM is Claude Code, wired in Plan 3).
- Tool functions take their dependencies (index, config, paths) as parameters so they are testable without the MCP layer; `mcp_server.py` injects the real ones.
- TDD: failing test first; commit after each green step. DRY, YAGNI.

---

### Task 1: Dependencies + transcript models + pure VTT parser

**Files:**
- Modify: `pyproject.toml` (add deps)
- Create: `src/study_notes/tools/__init__.py`
- Create: `src/study_notes/tools/youtube.py`
- Create: `tests/tools/__init__.py`
- Create: `tests/tools/fixtures/sample.en.vtt`
- Create: `tests/tools/test_youtube_parse.py`

**Interfaces:**
- Consumes: nothing from Plan 1.
- Produces:
  - `@dataclass TranscriptSegment{ start: str, text: str }` (start = `"HH:MM:SS"`).
  - `@dataclass TranscriptResult{ url: str, video_id: str, title: str, upload_date: str | None, segments: list[TranscriptSegment] }` (`upload_date` = `"YYYY-MM-DD"` or None).
  - `parse_vtt(text: str) -> list[TranscriptSegment]` — pure; strips tags, drops milliseconds, dedupes consecutive identical lines.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, extend the `dependencies` list with:
```toml
    "mcp>=1.2,<2",
    "yt-dlp>=2025.1.1",
```
Run: `uv pip install -e ".[dev]"`

- [ ] **Step 2: Write the fixture VTT**

`tests/tools/fixtures/sample.en.vtt`:
```
WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.500
Welcome to the lecture on <c>consensus</c>

00:00:02.500 --> 00:00:05.000
Welcome to the lecture on consensus

00:00:05.000 --> 00:00:08.000
A leader is elected for each term
```

- [ ] **Step 3: Write the failing test**

`tests/tools/__init__.py`:
```python
```

`tests/tools/test_youtube_parse.py`:
```python
from pathlib import Path

from study_notes.tools.youtube import TranscriptSegment, parse_vtt

FIXTURE = Path(__file__).parent / "fixtures" / "sample.en.vtt"


def test_parse_vtt_extracts_timed_segments():
    segs = parse_vtt(FIXTURE.read_text())
    assert all(isinstance(s, TranscriptSegment) for s in segs)
    # tags stripped, ms dropped
    assert segs[0] == TranscriptSegment(start="00:00:00", text="Welcome to the lecture on consensus")
    # consecutive duplicate line (rolling caption) removed
    assert [s.text for s in segs] == [
        "Welcome to the lecture on consensus",
        "A leader is elected for each term",
    ]
    assert segs[1].start == "00:00:05"


def test_parse_vtt_empty_returns_empty():
    assert parse_vtt("WEBVTT\n\n") == []
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_youtube_parse.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.tools.youtube'`.

- [ ] **Step 5: Write minimal implementation**

`src/study_notes/tools/__init__.py`:
```python
```

`src/study_notes/tools/youtube.py`:
```python
import re
from dataclasses import dataclass

_CUE_TIME = re.compile(
    r"(\d{2}:\d{2}:\d{2})\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}"
)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class TranscriptSegment:
    start: str  # "HH:MM:SS"
    text: str


@dataclass
class TranscriptResult:
    url: str
    video_id: str
    title: str
    upload_date: str | None  # "YYYY-MM-DD"
    segments: list["TranscriptSegment"]


def parse_vtt(text: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    lines = text.splitlines()
    i = 0
    last_text: str | None = None
    while i < len(lines):
        m = _CUE_TIME.search(lines[i])
        if not m:
            i += 1
            continue
        start = m.group(1)
        i += 1
        parts: list[str] = []
        while i < len(lines) and lines[i].strip():
            parts.append(_TAG.sub("", lines[i]).strip())
            i += 1
        cue = " ".join(p for p in parts if p).strip()
        if cue and cue != last_text:
            segments.append(TranscriptSegment(start=start, text=cue))
            last_text = cue
    return segments
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/tools/test_youtube_parse.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/study_notes/tools/__init__.py src/study_notes/tools/youtube.py tests/tools/__init__.py tests/tools/fixtures/sample.en.vtt tests/tools/test_youtube_parse.py
git commit -m "feat: transcript models + pure VTT parser; add mcp/yt-dlp deps"
```

---

### Task 2: `fetch_youtube_transcript` (yt-dlp integration)

**Files:**
- Modify: `src/study_notes/tools/youtube.py`
- Create: `tests/tools/test_youtube_fetch.py`

**Interfaces:**
- Consumes: `parse_vtt`, `TranscriptResult`, `TranscriptSegment` (Task 1).
- Produces: `fetch_youtube_transcript(url: str, *, tmp_dir: Path | None = None) -> TranscriptResult`. Uses yt-dlp to fetch English VTT subtitles (manual preferred, else auto) + metadata (title, upload_date, id). Raises `TranscriptUnavailable(url)` when no English captions exist.

- [ ] **Step 1: Write the failing test**

`tests/tools/test_youtube_fetch.py`:
```python
from pathlib import Path

import pytest

from study_notes.tools.youtube import (
    TranscriptResult,
    TranscriptUnavailable,
    _result_from_info,
)


def test_result_from_info_maps_metadata_and_parses_vtt(tmp_path):
    # Simulate what yt-dlp produced: an info dict + a written .en.vtt file.
    vtt = tmp_path / "vid123.en.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nhello there\n"
    )
    info = {"id": "vid123", "title": "My Talk", "upload_date": "20251114"}
    result = _result_from_info(
        url="https://youtu.be/vid123", info=info, vtt_path=vtt
    )
    assert isinstance(result, TranscriptResult)
    assert result.video_id == "vid123"
    assert result.title == "My Talk"
    assert result.upload_date == "2025-11-14"
    assert result.segments[0].start == "00:00:01"
    assert result.segments[0].text == "hello there"


def test_result_from_info_missing_vtt_raises(tmp_path):
    info = {"id": "vid123", "title": "My Talk", "upload_date": "20251114"}
    with pytest.raises(TranscriptUnavailable):
        _result_from_info(url="u", info=info, vtt_path=tmp_path / "missing.en.vtt")


@pytest.mark.network
def test_fetch_youtube_transcript_live():
    # A stable, caption-bearing video. Skipped unless network tests are run.
    from study_notes.tools.youtube import fetch_youtube_transcript

    res = fetch_youtube_transcript("https://www.youtube.com/watch?v=aircAruvnKk")
    assert res.segments
    assert res.title
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_youtube_fetch.py -m "not network" -v`
Expected: FAIL with `ImportError` (`TranscriptUnavailable`/`_result_from_info` not defined).

- [ ] **Step 3: Write minimal implementation**

Append to `src/study_notes/tools/youtube.py`:
```python
import tempfile
from pathlib import Path


class TranscriptUnavailable(Exception):
    """No usable English captions were found for the video."""


def _fmt_upload_date(raw: str | None) -> str | None:
    if not raw or len(raw) != 8:
        return None
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def _result_from_info(url: str, info: dict, vtt_path: Path) -> TranscriptResult:
    if not vtt_path.exists():
        raise TranscriptUnavailable(url)
    segments = parse_vtt(vtt_path.read_text())
    if not segments:
        raise TranscriptUnavailable(url)
    return TranscriptResult(
        url=url,
        video_id=info.get("id", ""),
        title=info.get("title", ""),
        upload_date=_fmt_upload_date(info.get("upload_date")),
        segments=segments,
    )


def fetch_youtube_transcript(url: str, *, tmp_dir: Path | None = None) -> TranscriptResult:
    import yt_dlp

    ctx = tempfile.TemporaryDirectory() if tmp_dir is None else None
    work = Path(tmp_dir) if tmp_dir is not None else Path(ctx.name)
    try:
        opts = {
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["en", "en-US", "en-orig"],
            "subtitlesformat": "vtt",
            "skip_download": True,
            "outtmpl": str(work / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        vid = info.get("id", "")
        candidates = sorted(work.glob(f"{vid}*.vtt"))
        if not candidates:
            raise TranscriptUnavailable(url)
        return _result_from_info(url=url, info=info, vtt_path=candidates[0])
    finally:
        if ctx is not None:
            ctx.cleanup()
```

- [ ] **Step 4: Run the offline tests**

Run: `uv run pytest tests/tools/test_youtube_fetch.py -m "not network" -v`
Expected: PASS (2 passed). The `network` test is deselected.

- [ ] **Step 5: (Optional) Run the live test**

Run: `uv run pytest tests/tools/test_youtube_fetch.py -m network -v`
Expected: PASS if online and the video still has captions. Skip if offline.

- [ ] **Step 6: Register the `network` marker**

In `pyproject.toml` under `[tool.pytest.ini_options].markers`, add:
```toml
    "network: hits the live network (YouTube)",
```

- [ ] **Step 7: Commit**

```bash
git add src/study_notes/tools/youtube.py tests/tools/test_youtube_fetch.py pyproject.toml
git commit -m "feat: fetch_youtube_transcript via yt-dlp (VTT + metadata)"
```

---

### Task 3: Frame extraction (`extract_frame` via ffmpeg)

**Files:**
- Create: `src/study_notes/tools/frames.py`
- Create: `tests/tools/test_frames.py`
- Modify: `README-dev.md` (note the ffmpeg system dependency)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `frame_filename(prefix: str, timestamp: str) -> str` — pure; e.g. `("raft", "00:14:32") -> "raft_00-14-32.jpg"`.
  - `extract_frame(video_path: Path, timestamp: str, out_path: Path) -> Path` — runs ffmpeg to grab one frame at `timestamp`; raises `FrameExtractionError` on ffmpeg failure. Returns `out_path`.
  - `download_video(url: str, out_dir: Path) -> Path` — yt-dlp download of the video (used later by the MCP tool); returns the file path.

- [ ] **Step 1: Document the ffmpeg dependency**

Append to `README-dev.md`:
```markdown

## ffmpeg (frame extraction)

    brew install ffmpeg      # system binary used by extract_frame

Tests that touch ffmpeg are marked `ffmpeg` and generate their own sample clip.
```

- [ ] **Step 2: Write the failing test**

`tests/tools/test_frames.py`:
```python
import shutil
import subprocess
from pathlib import Path

import pytest

from study_notes.tools.frames import FrameExtractionError, extract_frame, frame_filename


def test_frame_filename_slugifies_timestamp():
    assert frame_filename("raft", "00:14:32") == "raft_00-14-32.jpg"


needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


@pytest.fixture
def sample_video(tmp_path):
    out = tmp_path / "sample.mp4"
    subprocess.run(
        ["ffmpeg", "-f", "lavfi", "-i",
         "testsrc=duration=2:size=320x240:rate=10", str(out), "-y"],
        check=True, capture_output=True,
    )
    return out


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_extract_frame_writes_image(sample_video, tmp_path):
    out = tmp_path / "frame.jpg"
    result = extract_frame(sample_video, "00:00:01", out)
    assert result == out
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_extract_frame_bad_input_raises(tmp_path):
    with pytest.raises(FrameExtractionError):
        extract_frame(tmp_path / "nope.mp4", "00:00:01", tmp_path / "out.jpg")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_frames.py::test_frame_filename_slugifies_timestamp -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.tools.frames'`.

- [ ] **Step 4: Write minimal implementation**

`src/study_notes/tools/frames.py`:
```python
import subprocess
from pathlib import Path


class FrameExtractionError(Exception):
    """ffmpeg could not extract the requested frame."""


def frame_filename(prefix: str, timestamp: str) -> str:
    return f"{prefix}_{timestamp.replace(':', '-')}.jpg"


def extract_frame(video_path: Path, timestamp: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-ss", timestamp, "-i", str(video_path),
         "-frames:v", "1", "-q:v", "2", str(out_path), "-y"],
        capture_output=True,
    )
    if proc.returncode != 0 or not out_path.exists():
        raise FrameExtractionError(
            f"ffmpeg failed for {video_path} @ {timestamp}: "
            f"{proc.stderr.decode(errors='replace')[-300:]}"
        )
    return out_path


def download_video(url: str, out_dir: Path) -> Path:
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "mp4/bestvideo[ext=mp4]/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    matches = sorted(out_dir.glob(f"{info.get('id', '')}*"))
    if not matches:
        raise FrameExtractionError(f"video download produced no file for {url}")
    return matches[0]
```

- [ ] **Step 5: Register the `ffmpeg` marker and run**

In `pyproject.toml` markers, add:
```toml
    "ffmpeg: requires the ffmpeg binary and generates a sample clip",
```
Run: `uv run pytest tests/tools/test_frames.py -v`
Expected: PASS (3 passed if ffmpeg installed; the 2 ffmpeg tests skip if not). Install with `brew install ffmpeg` to run them.

- [ ] **Step 6: Commit**

```bash
git add src/study_notes/tools/frames.py tests/tools/test_frames.py README-dev.md pyproject.toml
git commit -m "feat: extract_frame (ffmpeg) + download_video helper"
```

---

### Task 4: `vault_write` — non-destructive writer + MOC maintenance + index upsert

**Files:**
- Create: `src/study_notes/tools/vault_write.py`
- Create: `tests/tools/test_vault_write.py`

**Interfaces:**
- Consumes: `Config` (Plan 1 `config.py`), `Note`/`Topic`/`Provenance` (`models.py`), `render_note`/`render_update_section` (`renderer.py`), `VaultIndex` (`vault_index.py`).
- Produces `VaultWriter`:
  - `__init__(self, config: Config, index: VaultIndex)`
  - `note_path(self, category: str, title: str) -> str` — vault-relative: `f"{notes_root}/{category}/{slug(title)}.md"`.
  - `write_new(self, topic: Topic, category: str, frame_paths: dict[int, str] | None = None) -> str` — creates category folder + MOC if missing, refuses to clobber an existing note path (raises `VaultWriteConflict`), writes rendered markdown, adds a MOC link, upserts into the index, read-back verifies. Returns the path.
  - `write_merge(self, target_path: str, topic: Topic, on: date, frame_paths: dict[int, str] | None = None) -> str` — appends a dated `## Update` section to an existing note, re-upserts, read-back verifies. Raises `FileNotFoundError` if the target doesn't exist.
  - Internal `_ensure_category(self, category: str) -> None` — folder + `<Category>.md` MOC (with description frontmatter) if absent, and `index.upsert_category`.

- [ ] **Step 1: Write the failing test**

`tests/tools/test_vault_write.py`:
```python
from datetime import date
from pathlib import Path

import pytest

from study_notes.config import Config
from study_notes.embedding import FakeEmbedder
from study_notes.models import Card, Provenance, Topic
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _config(vault: Path) -> Config:
    return Config(
        vault_path=vault, notes_root="04 - Resources",
        attachments_dir="06 - Attachments", frames_subdir="frames",
        database_url="unused", embedding_model="fake",
        models={}, prompts={}, dry_run=False,
    )


def _topic(title="Raft"):
    prov = Provenance(origin="u", input_type="youtube",
                      captured_at=date(2026, 7, 26), source_date=date(2025, 11, 14))
    return Topic(title=title, tags=["consensus"], summary=["Leaders per term."],
                 cards=[Card("Q?", "A.")], provenance=prov)


def _writer(vault, db_conn):
    from study_notes.tools.vault_write import VaultWriter

    return VaultWriter(_config(vault), VaultIndex(db_conn, FakeEmbedder()))


def test_write_new_creates_folder_moc_and_note(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    path = w.write_new(_topic(), category="Distributed Systems")
    note_file = tmp_path / path
    assert note_file.exists()
    assert "title: Raft" in note_file.read_text()
    moc = tmp_path / "04 - Resources/Distributed Systems/Distributed Systems.md"
    assert moc.exists()
    assert f"[[{Path(path).stem}]]" in moc.read_text()  # MOC links the note


def test_write_new_refuses_to_clobber(tmp_path, db_conn):
    from study_notes.tools.vault_write import VaultWriteConflict

    w = _writer(tmp_path, db_conn)
    w.write_new(_topic(), category="Distributed Systems")
    with pytest.raises(VaultWriteConflict):
        w.write_new(_topic(), category="Distributed Systems")


def test_write_merge_appends_dated_update(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    path = w.write_new(_topic(), category="Distributed Systems")
    merged = w.write_merge(path, _topic(), on=date(2026, 7, 27))
    body = (tmp_path / merged).read_text()
    assert "## Update (2026-07-27)" in body
    assert body.count("title: Raft") == 1  # frontmatter not duplicated


def test_write_new_upserts_into_index(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    w.write_new(_topic(), category="Distributed Systems")
    hits = w.index.find_related("leaders per term", category="Distributed Systems", k=5)
    assert any("Raft" in p for p, _ in hits)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_vault_write.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.tools.vault_write'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/tools/vault_write.py`:
```python
from datetime import date
from pathlib import Path

from study_notes.config import Config
from study_notes.models import Note, Topic
from study_notes.renderer import render_note, render_update_section
from study_notes.vault_index import VaultIndex


class VaultWriteConflict(Exception):
    """A new note would overwrite an existing file."""


def slug(title: str) -> str:
    kept = "".join(c if (c.isalnum() or c in " -_") else "" for c in title)
    return " ".join(kept.split())[:80].strip() or "note"


class VaultWriter:
    def __init__(self, config: Config, index: VaultIndex) -> None:
        self.config = config
        self.index = index

    def _category_dir(self, category: str) -> Path:
        return self.config.vault_path / self.config.notes_root / category

    def note_path(self, category: str, title: str) -> str:
        return f"{self.config.notes_root}/{category}/{slug(title)}.md"

    def _ensure_category(self, category: str) -> None:
        cdir = self._category_dir(category)
        cdir.mkdir(parents=True, exist_ok=True)
        moc = cdir / f"{category}.md"
        if not moc.exists():
            moc.write_text(
                f"---\ntype: moc\ncategory: {category}\ndescription: \"\"\n---\n\n"
                f"# {category}\n\n## Notes\n"
            )
        self.index.upsert_category(category)

    def _add_moc_link(self, category: str, note_stem: str) -> None:
        moc = self._category_dir(category) / f"{category}.md"
        text = moc.read_text()
        link = f"- [[{note_stem}]]"
        if link not in text:
            moc.write_text(text.rstrip() + f"\n{link}\n")

    def _upsert(self, path: str, topic: Topic, category: str, body: str) -> None:
        self.index.upsert_note(Note(
            path=path, title=topic.title, category=category,
            content=body, provenance=topic.provenance,
        ))

    def write_new(self, topic: Topic, category: str,
                  frame_paths: dict[int, str] | None = None) -> str:
        self._ensure_category(category)
        path = self.note_path(category, topic.title)
        abs_path = self.config.vault_path / path
        if abs_path.exists():
            raise VaultWriteConflict(path)
        markdown = render_note(topic, category=category, frame_paths=frame_paths)
        abs_path.write_text(markdown)
        self._add_moc_link(category, abs_path.stem)
        self._upsert(path, topic, category, markdown)
        assert abs_path.read_text() == markdown  # read-back verification
        return path

    def write_merge(self, target_path: str, topic: Topic, on: date,
                    frame_paths: dict[int, str] | None = None) -> str:
        abs_path = self.config.vault_path / target_path
        if not abs_path.exists():
            raise FileNotFoundError(target_path)
        existing = abs_path.read_text()
        section = render_update_section(topic, on=on, frame_paths=frame_paths)
        merged = existing.rstrip() + f"\n\n{section}"
        abs_path.write_text(merged)
        category = Path(target_path).parent.name
        self._upsert(target_path, topic, category, merged)
        assert abs_path.read_text() == merged  # read-back verification
        return target_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tools/test_vault_write.py -v`
Expected: PASS (4 passed). (Requires the DB container from Plan 1.)

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/tools/vault_write.py tests/tools/test_vault_write.py
git commit -m "feat: non-destructive VaultWriter with MOC maintenance + index upsert"
```

---

### Task 5: Search adapters (`vault_search`, `list_categories`)

**Files:**
- Create: `src/study_notes/tools/search.py`
- Create: `tests/tools/test_search.py`

**Interfaces:**
- Consumes: `VaultIndex` (Plan 1).
- Produces (plain, JSON-serializable returns for MCP):
  - `vault_search(index: VaultIndex, query: str, category: str, k: int = 5) -> list[dict]` — `[{"path": str, "score": float}, ...]`, category-scoped.
  - `list_categories(index: VaultIndex) -> list[dict]` — `[{"name": str, "description": str}, ...]`.

- [ ] **Step 1: Write the failing test**

`tests/tools/test_search.py`:
```python
from datetime import date

import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _note(path, title, category, content):
    prov = Provenance(origin="s", input_type="markdown",
                      captured_at=date(2026, 7, 26), source_date=None)
    return Note(path=path, title=title, category=category, content=content, provenance=prov)


def test_vault_search_returns_serializable_scoped_hits(db_conn):
    from study_notes.tools.search import vault_search

    idx = VaultIndex(db_conn, FakeEmbedder())
    idx.upsert_category("DS")
    idx.upsert_category("Bio")
    idx.upsert_note(_note("ds/raft.md", "Raft", "DS", "consensus leader term"))
    idx.upsert_note(_note("bio/cell.md", "Cell", "Bio", "consensus mitosis"))

    hits = vault_search(idx, "consensus", category="DS", k=5)
    assert isinstance(hits, list) and all(set(h) == {"path", "score"} for h in hits)
    assert all(isinstance(h["score"], float) for h in hits)
    assert all(h["path"].startswith("ds/") for h in hits)  # scoped


def test_list_categories_returns_dicts(db_conn):
    from study_notes.tools.search import list_categories

    idx = VaultIndex(db_conn, FakeEmbedder())
    idx.upsert_category("DS", "distributed systems")
    out = list_categories(idx)
    assert {"name": "DS", "description": "distributed systems"} in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/tools/test_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.tools.search'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/tools/search.py`:
```python
from study_notes.vault_index import VaultIndex


def vault_search(index: VaultIndex, query: str, category: str, k: int = 5) -> list[dict]:
    return [
        {"path": path, "score": score}
        for path, score in index.find_related(query, category=category, k=k)
    ]


def list_categories(index: VaultIndex) -> list[dict]:
    return [{"name": c.name, "description": c.description}
            for c in index.list_categories()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/tools/test_search.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/tools/search.py tests/tools/test_search.py
git commit -m "feat: vault_search + list_categories JSON adapters"
```

---

### Task 6: MCP server wiring

**Files:**
- Create: `src/study_notes/mcp_server.py`
- Create: `tests/test_mcp_server.py`
- Modify: `README-dev.md` (how Claude Code loads the server)

**Interfaces:**
- Consumes: everything above + `load_config` (Plan 1).
- Produces:
  - `build_context(config: Config) -> Context` — a small holder with a live `VaultIndex` (real `BGEM3Embedder` + `connect(config.database_url)`) and a `VaultWriter`.
  - A module-level `FastMCP` instance `mcp` named `"study-notes-tools"` registering 5 tools: `fetch_youtube_transcript`, `list_categories`, `vault_search`, `extract_frame`, `vault_write`.
  - `main()` → `mcp.run()` (stdio). Config path from env `STUDY_NOTES_CONFIG`.

- [ ] **Step 1: Write the failing test**

`tests/test_mcp_server.py`:
```python
import pytest


def test_server_registers_all_five_tools():
    from study_notes import mcp_server

    tool_names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert {
        "fetch_youtube_transcript",
        "list_categories",
        "vault_search",
        "extract_frame",
        "vault_write",
    } <= tool_names


def test_server_name():
    from study_notes import mcp_server

    assert mcp_server.mcp.name == "study-notes-tools"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.mcp_server'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/mcp_server.py`:
```python
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from study_notes.config import Config, load_config
from study_notes.tools import frames, search, youtube
from study_notes.tools.vault_write import VaultWriter

mcp = FastMCP("study-notes-tools")


@dataclass
class Context:
    config: Config
    writer: VaultWriter


_ctx: Context | None = None


def build_context(config: Config) -> Context:
    from study_notes.db import connect
    from study_notes.embedding import BGEM3Embedder
    from study_notes.vault_index import VaultIndex

    index = VaultIndex(connect(config.database_url),
                       BGEM3Embedder(config.embedding_model))
    return Context(config=config, writer=VaultWriter(config, index))


def _context() -> Context:
    global _ctx
    if _ctx is None:
        cfg_path = os.environ.get("STUDY_NOTES_CONFIG", "config.toml")
        _ctx = build_context(load_config(Path(cfg_path)))
    return _ctx


@mcp.tool()
def fetch_youtube_transcript(url: str) -> dict:
    """Fetch a YouTube video's English transcript with timestamps and metadata."""
    r = youtube.fetch_youtube_transcript(url)
    return {
        "url": r.url, "video_id": r.video_id, "title": r.title,
        "upload_date": r.upload_date,
        "segments": [{"start": s.start, "text": s.text} for s in r.segments],
    }


@mcp.tool()
def list_categories() -> list[dict]:
    """List existing vault categories with their descriptions."""
    return search.list_categories(_context().writer.index)


@mcp.tool()
def vault_search(query: str, category: str, k: int = 5) -> list[dict]:
    """Find notes related to `query` WITHIN a single category (never crosses categories)."""
    return search.vault_search(_context().writer.index, query, category, k)


@mcp.tool()
def extract_frame(video_url: str, timestamp: str, prefix: str) -> dict:
    """Download a video and save the frame at `timestamp` (HH:MM:SS) into the vault frames dir."""
    ctx = _context()
    frames_dir = ctx.config.vault_path / ctx.config.attachments_dir / ctx.config.frames_subdir
    video = frames.download_video(video_url, frames_dir / "_tmp")
    out = frames_dir / frames.frame_filename(prefix, timestamp)
    frames.extract_frame(video, timestamp, out)
    rel = f"{ctx.config.attachments_dir}/{ctx.config.frames_subdir}/{out.name}"
    return {"embed_path": rel}


@mcp.tool()
def vault_write(title: str, category: str, summary: list[str], cards: list[dict],
                source: str, source_type: str, source_date: str | None,
                action: str = "new_note", target_note: str | None = None) -> dict:
    """Write a study note non-destructively. action: 'new_note' or 'merge' (into target_note)."""
    from study_notes.models import Card, Provenance, Topic

    prov = Provenance(
        origin=source, input_type=source_type, captured_at=date.today(),
        source_date=date.fromisoformat(source_date) if source_date else None,
    )
    topic = Topic(
        title=title, tags=[], summary=summary,
        cards=[Card(question=c["question"], answer=c["answer"],
                    cloze=c.get("cloze", False), timestamp=c.get("timestamp"))
               for c in cards],
        provenance=prov,
    )
    w = _context().writer
    if action == "merge" and target_note:
        path = w.write_merge(target_note, topic, on=date.today())
    else:
        path = w.write_new(topic, category=category)
    return {"path": path}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_server.py -v`
Expected: PASS (2 passed). (Import does not connect to the DB — the context is lazy.)

Note: if `list_tools()`/`_tool_manager` differs in the installed `mcp` version, discover the correct accessor with:
`uv run python -c "from study_notes import mcp_server as m; print([a for a in dir(m.mcp) if 'tool' in a.lower()])"`
and adjust the test's accessor accordingly (the registration itself via `@mcp.tool()` is stable).

- [ ] **Step 5: Document how Claude Code loads the server**

Append to `README-dev.md`:
```markdown

## MCP server (for Claude Code)

Run standalone (stdio):

    STUDY_NOTES_CONFIG=config.toml uv run python -m study_notes.mcp_server

Register with Claude Code via an MCP config JSON (used by Plan 3's orchestrator):

    {
      "mcpServers": {
        "study-notes-tools": {
          "command": "uv",
          "args": ["run", "python", "-m", "study_notes.mcp_server"],
          "env": { "STUDY_NOTES_CONFIG": "config.toml" }
        }
      }
    }
```

- [ ] **Step 6: Run the full offline suite**

Run: `uv run pytest -m "not slow and not network and not ffmpeg" -q`
Expected: PASS (all Plan 1 + Plan 2 offline/integration tests green; requires the DB container).

- [ ] **Step 7: Commit**

```bash
git add src/study_notes/mcp_server.py tests/test_mcp_server.py README-dev.md
git commit -m "feat: FastMCP server exposing the 5 study-notes tools"
```

---

## Self-Review

**Spec coverage (Plan 2 portion of §5–§6):**
- `fetch_youtube_transcript` (timed segments + metadata) → Tasks 1–2. ✓
- `list_categories` → Task 5 + Task 6. ✓
- `vault_search(query, category)` category-scoped → Task 5 + Task 6. ✓
- `extract_frame` (ffmpeg) → Task 3 + Task 6. ✓
- `vault_write` non-destructive + category folder/MOC creation + MOC link maintenance + index upsert + read-back → Task 4 + Task 6. ✓
- MCP server exposing all as typed tools → Task 6. ✓
- Reuse of `renderer`/`vault_index` (no reimplementation) → Task 4 uses `render_note`/`render_update_section`/`VaultIndex`. ✓
- Deferred to Plan 3 (correctly out of scope): `claude -p` orchestration, prompts, self-verifying procedure, `add`/`reindex` CLI, `--category`/`--note`/`--dry-run`.

**Placeholder scan:** No TBD/TODO; every step has concrete code/commands. The Task 6 note about `list_tools()` accessor is a version-robustness check with an exact command, not a placeholder.

**Type consistency:** `TranscriptSegment{start,text}`/`TranscriptResult` consistent across Tasks 1–2 and Task 6. `VaultWriter(config, index)` with `write_new`/`write_merge`/`note_path` consistent between Task 4 and Task 6. `vault_search(index, query, category, k) -> list[dict]` and `list_categories(index) -> list[dict]` consistent between Task 5 and Task 6. `extract_frame(video_path, timestamp, out_path)`, `frame_filename(prefix, timestamp)`, `download_video(url, out_dir)` consistent between Task 3 and Task 6.

---

## Plan 3 (to be written after Plan 2 is built and reviewed)

**Orchestrator, prompts & CLI:** per-task `claude -p` invocation (model + `--append-system-prompt` from versioned prompt files + `--allowedTools` + `--mcp-config` pointing at Task 6's server + `--output-format json`), the single self-verifying agentic procedure (§8), `study-notes add <src> [--category] [--note] [--dry-run]` and `study-notes reindex`, and end-to-end smoke tests against golden transcripts.
