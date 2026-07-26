# Study Notes — Plan 1: Foundation & Local Retrieval Core

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the local, deterministic core of the study-notes tool — configuration, data models, the pure markdown renderer, and a PostgreSQL-backed BGE-M3 hybrid retrieval index scoped by category — as standalone, tested software.

**Architecture:** A Python package (`study_notes`) with focused modules. Pure logic (config, models, renderer) has no I/O and is unit-tested directly. Retrieval is split behind two seams: an `Embedder` protocol (real BGE-M3 vs a fast fake) and a `VaultIndex` class that owns all SQL. Hybrid search fuses pgvector dense similarity with PostgreSQL full-text search via Reciprocal Rank Fusion, always filtered to a single category.

**Tech Stack:** Python 3.12+, `uv`, PostgreSQL 17 + `pgvector` (run via Docker image `pgvector/pgvector:pg17` on a Colima runtime; `docker-compose.yml` at repo root), `psycopg` (v3), `pgvector` Python package, `FlagEmbedding` (BGE-M3) + PyTorch (MPS), `pytest`, `tomllib` (stdlib).

## Global Constraints

- Python 3.12+ (target machine can run 3.14).
- macOS / Apple Silicon (arm64); PyTorch runs on MPS.
- Embeddings come from **BGE-M3 via `FlagEmbedding` (BGEM3FlagModel)** — never Ollama. Dense vector dimension is **1024**.
- Lexical retrieval in v1 uses **PostgreSQL native FTS** (`tsvector`); BGE-M3 learned-sparse is a deferred upgrade path, not built here.
- Retrieval is **always category-scoped**: `vault_search`/`find_related` must never return a note outside the requested category.
- No LLM API keys anywhere in this codebase (the LLM lives in later plans via Claude Code).
- Reciprocal Rank Fusion constant `k = 60`.
- All writes are non-destructive (relevant renderer behavior only in this plan; file writing lands in Plan 2).
- TDD: every code change is preceded by a failing test. Commit after each green step.

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/study_notes/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`
- Create: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `study_notes` package and a working `pytest` command.

- [ ] **Step 1: Write `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
.DS_Store
models/
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "study-notes"
version = "0.1.0"
description = "Personal Obsidian study-notes CLI"
requires-python = ">=3.12"
dependencies = [
    "psycopg[binary]>=3.2",
    "pgvector>=0.3.6",
    "FlagEmbedding>=1.3.0",
    "torch>=2.4",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/study_notes"]

[tool.pytest.ini_options]
pythonpath = ["src"]
markers = [
    "integration: requires a live PostgreSQL database",
    "slow: downloads/loads the BGE-M3 model",
]
```

- [ ] **Step 3: Create empty package + test package files**

`src/study_notes/__init__.py`:
```python
"""Personal Obsidian study-notes CLI."""
```

`tests/__init__.py`:
```python
```

- [ ] **Step 4: Write the smoke test**

`tests/test_smoke.py`:
```python
import study_notes


def test_package_imports():
    assert study_notes is not None
```

- [ ] **Step 5: Create the environment and run the smoke test**

Run:
```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest tests/test_smoke.py -v
```
Expected: PASS (1 passed). Note: installing `torch`/`FlagEmbedding` may take a few minutes.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/study_notes/__init__.py tests/__init__.py tests/test_smoke.py .gitignore
git commit -m "chore: scaffold study_notes package"
```

---

### Task 2: Config loader

**Files:**
- Create: `src/study_notes/config.py`
- Create: `tests/test_config.py`
- Create: `tests/fixtures/config_ok.toml`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass(frozen=True) Config` with fields: `vault_path: Path`, `notes_root: str`, `attachments_dir: str`, `frames_subdir: str`, `database_url: str`, `embedding_model: str`, `models: dict[str, str]`, `prompts: dict[str, str]`, `dry_run: bool`.
  - `load_config(path: Path) -> Config`.

- [ ] **Step 1: Write the failing test**

`tests/fixtures/config_ok.toml`:
```toml
vault_path = "/tmp/vault"
notes_root = "04 - Resources"
attachments_dir = "06 - Attachments"
frames_subdir = "frames"

[database]
url = "postgresql://localhost/study_notes_test"

[embedding]
model = "BAAI/bge-m3"

[models]
segment = "claude-haiku-4-5"
extract = "claude-fable-5"
categorize = "claude-opus-4-8"

[prompts]
segment = "prompts/segment.md"
extract = "prompts/extract.md"
categorize = "prompts/categorize.md"

[run]
dry_run = false
```

`tests/test_config.py`:
```python
from pathlib import Path

from study_notes.config import Config, load_config

FIXTURE = Path(__file__).parent / "fixtures" / "config_ok.toml"


def test_load_config_reads_all_fields():
    cfg = load_config(FIXTURE)
    assert isinstance(cfg, Config)
    assert cfg.vault_path == Path("/tmp/vault")
    assert cfg.notes_root == "04 - Resources"
    assert cfg.attachments_dir == "06 - Attachments"
    assert cfg.frames_subdir == "frames"
    assert cfg.database_url == "postgresql://localhost/study_notes_test"
    assert cfg.embedding_model == "BAAI/bge-m3"
    assert cfg.models["extract"] == "claude-fable-5"
    assert cfg.prompts["categorize"] == "prompts/categorize.md"
    assert cfg.dry_run is False


def test_load_config_missing_file_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        load_config(Path("/nonexistent/config.toml"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.config'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/config.py`:
```python
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    vault_path: Path
    notes_root: str
    attachments_dir: str
    frames_subdir: str
    database_url: str
    embedding_model: str
    models: dict[str, str]
    prompts: dict[str, str]
    dry_run: bool


def load_config(path: Path) -> Config:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    data = tomllib.loads(path.read_text())
    return Config(
        vault_path=Path(data["vault_path"]),
        notes_root=data["notes_root"],
        attachments_dir=data["attachments_dir"],
        frames_subdir=data["frames_subdir"],
        database_url=data["database"]["url"],
        embedding_model=data["embedding"]["model"],
        models=dict(data["models"]),
        prompts=dict(data["prompts"]),
        dry_run=bool(data["run"]["dry_run"]),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/config.py tests/test_config.py tests/fixtures/config_ok.toml
git commit -m "feat: config loader"
```

---

### Task 3: Data models

**Files:**
- Create: `src/study_notes/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces (all `@dataclass`):
  - `Provenance{ origin: str, input_type: str, captured_at: date, source_date: date | None }`
  - `Card{ question: str, answer: str, cloze: bool = False, timestamp: str | None = None }` — `timestamp` is `"HH:MM:SS"`.
  - `Topic{ title: str, tags: list[str], summary: list[str], cards: list[Card], provenance: Provenance }`
  - `Category{ name: str, description: str = "" }`
  - `Placement{ category: Category, action: str, target_note: str | None = None }` — `action` is `"new_note"` or `"merge"`.
  - `Note{ path: str, title: str, category: str, content: str, provenance: Provenance }` — a rendered, placeable note.

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from datetime import date

from study_notes.models import Card, Category, Note, Placement, Provenance, Topic


def test_card_defaults():
    c = Card(question="Q", answer="A")
    assert c.cloze is False
    assert c.timestamp is None


def test_topic_holds_cards_and_provenance():
    prov = Provenance(origin="https://x", input_type="youtube",
                      captured_at=date(2026, 7, 26), source_date=date(2025, 11, 14))
    topic = Topic(title="Raft", tags=["consensus"], summary=["idea one"],
                  cards=[Card("Q", "A", timestamp="00:14:32")], provenance=prov)
    assert topic.cards[0].timestamp == "00:14:32"
    assert topic.provenance.input_type == "youtube"


def test_placement_actions():
    cat = Category(name="Distributed Systems", description="d")
    p = Placement(category=cat, action="merge", target_note="04 - Resources/Distributed Systems/Raft.md")
    assert p.action == "merge"
    assert p.category.name == "Distributed Systems"


def test_note_shape():
    prov = Provenance(origin="f.pdf", input_type="pdf",
                      captured_at=date(2026, 7, 26), source_date=None)
    n = Note(path="a/b.md", title="T", category="Cat", content="# body", provenance=prov)
    assert n.path == "a/b.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.models'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/models.py`:
```python
from dataclasses import dataclass, field
from datetime import date


@dataclass
class Provenance:
    origin: str
    input_type: str
    captured_at: date
    source_date: date | None = None


@dataclass
class Card:
    question: str
    answer: str
    cloze: bool = False
    timestamp: str | None = None


@dataclass
class Topic:
    title: str
    tags: list[str]
    summary: list[str]
    cards: list[Card]
    provenance: Provenance


@dataclass
class Category:
    name: str
    description: str = ""


@dataclass
class Placement:
    category: Category
    action: str  # "new_note" | "merge"
    target_note: str | None = None


@dataclass
class Note:
    path: str
    title: str
    category: str
    content: str
    provenance: Provenance
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/models.py tests/test_models.py
git commit -m "feat: core data models"
```

---

### Task 4: NoteRenderer (pure markdown)

**Files:**
- Create: `src/study_notes/renderer.py`
- Create: `tests/test_renderer.py`

**Interfaces:**
- Consumes: `Topic`, `Card`, `Provenance` from `study_notes.models`.
- Produces:
  - `render_card(card: Card, frame_path: str | None = None) -> str` — inline `::` for short/plain cards; multi-line `?` form when `frame_path` is given or the answer contains a newline.
  - `render_note(topic: Topic, category: str, frame_paths: dict[int, str] | None = None) -> str` — full note markdown with frontmatter, `## Core ideas`, `## Study cards`. `frame_paths` maps card index → embed path.
  - `render_update_section(topic: Topic, on: date, frame_paths: dict[int, str] | None = None) -> str` — a dated `## Update (YYYY-MM-DD)` block for non-destructive merges.

- [ ] **Step 1: Write the failing test**

`tests/test_renderer.py`:
```python
from datetime import date

from study_notes.models import Card, Provenance, Topic
from study_notes.renderer import render_card, render_note, render_update_section


def _topic():
    prov = Provenance(origin="https://youtube.com/watch?v=abc", input_type="youtube",
                      captured_at=date(2026, 7, 26), source_date=date(2025, 11, 14))
    return Topic(
        title="Raft Consensus",
        tags=["consensus", "youtube"],
        summary=["Leader election picks one leader per term.", "Logs replicate from leader."],
        cards=[
            Card("What is a term in Raft?", "A logical clock period with one leader."),
            Card("What triggers a new term?", "A failed election or leader timeout.", timestamp="00:14:32"),
        ],
        provenance=prov,
    )


def test_render_card_inline_for_short():
    c = Card("Q short", "A short")
    assert render_card(c) == "Q short::A short"


def test_render_card_multiline_with_frame():
    c = Card("What triggers a new term?", "A failed election or leader timeout.", timestamp="00:14:32")
    out = render_card(c, frame_path="06 - Attachments/frames/raft_00-14-32.jpg")
    assert out == (
        "What triggers a new term?\n"
        "?\n"
        "A failed election or leader timeout.\n"
        "![[06 - Attachments/frames/raft_00-14-32.jpg]]"
    )


def test_render_note_has_frontmatter_and_sections():
    md = render_note(_topic(), category="Distributed Systems",
                     frame_paths={1: "06 - Attachments/frames/raft_00-14-32.jpg"})
    assert md.startswith("---\n")
    assert "title: Raft Consensus" in md
    assert "category: Distributed Systems" in md
    assert "type: study-note" in md
    assert "source: https://youtube.com/watch?v=abc" in md
    assert "source_type: youtube" in md
    assert "source_date: 2025-11-14" in md
    assert "captured_at: 2026-07-26" in md
    assert "supersedes: []" in md
    assert "## Core ideas" in md
    assert "- Leader election picks one leader per term." in md
    assert "## Study cards" in md
    assert "What is a term in Raft?::A logical clock period with one leader." in md
    assert "![[06 - Attachments/frames/raft_00-14-32.jpg]]" in md


def test_render_update_section_is_dated():
    section = render_update_section(_topic(), on=date(2026, 7, 26))
    assert section.startswith("## Update (2026-07-26)")
    assert "What is a term in Raft?" in section
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_renderer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.renderer'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/renderer.py`:
```python
from datetime import date

from study_notes.models import Card, Topic


def render_card(card: Card, frame_path: str | None = None) -> str:
    multiline = frame_path is not None or "\n" in card.answer
    if not multiline:
        sep = ":::" if False else "::"
        return f"{card.question}{sep}{card.answer}"
    lines = [card.question, "?", card.answer]
    if frame_path is not None:
        lines.append(f"![[{frame_path}]]")
    return "\n".join(lines)


def _frontmatter(topic: Topic, category: str) -> str:
    p = topic.provenance
    rows = [
        "---",
        f"title: {topic.title}",
        f"category: {category}",
        "type: study-note",
        f"tags: [{', '.join(topic.tags)}]",
        f"source: {p.origin}",
        f"source_type: {p.input_type}",
        f"source_date: {p.source_date.isoformat() if p.source_date else ''}",
        f"captured_at: {p.captured_at.isoformat()}",
        "supersedes: []",
        "---",
    ]
    return "\n".join(rows)


def _cards_block(topic: Topic, frame_paths: dict[int, str] | None) -> str:
    frame_paths = frame_paths or {}
    return "\n\n".join(
        render_card(card, frame_paths.get(i)) for i, card in enumerate(topic.cards)
    )


def render_note(topic: Topic, category: str,
                frame_paths: dict[int, str] | None = None) -> str:
    ideas = "\n".join(f"- {line}" for line in topic.summary)
    return (
        f"{_frontmatter(topic, category)}\n\n"
        f"## Core ideas\n{ideas}\n\n"
        f"## Study cards\n{_cards_block(topic, frame_paths)}\n"
    )


def render_update_section(topic: Topic, on: date,
                          frame_paths: dict[int, str] | None = None) -> str:
    ideas = "\n".join(f"- {line}" for line in topic.summary)
    return (
        f"## Update ({on.isoformat()})\n{ideas}\n\n"
        f"{_cards_block(topic, frame_paths)}\n"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_renderer.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Refactor the dead `sep` branch and re-run**

Replace the `render_card` body's `sep` lines with a direct inline return:
```python
    if not multiline:
        return f"{card.question}::{card.answer}"
```
Run: `uv run pytest tests/test_renderer.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/study_notes/renderer.py tests/test_renderer.py
git commit -m "feat: pure markdown note renderer"
```

---

### Task 5: Embedder seam (protocol + fake + BGE-M3)

**Files:**
- Create: `src/study_notes/embedding.py`
- Create: `tests/test_embedding.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Embedder` — a `typing.Protocol` with `embed(texts: list[str]) -> list[list[float]]` returning 1024-dim dense vectors.
  - `FakeEmbedder(dim: int = 1024)` — deterministic hash-based vectors for fast tests.
  - `BGEM3Embedder(model_name: str = "BAAI/bge-m3")` — real implementation via `FlagEmbedding`, lazily loaded, MPS/fp16.

- [ ] **Step 1: Write the failing test (fake only; real model is a slow test)**

`tests/test_embedding.py`:
```python
import pytest

from study_notes.embedding import Embedder, FakeEmbedder


def test_fake_embedder_dim_and_determinism():
    emb: Embedder = FakeEmbedder(dim=1024)
    a = emb.embed(["hello world"])
    b = emb.embed(["hello world"])
    assert len(a) == 1
    assert len(a[0]) == 1024
    assert a == b  # deterministic


def test_fake_embedder_differs_by_text():
    emb = FakeEmbedder(dim=1024)
    out = emb.embed(["alpha", "beta"])
    assert out[0] != out[1]


@pytest.mark.slow
def test_bge_m3_embedder_shape():
    from study_notes.embedding import BGEM3Embedder

    emb = BGEM3Embedder()
    out = emb.embed(["distributed consensus"])
    assert len(out) == 1
    assert len(out[0]) == 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_embedding.py -m "not slow" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.embedding'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/embedding.py`:
```python
import hashlib
import math
from typing import Protocol, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class FakeEmbedder:
    """Deterministic, dependency-free embedder for fast tests."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            seed = hashlib.sha256(text.encode()).digest()
            raw = [seed[i % len(seed)] / 255.0 for i in range(self.dim)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            vectors.append([v / norm for v in raw])
        return vectors


class BGEM3Embedder:
    """Real BGE-M3 dense embedder via FlagEmbedding (MPS/fp16). Lazily loaded."""

    def __init__(self, model_name: str = "BAAI/bge-m3") -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel

            self._model = BGEM3FlagModel(self.model_name, use_fp16=True)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        out = model.encode(texts, return_dense=True,
                           return_sparse=False, return_colbert_vecs=False)
        return [list(map(float, v)) for v in out["dense_vecs"]]
```

- [ ] **Step 4: Run the fast tests**

Run: `uv run pytest tests/test_embedding.py -m "not slow" -v`
Expected: PASS (2 passed). The `slow` test is deselected.

- [ ] **Step 5: (Optional, one-time) Run the real-model test**

Run: `uv run pytest tests/test_embedding.py -m slow -v`
Expected: PASS after downloading BGE-M3 (~2 GB, first run only). Skip if offline; the fake covers all downstream logic.

- [ ] **Step 6: Commit**

```bash
git add src/study_notes/embedding.py tests/test_embedding.py
git commit -m "feat: embedder protocol with fake and BGE-M3 implementations"
```

---

### Task 6: PostgreSQL schema + connection helper

**Files:**
- Create: `src/study_notes/db.py`
- Create: `src/study_notes/schema.sql`
- Create: `tests/conftest.py`
- Create: `tests/test_db.py`
- Create: `README-dev.md` (DB setup instructions)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `connect(database_url: str)` → a `psycopg.Connection` with `pgvector` registered.
  - `apply_schema(conn)` → creates the extension, `categories`, and `notes` tables idempotently from `schema.sql`.
  - Schema: `categories(name PK, description)`, `notes(path PK, title, category FK, content, captured_at, source, source_type, source_date, dense_vec vector(1024), fts tsvector generated)`, with HNSW, GIN, and category indexes.

- [ ] **Step 1: Document local DB setup**

`README-dev.md`:
```markdown
# Dev setup

## PostgreSQL + pgvector (Docker via Colima)

The database runs in a container defined by `docker-compose.yml`
(`pgvector/pgvector:pg17` — Postgres 17 with pgvector preinstalled). On a Mac
without Docker Desktop, use Colima as the runtime:

    brew install colima docker docker-compose
    colima start
    docker compose up -d          # starts Postgres + pgvector

This creates two databases: `study_notes` (main) and `study_notes_test` (tests,
created by `docker/initdb/01-create-test-db.sql`). Connection URL:

    postgresql://postgres:postgres@localhost:5432/study_notes

Stop / reset:

    docker compose down           # stop
    docker compose down -v        # stop and wipe the data volume

## Tests

    export STUDY_NOTES_TEST_DB="postgresql://postgres:postgres@localhost:5432/study_notes_test"
    uv run pytest -m "not slow and not integration"   # fast unit tests
    uv run pytest -m integration                       # needs the DB container up
    uv run pytest -m slow                               # downloads BGE-M3
```

- [ ] **Step 2: Write `schema.sql`**

`src/study_notes/schema.sql`:
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS categories (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS notes (
    path        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL REFERENCES categories(name) ON UPDATE CASCADE,
    content     TEXT NOT NULL,
    captured_at DATE NOT NULL,
    source      TEXT,
    source_type TEXT,
    source_date DATE,
    dense_vec   vector(1024),
    fts         tsvector GENERATED ALWAYS AS
                (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,''))) STORED
);

CREATE INDEX IF NOT EXISTS notes_dense_idx ON notes USING hnsw (dense_vec vector_cosine_ops);
CREATE INDEX IF NOT EXISTS notes_fts_idx   ON notes USING gin (fts);
CREATE INDEX IF NOT EXISTS notes_cat_idx   ON notes (category);
```

- [ ] **Step 3: Write the shared test DB fixture**

`tests/conftest.py`:
```python
import os

import pytest


TEST_DB_URL = os.environ.get(
    "STUDY_NOTES_TEST_DB",
    "postgresql://postgres:postgres@localhost:5432/study_notes_test",
)


@pytest.fixture
def db_conn():
    """A clean schema-applied connection; rows are torn down after each test."""
    from study_notes.db import apply_schema, connect

    conn = connect(TEST_DB_URL)
    apply_schema(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE notes, categories CASCADE;")
    conn.commit()
    yield conn
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE notes, categories CASCADE;")
    conn.commit()
    conn.close()
```

- [ ] **Step 4: Write the failing integration test**

`tests/test_db.py`:
```python
import pytest

pytestmark = pytest.mark.integration


def test_apply_schema_is_idempotent(db_conn):
    from study_notes.db import apply_schema

    apply_schema(db_conn)  # second application must not error
    with db_conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.notes'), to_regclass('public.categories');")
        notes_tbl, cats_tbl = cur.fetchone()
    assert notes_tbl == "notes"
    assert cats_tbl == "categories"


def test_insert_note_row(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO categories (name, description) VALUES (%s, %s);",
                    ("Distributed Systems", "d"))
        cur.execute(
            "INSERT INTO notes (path, title, category, content, captured_at) "
            "VALUES (%s, %s, %s, %s, %s);",
            ("a/Raft.md", "Raft", "Distributed Systems", "consensus body", "2026-07-26"),
        )
    db_conn.commit()
    with db_conn.cursor() as cur:
        cur.execute("SELECT title FROM notes WHERE path = %s;", ("a/Raft.md",))
        assert cur.fetchone()[0] == "Raft"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.db'`.

- [ ] **Step 6: Write minimal implementation**

`src/study_notes/db.py`:
```python
from importlib.resources import files

import psycopg
from pgvector.psycopg import register_vector


def connect(database_url: str) -> psycopg.Connection:
    conn = psycopg.connect(database_url)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.commit()
    register_vector(conn)
    return conn


def apply_schema(conn: psycopg.Connection) -> None:
    sql = files("study_notes").joinpath("schema.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
```

- [ ] **Step 7: Ensure `schema.sql` ships with the package**

Add to `pyproject.toml` under `[tool.hatch.build.targets.wheel]`:
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/study_notes"]
force-include = { "src/study_notes/schema.sql" = "study_notes/schema.sql" }
```
Re-install: `uv pip install -e ".[dev]"`

- [ ] **Step 8: Run the integration tests**

Run: `uv run pytest tests/test_db.py -v`
Expected: PASS (2 passed). (Requires the `study_notes_test` DB from Step 1.)

- [ ] **Step 9: Commit**

```bash
git add src/study_notes/db.py src/study_notes/schema.sql tests/conftest.py tests/test_db.py README-dev.md pyproject.toml
git commit -m "feat: postgres schema and connection helper"
```

---

### Task 7: VaultIndex — category-scoped hybrid retrieval

**Files:**
- Create: `src/study_notes/vault_index.py`
- Create: `tests/test_vault_index.py`

**Interfaces:**
- Consumes: `Embedder` (Task 5), `connect`/`apply_schema` (Task 6), `Note` (Task 3).
- Produces `VaultIndex`:
  - `__init__(self, conn, embedder: Embedder)`
  - `upsert_category(self, name: str, description: str = "") -> None`
  - `upsert_note(self, note: Note) -> None` — embeds `title + "\n" + content`, writes the row (insert or update on `path`).
  - `list_categories(self) -> list[Category]`
  - `find_related(self, query: str, category: str, k: int = 5) -> list[tuple[str, float]]` — returns `(path, rrf_score)` pairs, **filtered to `category`**, fusing dense + FTS with RRF (`k_rrf = 60`).

- [ ] **Step 1: Write the failing test**

`tests/test_vault_index.py`:
```python
from datetime import date

import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance

pytestmark = pytest.mark.integration


def _note(path, title, category, content):
    prov = Provenance(origin="src", input_type="markdown",
                      captured_at=date(2026, 7, 26), source_date=None)
    return Note(path=path, title=title, category=category, content=content, provenance=prov)


def _index(db_conn):
    from study_notes.vault_index import VaultIndex

    return VaultIndex(db_conn, FakeEmbedder(dim=1024))


def test_upsert_and_list_categories(db_conn):
    idx = _index(db_conn)
    idx.upsert_category("Distributed Systems", "consensus etc")
    idx.upsert_category("Biology", "cells")
    names = sorted(c.name for c in idx.list_categories())
    assert names == ["Biology", "Distributed Systems"]


def test_find_related_is_category_scoped(db_conn):
    idx = _index(db_conn)
    idx.upsert_category("Distributed Systems")
    idx.upsert_category("Biology")
    idx.upsert_note(_note("ds/raft.md", "Raft", "Distributed Systems",
                          "leader election consensus term log replication"))
    idx.upsert_note(_note("ds/paxos.md", "Paxos", "Distributed Systems",
                          "consensus quorum proposals"))
    idx.upsert_note(_note("bio/mitosis.md", "Mitosis", "Biology",
                          "consensus is also a word about cells dividing"))

    results = idx.find_related("consensus algorithm", category="Distributed Systems", k=5)
    paths = [p for p, _ in results]

    assert "bio/mitosis.md" not in paths          # never crosses categories
    assert all(p.startswith("ds/") for p in paths)
    assert len(paths) >= 1


def test_upsert_note_updates_in_place(db_conn):
    idx = _index(db_conn)
    idx.upsert_category("Distributed Systems")
    idx.upsert_note(_note("ds/raft.md", "Raft", "Distributed Systems", "old body"))
    idx.upsert_note(_note("ds/raft.md", "Raft", "Distributed Systems", "new body text"))
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*), max(content) FROM notes WHERE path = %s;", ("ds/raft.md",))
        count, content = cur.fetchone()
    assert count == 1
    assert content == "new body text"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_vault_index.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.vault_index'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/vault_index.py`:
```python
import psycopg

from study_notes.embedding import Embedder
from study_notes.models import Category, Note

RRF_K = 60

_HYBRID_SQL = """
WITH dense AS (
    SELECT path, ROW_NUMBER() OVER (ORDER BY dense_vec <=> %(qvec)s) AS rank
    FROM notes
    WHERE category = %(cat)s AND dense_vec IS NOT NULL
    ORDER BY dense_vec <=> %(qvec)s
    LIMIT %(k)s
),
lexical AS (
    SELECT path,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(fts, plainto_tsquery('english', %(q)s)) DESC
           ) AS rank
    FROM notes
    WHERE category = %(cat)s AND fts @@ plainto_tsquery('english', %(q)s)
    ORDER BY ts_rank(fts, plainto_tsquery('english', %(q)s)) DESC
    LIMIT %(k)s
)
SELECT n.path,
       COALESCE(1.0 / (%(rrf)s + d.rank), 0.0)
     + COALESCE(1.0 / (%(rrf)s + l.rank), 0.0) AS score
FROM notes n
LEFT JOIN dense   d ON n.path = d.path
LEFT JOIN lexical l ON n.path = l.path
WHERE (d.path IS NOT NULL OR l.path IS NOT NULL)
ORDER BY score DESC
LIMIT %(k)s;
"""


class VaultIndex:
    def __init__(self, conn: psycopg.Connection, embedder: Embedder) -> None:
        self.conn = conn
        self.embedder = embedder

    def upsert_category(self, name: str, description: str = "") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO categories (name, description) VALUES (%s, %s) "
                "ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description;",
                (name, description),
            )
        self.conn.commit()

    def list_categories(self) -> list[Category]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT name, description FROM categories ORDER BY name;")
            return [Category(name=n, description=d) for n, d in cur.fetchall()]

    def upsert_note(self, note: Note) -> None:
        vec = self.embedder.embed([f"{note.title}\n{note.content}"])[0]
        p = note.provenance
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notes (path, title, category, content, captured_at,
                                   source, source_type, source_date, dense_vec)
                VALUES (%(path)s, %(title)s, %(category)s, %(content)s, %(captured_at)s,
                        %(source)s, %(source_type)s, %(source_date)s, %(vec)s)
                ON CONFLICT (path) DO UPDATE SET
                    title = EXCLUDED.title,
                    category = EXCLUDED.category,
                    content = EXCLUDED.content,
                    captured_at = EXCLUDED.captured_at,
                    source = EXCLUDED.source,
                    source_type = EXCLUDED.source_type,
                    source_date = EXCLUDED.source_date,
                    dense_vec = EXCLUDED.dense_vec;
                """,
                {
                    "path": note.path, "title": note.title, "category": note.category,
                    "content": note.content, "captured_at": p.captured_at,
                    "source": p.origin, "source_type": p.input_type,
                    "source_date": p.source_date, "vec": vec,
                },
            )
        self.conn.commit()

    def find_related(self, query: str, category: str, k: int = 5) -> list[tuple[str, float]]:
        qvec = self.embedder.embed([query])[0]
        with self.conn.cursor() as cur:
            cur.execute(_HYBRID_SQL,
                        {"qvec": qvec, "q": query, "cat": category, "k": k, "rrf": RRF_K})
            return [(path, float(score)) for path, score in cur.fetchall()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_vault_index.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full fast + integration suite**

Run: `uv run pytest -m "not slow" -v`
Expected: PASS (all unit + integration tests green).

- [ ] **Step 6: Commit**

```bash
git add src/study_notes/vault_index.py tests/test_vault_index.py
git commit -m "feat: category-scoped hybrid VaultIndex (dense + FTS via RRF)"
```

---

## Self-Review

**Spec coverage (Plan 1 portion):**
- Config (§11) → Task 2. ✓
- Data models (§7) → Task 3. ✓
- Note & card format, incl. inline vs multi-line, frontmatter, frames, dated merge section (§10) → Task 4. ✓
- BGE-M3 via FlagEmbedding, dense 1024, not Ollama (§12) → Task 5. ✓
- PostgreSQL + pgvector schema, categories, provenance columns (§4, §9, §12) → Task 6. ✓
- Category-scoped hybrid retrieval with RRF; never crosses categories (§8, §12, §13) → Task 7 (test `test_find_related_is_category_scoped`). ✓
- Deferred to Plans 2–3 (correctly out of scope here): MCP tools, `fetch_youtube_transcript`, `extract_frame`, `vault_write` file I/O, `claude -p` orchestration, prompts, CLI, category/MOC folder creation on disk.

**Placeholder scan:** No TBD/TODO; every code and command step is concrete. ✓

**Type consistency:** `Embedder.embed(list[str]) -> list[list[float]]` used identically in Tasks 5 and 7; `Note`/`Provenance`/`Category` fields match Task 3 across Tasks 4, 6, 7; `find_related(query, category, k)` signature consistent between the interface block and Task 7 tests. Dense dimension `1024` consistent in Tasks 5, 6, 7. ✓

---

## Plans 2 and 3 (to be written after Plan 1 is built and reviewed)

- **Plan 2 — MCP tool server:** `fetch_youtube_transcript` (yt-dlp, timed segments), `list_categories`/`vault_search` (wrap `VaultIndex`), `extract_frame` (ffmpeg), `vault_write` (non-destructive file writes + category folder/MOC creation + MOC link maintenance, reusing `renderer.py`). Exposed as a local MCP server.
- **Plan 3 — Orchestrator, prompts & CLI:** per-task `claude -p` invocation (model + system-prompt + `--allowedTools` + `--mcp-config` + `--output-format json`), versioned prompt files, the self-verifying procedure, `study-notes add`/`reindex`, `--category`/`--note`/`--dry-run`, and end-to-end smoke tests against golden transcripts.
