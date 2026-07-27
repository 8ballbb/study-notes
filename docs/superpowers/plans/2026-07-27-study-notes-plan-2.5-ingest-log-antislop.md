# Study Notes — Plan 2.5: Ingestion Log & Anti-Slop Guardrails

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two independent guardrail units that Plan 3's `add` flow will wire in: (1) an **ingestion log** so the same YouTube URL / document isn't re-ingested unknowingly, and (2) an **anti-slop** style guide + validator so Claude-written notes avoid AI-filler language.

**Architecture:** Both are small, standalone, directly-testable units on top of the merged Plan 1/2 core. Source identity is pure functions (URL→id, file→hash); the log is a thin Postgres-backed class beside the existing schema. Anti-slop is a versioned prompt artifact (primary defense, used by Plan 3's prompts) plus a pure `slop_check` validator (backstop for Plan 3's self-verification). Nothing here changes existing behavior — Plan 3 does the wiring.

**Tech Stack:** Python 3.12+ stdlib (`hashlib`, `re`), `psycopg` (v3, existing), PostgreSQL (existing Docker container). No new dependencies.

## Global Constraints

- Python 3.12+; macOS/arm64.
- Canonical `source_id`: YouTube → `youtube:<11-char video id>` (parsed from any URL form); files → `sha256:<hex>` of file bytes.
- The `sources` table lives in the existing `schema.sql` (idempotent `CREATE TABLE IF NOT EXISTS`), applied by the existing `apply_schema`.
- `slop_check` is **pure** (no I/O) and returns findings; it never raises or hard-fails — it is a backstop, the prompt guide is the primary defense.
- `prompts/anti-slop.md` is adapted from petergyang/no-ai-slop and must credit the source.
- No LLM API keys. TDD: failing test first; commit after green. DRY, YAGNI.
- This plan only builds the units. Do NOT wire them into the MCP server or a CLI here — that is Plan 3.

---

### Task 1: Source identity (pure)

**Files:**
- Create: `src/study_notes/ingest.py`
- Create: `tests/test_ingest_identity.py`
- Create: `tests/fixtures/hash_me.txt`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `SourceIdentityError(Exception)`
  - `youtube_source_id(url: str) -> str` → `"youtube:<id>"`; raises `SourceIdentityError` if no 11-char id is found.
  - `file_source_id(path: Path) -> str` → `"sha256:<hex>"` (streamed, 64 KiB chunks).

- [ ] **Step 1: Write the fixture + failing test**

`tests/fixtures/hash_me.txt`:
```
deterministic content for hashing
```

`tests/test_ingest_identity.py`:
```python
import hashlib
from pathlib import Path

import pytest

from study_notes.ingest import SourceIdentityError, file_source_id, youtube_source_id

FIXTURE = Path(__file__).parent / "fixtures" / "hash_me.txt"


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=772CUg2xYAo",
    "https://youtu.be/772CUg2xYAo",
    "https://www.youtube.com/watch?v=772CUg2xYAo&list=PLxyz&index=2",
    "https://www.youtube.com/shorts/772CUg2xYAo",
    "https://www.youtube.com/embed/772CUg2xYAo",
])
def test_youtube_source_id_canonicalizes(url):
    assert youtube_source_id(url) == "youtube:772CUg2xYAo"


def test_youtube_source_id_rejects_non_youtube():
    with pytest.raises(SourceIdentityError):
        youtube_source_id("https://example.com/not-a-video")


def test_file_source_id_matches_sha256():
    expected = "sha256:" + hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert file_source_id(FIXTURE) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ingest_identity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.ingest'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/ingest.py`:
```python
import hashlib
import re
from pathlib import Path

_YT_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/v/)([0-9A-Za-z_-]{11})")


class SourceIdentityError(Exception):
    """The source could not be identified (e.g. no YouTube id in the URL)."""


def youtube_source_id(url: str) -> str:
    m = _YT_ID.search(url)
    if not m:
        raise SourceIdentityError(f"no YouTube video id in {url!r}")
    return f"youtube:{m.group(1)}"


def file_source_id(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ingest_identity.py -v`
Expected: PASS (7 passed — 5 parametrized + 2).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/ingest.py tests/test_ingest_identity.py tests/fixtures/hash_me.txt
git commit -m "feat: canonical source identity (youtube id / file sha256)"
```

---

### Task 2: Ingestion log (`sources` table + `IngestLog`)

**Files:**
- Modify: `src/study_notes/schema.sql` (add `sources` table)
- Modify: `src/study_notes/ingest.py` (add `IngestRecord`, `IngestLog`)
- Modify: `tests/conftest.py` (truncate `sources` too)
- Create: `tests/test_ingest_log.py`

**Interfaces:**
- Consumes: `connect`/`apply_schema` (Plan 1), the `db_conn` fixture.
- Produces:
  - `@dataclass IngestRecord{ source_id: str, source_type: str, origin: str, note_paths: list[str] }`
  - `IngestLog(conn)` with `lookup(source_id: str) -> IngestRecord | None` and `record(source_id, source_type, origin, note_paths: list[str]) -> None` (upsert on `source_id`, refreshes `ingested_at`).

- [ ] **Step 1: Add the `sources` table to `schema.sql`**

Append to `src/study_notes/schema.sql`:
```sql

CREATE TABLE IF NOT EXISTS sources (
    source_id   TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    origin      TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    note_paths  TEXT[] NOT NULL DEFAULT '{}'
);
```

- [ ] **Step 2: Extend the conftest truncation to include `sources`**

In `tests/conftest.py`, change both `TRUNCATE notes, categories CASCADE;` statements (setup and teardown) to:
```python
        cur.execute("TRUNCATE notes, categories, sources CASCADE;")
```

- [ ] **Step 3: Write the failing test**

`tests/test_ingest_log.py`:
```python
import pytest

from study_notes.ingest import IngestLog, IngestRecord

pytestmark = pytest.mark.integration


def test_lookup_miss_returns_none(db_conn):
    log = IngestLog(db_conn)
    assert log.lookup("youtube:missing0000") is None


def test_record_then_lookup_roundtrips(db_conn):
    log = IngestLog(db_conn)
    log.record("youtube:772CUg2xYAo", "youtube", "https://youtu.be/772CUg2xYAo",
               ["04 - Resources/Web APIs/HTTP Status Codes.md"])
    rec = log.lookup("youtube:772CUg2xYAo")
    assert rec == IngestRecord(
        source_id="youtube:772CUg2xYAo", source_type="youtube",
        origin="https://youtu.be/772CUg2xYAo",
        note_paths=["04 - Resources/Web APIs/HTTP Status Codes.md"],
    )


def test_record_is_idempotent_upsert(db_conn):
    log = IngestLog(db_conn)
    log.record("sha256:abc", "file", "/tmp/a.pdf", ["p/one.md"])
    log.record("sha256:abc", "file", "/tmp/a.pdf", ["p/one.md", "p/two.md"])  # re-ingest
    rec = log.lookup("sha256:abc")
    assert rec.note_paths == ["p/one.md", "p/two.md"]
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sources WHERE source_id = %s;", ("sha256:abc",))
        assert cur.fetchone()[0] == 1
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_ingest_log.py -v`
Expected: FAIL with `ImportError` (`IngestLog`/`IngestRecord` not defined).

- [ ] **Step 5: Write minimal implementation**

Append to `src/study_notes/ingest.py`:
```python
from dataclasses import dataclass

import psycopg


@dataclass
class IngestRecord:
    source_id: str
    source_type: str
    origin: str
    note_paths: list[str]


class IngestLog:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def lookup(self, source_id: str) -> IngestRecord | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, source_type, origin, note_paths "
                "FROM sources WHERE source_id = %s;",
                (source_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return IngestRecord(source_id=row[0], source_type=row[1],
                            origin=row[2], note_paths=list(row[3]))

    def record(self, source_id: str, source_type: str, origin: str,
               note_paths: list[str]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sources (source_id, source_type, origin, note_paths) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "  source_type = EXCLUDED.source_type, origin = EXCLUDED.origin, "
                "  note_paths = EXCLUDED.note_paths, ingested_at = now();",
                (source_id, source_type, origin, note_paths),
            )
        self.conn.commit()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_ingest_log.py -v`
Expected: PASS (3 passed). (Requires the DB container.)

- [ ] **Step 7: Commit**

```bash
git add src/study_notes/schema.sql src/study_notes/ingest.py tests/conftest.py tests/test_ingest_log.py
git commit -m "feat: ingestion log (sources table + IngestLog upsert/lookup)"
```

---

### Task 3: Anti-slop style guide + `slop_check` validator

**Files:**
- Create: `prompts/anti-slop.md`
- Create: `src/study_notes/slop_check.py`
- Create: `tests/test_slop_check.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass SlopFinding{ pattern: str, snippet: str }`
  - `slop_check(text: str) -> list[SlopFinding]` — pure; regex-scans for the mechanically-detectable AI-slop patterns. Never raises.

- [ ] **Step 1: Write the anti-slop style guide**

`prompts/anti-slop.md`:
```markdown
# Writing style: no AI slop

Adapted from petergyang/no-ai-slop (https://github.com/petergyang/no-ai-slop).
Write these notes like a sharp human's study notes. Cut every pattern below.

## Cut these patterns
- **Binary contrasts:** "It's not X, it's Y." State Y directly.
- **Throat-clearing openers:** "Here's the thing," "Let me be clear," "To be honest." Delete; state the point.
- **Faux-insight setups:** "What nobody tells you," "What most people get wrong." Just say the thing.
- **Colon reveals:** noun phrase + colon + dramatic reveal. Use a plain sentence.
- **Superficial -ing analysis:** "highlighting the team's commitment." State the actual benefit.
- **Importance puffery:** "marks a pivotal moment," "stands as a testament," "plays a vital role." State facts; let the reader judge.
- **Weasel attribution:** "experts agree," "studies show," "widely regarded as." Name a source or cut it.
- **Fake-strong verbs:** "serves as a centralized hub." Say what it actually does.
- **Synonym cycling:** don't rotate terms for style; repeat the clear word.
- **Negative listing:** "Not X. Not Y. Z." Just say Z.
- **Dramatic fragmentation:** "That's it." "And Y. And Z." Use complete sentences.
- **Rhetorical setups:** "What if I told you," "Think about it," "Plot twist."
- **Fake-profound kickers:** no final "deep" metaphor line.
- **Summary-recap endings:** "In conclusion," "Ultimately." End on a concrete detail.
- **Formatting slop:** no emoji in headings, no mid-sentence bold, no header over a one-line section.
- **Em dashes:** don't use them as a rhythm crutch.

## Do this instead
- Lead with the point.
- Active voice.
- Concrete specifics and numbers over abstractions.
- Strong, direct verbs; plain repeated nouns.
- Keep it short. A study card is a question and a precise answer, nothing more.
```

- [ ] **Step 2: Write the failing test**

`tests/test_slop_check.py`:
```python
from study_notes.slop_check import SlopFinding, slop_check


def test_clean_text_has_no_findings():
    clean = (
        "## Core ideas\n"
        "- Raft elects one leader per term.\n"
        "- A log entry commits once a majority replicate it.\n"
    )
    assert slop_check(clean) == []


def test_detects_common_slop_patterns():
    slop = (
        "Here's the thing. It's not about the model, it's about the eval. "
        "Studies show this marks a pivotal moment. In conclusion, think about it."
    )
    patterns = {f.pattern for f in slop_check(slop)}
    assert {"throat-clearing", "binary-contrast", "weasel-attribution",
            "importance-puffery", "summary-recap", "rhetorical-setup"} <= patterns


def test_detects_emoji_heading():
    findings = slop_check("## Overview \U0001F680\nsome text")
    assert any(f.pattern == "emoji-heading" for f in findings)


def test_findings_carry_snippet():
    findings = slop_check("Here's the thing about caching.")
    assert findings and all(isinstance(f, SlopFinding) and f.snippet for f in findings)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_slop_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.slop_check'`.

- [ ] **Step 4: Write minimal implementation**

`src/study_notes/slop_check.py`:
```python
import re
from dataclasses import dataclass


@dataclass
class SlopFinding:
    pattern: str
    snippet: str


_RULES: list[tuple[str, re.Pattern]] = [
    ("throat-clearing",
     re.compile(r"\b(here'?s the thing|let me be clear|i'?ll be honest|to be honest)\b", re.I)),
    ("binary-contrast",
     re.compile(r"\bit'?s not (just )?[^.\n]{1,50}?,?\s*it'?s\b", re.I)),
    ("faux-insight",
     re.compile(r"\b(what (most people|nobody|everyone) (gets? wrong)|what nobody tells you|"
                r"the part (everyone|most people) miss(es)?)\b", re.I)),
    ("importance-puffery",
     re.compile(r"\b(stands as a testament|a testament to|marks a pivotal moment|"
                r"plays? a (vital|crucial|pivotal) role)\b", re.I)),
    ("weasel-attribution",
     re.compile(r"\b(experts agree|studies show|research shows|widely regarded as|"
                r"it is (widely )?believed)\b", re.I)),
    ("summary-recap",
     re.compile(r"(?:^|[.\n])\s*(in conclusion|ultimately|in summary|to sum up)\b", re.I)),
    ("rhetorical-setup",
     re.compile(r"\b(what if i told you|think about it|plot twist)\b", re.I)),
    ("negative-listing",
     re.compile(r"\bnot a [^.\n]{1,30}\.\s*not a [^.\n]{1,30}\.", re.I)),
    ("emoji-heading",
     re.compile(r"(?:^|\n)#{1,6} .*[\U0001F000-\U0001FAFF☀-➿]")),
]


def slop_check(text: str) -> list[SlopFinding]:
    findings: list[SlopFinding] = []
    for name, rx in _RULES:
        for m in rx.finditer(text):
            findings.append(SlopFinding(pattern=name, snippet=m.group(0).strip()[:80]))
    return findings
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_slop_check.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Run the full offline suite**

Run: `uv run pytest -m "not slow and not network and not ffmpeg and not docker" -q`
Expected: PASS (all prior tests + the new ones green; requires the DB container for the integration tests).

- [ ] **Step 7: Commit**

```bash
git add prompts/anti-slop.md src/study_notes/slop_check.py tests/test_slop_check.py
git commit -m "feat: anti-slop style guide + slop_check validator"
```

---

## Self-Review

**Spec coverage:**
- Ingestion idempotency, canonical `source_id`, `sources` table (spec §9.5) → Tasks 1–2. ✓
- Anti-slop style guide in prompts + `slop_check` backstop (spec §10.5) → Task 3. ✓
- `--force` behavior and step-0 dedup gate (spec §8) → belong to the `add` flow → **Plan 3 wiring** (out of scope here; this plan builds the units they call). ✓

**Placeholder scan:** No TBD/TODO; every step has concrete code/commands.

**Type consistency:** `youtube_source_id`/`file_source_id` return `str`; `IngestLog.lookup -> IngestRecord | None`, `record(...) -> None`; `slop_check(text) -> list[SlopFinding]` — consistent across tasks and with spec §9.5/§10.5. `sources` columns match between `schema.sql` (Task 2 Step 1) and the `IngestLog` SQL (Task 2 Step 5).

---

## What Plan 3 wires (not built here)
- `add` flow step 0: `source_id = youtube_source_id(url)` or `file_source_id(path)`; `IngestLog.lookup` → skip+report unless `--force`; `IngestLog.record(...)` after a successful write.
- Prompts: append `prompts/anti-slop.md` to the extraction/segmentation system prompts.
- Self-verification (spec §8 step 8): run `slop_check` on the drafted note; feed findings back for revision.
