# Study Notes — Plan 3: Orchestrator, Prompts & CLI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tool runnable end to end: `study-notes add <url|file>` ingests a source via a single agentic `claude -p` run that drives the MCP tools through a self-verifying procedure, and `study-notes reindex` rebuilds the search index from the vault.

**Architecture (single agentic run — chosen design):** Python owns three deterministic things — the dedup gate (IngestLog), launching one `claude -p` per input with the right flags/prompt/MCP config, and recording the ingestion log afterward. Claude, guided by `prompts/procedure.md`, does the reasoning and drives the MCP tools (fetch transcript → segment → extract → categorize via `vault_search` → frame → `check_slop` → `vault_write` → self-verify). We recover the written note paths deterministically from the `notes` table (they carry `source = <origin>`), not by parsing model text. `reindex` is pure Python.

**Tech Stack:** Python 3.12+, `argparse` (stdlib), `subprocess` (stdlib) to invoke the `claude` CLI, plus the merged Plan 1/2/2.5 modules. No new third-party deps.

## Global Constraints

- Python 3.12+; macOS/arm64. The app runs on the host (BGE-M3/MPS); Postgres + ffmpeg stay in Docker.
- **Single agentic run:** one `claude -p` per input. It passes `--model <[agent].model>`,
  `--append-system-prompt <procedure.md + anti-slop.md>`, `--mcp-config <generated>`,
  `--allowedTools <the MCP tool names>`, `--add-dir <input + vault>`, `--output-format json`.
  Under `--dry-run`, the write tool (`mcp__study-notes-tools__vault_write`) is omitted from
  `--allowedTools`.
- **Dedup gate runs first, in Python** (spec §8 step 0): compute `source_id`
  (`youtube_source_id`/`file_source_id`), `IngestLog.lookup`; if present and not `--force`, print
  "already ingested as <paths>" and exit 0 without invoking Claude. Record `IngestLog` only after
  a successful, non-dry-run write.
- **Written note paths are recovered from Postgres** (`SELECT path FROM notes WHERE source = %s`),
  not from model output. The procedure prompt instructs Claude to use the exact provided `source`
  string when calling `vault_write`.
- Reuse everything merged: identity/log (`ingest.py`), tools + MCP server (`tools/`, `mcp_server.py`),
  index/renderer/db (Plan 1), `slop_check`. Do NOT reimplement them.
- No LLM API keys (rides Claude Code auth). TDD: failing test first; commit after green. DRY, YAGNI.
- Pure/deterministic units (command building, result parsing, arg parsing, source resolution,
  reindex, config generation) are unit-tested; the live `claude -p` run is an `e2e`-marked manual
  validation, not an automated test.

---

### Task 1: `check_slop` MCP tool

**Files:**
- Modify: `src/study_notes/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `slop_check` (Plan 2.5).
- Produces: a sixth MCP tool `check_slop(text: str) -> list[dict]` returning
  `[{"pattern": str, "snippet": str}, ...]`, so the agent can screen a draft during self-verification.

- [ ] **Step 1: Update the failing registration test**

In `tests/test_mcp_server.py`, change the required-names set in `test_server_registers_all_five_tools`
to include `check_slop` (and rename the test):
```python
def test_server_registers_all_tools():
    from study_notes import mcp_server

    tool_names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert {
        "fetch_youtube_transcript", "list_categories", "vault_search",
        "extract_frame", "vault_write", "check_slop",
    } <= tool_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_server.py::test_server_registers_all_tools -v`
Expected: FAIL (`check_slop` not registered).

- [ ] **Step 3: Add the tool**

In `src/study_notes/mcp_server.py`, add near the other `@mcp.tool()` functions:
```python
@mcp.tool()
def check_slop(text: str) -> list[dict]:
    """Flag AI-slop writing patterns in a drafted note. Returns findings to fix before writing."""
    from study_notes.slop_check import slop_check

    return [{"pattern": f.pattern, "snippet": f.snippet} for f in slop_check(text)]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_server.py -v`
Expected: PASS (all mcp_server tests green).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: check_slop MCP tool for draft self-verification"
```

---

### Task 2: MCP config + `ClaudeRunner` (command build + result parse)

**Files:**
- Create: `src/study_notes/claude_runner.py`
- Create: `tests/test_claude_runner.py`

**Interfaces:**
- Consumes: `Config` (Plan 1).
- Produces:
  - `mcp_config_dict(config_path: str) -> dict` — the `{"mcpServers": {...}}` structure launching
    `uv run python -m study_notes.mcp_server` with `STUDY_NOTES_CONFIG=config_path`.
  - `TOOL_NAMES: list[str]` — the six `mcp__study-notes-tools__*` names; `WRITE_TOOL` the vault_write one.
  - `build_command(*, input_prompt, model, system_prompt, mcp_config_path, add_dirs, dry_run) -> list[str]`
    — pure; builds the `claude` argv.
  - `parse_result(stdout: str) -> str` — parses `--output-format json`, returns the `result` text;
    raises `ClaudeRunError` if `is_error` or unparseable.
  - `ClaudeRunError(Exception)`.
  - `run(cmd: list[str]) -> str` — executes, one retry on failure, returns `parse_result(stdout)`.

- [ ] **Step 1: Write the failing test**

`tests/test_claude_runner.py`:
```python
import json

import pytest

from study_notes.claude_runner import (
    ClaudeRunError,
    TOOL_NAMES,
    WRITE_TOOL,
    build_command,
    mcp_config_dict,
    parse_result,
)


def test_mcp_config_points_at_server_with_env():
    cfg = mcp_config_dict("/x/config.toml")
    server = cfg["mcpServers"]["study-notes-tools"]
    assert server["command"] == "uv"
    assert server["args"][-1] == "study_notes.mcp_server"
    assert server["env"]["STUDY_NOTES_CONFIG"] == "/x/config.toml"


def test_build_command_includes_flags_and_all_tools():
    cmd = build_command(
        input_prompt="ingest https://x", model="claude-opus-4-8",
        system_prompt="PROC", mcp_config_path="/tmp/mcp.json",
        add_dirs=["/vault"], dry_run=False,
    )
    assert cmd[0] == "claude" and "-p" in cmd
    assert "--model" in cmd and "claude-opus-4-8" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--mcp-config" in cmd and "/tmp/mcp.json" in cmd
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert WRITE_TOOL in allowed  # write tool present when not dry-run
    for name in TOOL_NAMES:
        assert name in allowed


def test_build_command_dry_run_omits_write_tool():
    cmd = build_command(
        input_prompt="p", model="m", system_prompt="s",
        mcp_config_path="/tmp/mcp.json", add_dirs=[], dry_run=True,
    )
    allowed = cmd[cmd.index("--allowedTools") + 1]
    assert WRITE_TOOL not in allowed
    assert "mcp__study-notes-tools__vault_search" in allowed  # read tools still allowed


def test_parse_result_returns_result_text():
    out = json.dumps({"type": "result", "is_error": False, "result": "done: wrote 2 notes"})
    assert parse_result(out) == "done: wrote 2 notes"


def test_parse_result_raises_on_error_envelope():
    out = json.dumps({"type": "result", "is_error": True, "result": "boom"})
    with pytest.raises(ClaudeRunError):
        parse_result(out)


def test_parse_result_raises_on_garbage():
    with pytest.raises(ClaudeRunError):
        parse_result("not json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_claude_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.claude_runner'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/claude_runner.py`:
```python
import json
import subprocess

_SERVER = "study-notes-tools"
_PREFIX = f"mcp__{_SERVER}__"
TOOL_NAMES = [
    f"{_PREFIX}fetch_youtube_transcript",
    f"{_PREFIX}list_categories",
    f"{_PREFIX}vault_search",
    f"{_PREFIX}extract_frame",
    f"{_PREFIX}check_slop",
    f"{_PREFIX}vault_write",
]
WRITE_TOOL = f"{_PREFIX}vault_write"


class ClaudeRunError(Exception):
    """The `claude -p` run failed or returned an error envelope."""


def mcp_config_dict(config_path: str) -> dict:
    return {
        "mcpServers": {
            _SERVER: {
                "command": "uv",
                "args": ["run", "python", "-m", "study_notes.mcp_server"],
                "env": {"STUDY_NOTES_CONFIG": config_path},
            }
        }
    }


def build_command(*, input_prompt: str, model: str, system_prompt: str,
                  mcp_config_path: str, add_dirs: list[str], dry_run: bool) -> list[str]:
    tools = [t for t in TOOL_NAMES if not (dry_run and t == WRITE_TOOL)]
    cmd = [
        "claude", "-p", input_prompt,
        "--model", model,
        "--append-system-prompt", system_prompt,
        "--mcp-config", mcp_config_path,
        "--allowedTools", ",".join(tools),
        "--output-format", "json",
    ]
    for d in add_dirs:
        cmd += ["--add-dir", d]
    return cmd


def parse_result(stdout: str) -> str:
    try:
        env = json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as e:
        raise ClaudeRunError(f"could not parse claude output: {e}") from e
    if env.get("is_error"):
        raise ClaudeRunError(f"claude reported an error: {env.get('result')!r}")
    return env.get("result", "")


def run(cmd: list[str]) -> str:
    last: Exception | None = None
    for _ in range(2):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            try:
                return parse_result(proc.stdout)
            except ClaudeRunError as e:
                last = e
        else:
            last = ClaudeRunError(
                f"claude exited {proc.returncode}: {proc.stderr[-500:]}")
    raise last if last else ClaudeRunError("claude run failed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_claude_runner.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/claude_runner.py tests/test_claude_runner.py
git commit -m "feat: ClaudeRunner (mcp config, command build, json result parse)"
```

---

### Task 3: The procedure system prompt

**Files:**
- Create: `prompts/procedure.md`
- Create: `tests/test_procedure_prompt.py`

**Interfaces:**
- Consumes: nothing (content artifact).
- Produces: `prompts/procedure.md` — the master system prompt encoding the self-verifying
  procedure. A light test asserts it names every MCP tool and the key steps.

- [ ] **Step 1: Write the failing test**

`tests/test_procedure_prompt.py`:
```python
from pathlib import Path

PROC = Path("prompts/procedure.md")


def test_procedure_names_all_tools_and_steps():
    text = PROC.read_text()
    for tool in ["fetch_youtube_transcript", "list_categories", "vault_search",
                 "extract_frame", "check_slop", "vault_write"]:
        assert tool in text, f"procedure must mention {tool}"
    for step in ["Segment", "Extract", "categor", "Verify"]:
        assert step.lower() in text.lower()
    # must instruct using the exact provided source string
    assert "source" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_procedure_prompt.py -v`
Expected: FAIL (file missing).

- [ ] **Step 3: Write the prompt**

`prompts/procedure.md`:
```markdown
# Study-notes ingestion procedure

You turn one source (a YouTube URL or a document) into concise Obsidian study notes with
review-ready flashcards, using ONLY the provided MCP tools. Follow these steps in order and
run the self-checks. Do not ask the user anything — this is a headless run.

## Inputs you are given
The user message contains the source and its exact `source` string to record, plus optional
directives: a forced `category`, a forced merge `target_note`, and whether this is a dry run.

## Steps
1. **Ingest.** For a YouTube URL, call `fetch_youtube_transcript`. For a document, read the file
   directly (you have --add-dir access); convert .docx with `textutil`/`pandoc` if needed.
2. **Segment** the source into distinct topics.
   *Self-check:* topics are mutually distinct; every meaningful section maps to one; no overlap.
3. **Extract** per topic: a concise `## Core ideas` summary (tight bullets) and Q&A study cards.
   *Self-check:* every answer is grounded in the source; every timestamped card cites a real
   transcript timestamp.
4. **Frame** (YouTube only): for each timestamped card, call `extract_frame` and embed the
   returned path in that card.
5. **Resolve category.** If a category directive was given, use it. Otherwise call
   `list_categories` and choose the fitting existing category, or propose a new one only on
   genuine non-overlap (avoid near-duplicates).
6. **Resolve placement.** If a target_note directive was given, merge into it. Otherwise call
   `vault_search(query, category)` — scoped to the chosen category — and decide new note vs
   merge, stating your reasoning.
7. **Screen for slop.** Before writing each note, call `check_slop` on its full markdown; revise
   until it returns no findings you agree are slop. Follow the appended writing-style guide.
8. **Write.** Call `vault_write` with the note. Pass the EXACT `source` string you were given so
   the note is traceable. New notes never overwrite; merges append a dated update section.
9. **Verify (closing gate).** Re-read what `vault_write` returned; confirm each note is
   well-formed, correctly categorized/placed, and complete.

## Dry run
If told this is a dry run, do steps 1-7 and report the proposed topics, categories, and
placements. Do NOT call `vault_write`.

## Finish
End with a one-line summary of what you wrote (or proposed, on a dry run).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_procedure_prompt.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add prompts/procedure.md tests/test_procedure_prompt.py
git commit -m "feat: master procedure system prompt for the agentic run"
```

---

### Task 4: `paths_for_source` + orchestrator `add` flow

**Files:**
- Modify: `src/study_notes/vault_index.py` (add `paths_for_source`)
- Create: `src/study_notes/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Config`, `IngestLog`, `youtube_source_id`/`file_source_id`, `ClaudeRunner.run`,
  `VaultIndex`.
- Produces:
  - `VaultIndex.paths_for_source(source: str) -> list[str]` — note paths whose `source` column matches.
  - `resolve_source(raw: str) -> tuple[str, str, str]` → `(source_id, source_type, origin)`;
    `source_type` is `"youtube"` if it parses as a YouTube URL else `"file"`.
  - `@dataclass AddResult{ status: str, source_id: str, note_paths: list[str], message: str }`
    where `status ∈ {"ingested", "skipped", "dry_run"}`.
  - `add(raw_input, *, config, index, ingest_log, run_claude, build_system_prompt, category=None,
    note=None, dry_run=False, force=False) -> AddResult` — the dedup gate + run + record flow.
    `run_claude` and `build_system_prompt` are injected callables (so tests stub the model run).

- [ ] **Step 1: Write the failing test**

`tests/test_orchestrator.py`:
```python
from datetime import date

import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _cfg(tmp_path):
    from study_notes.config import Config
    return Config(vault_path=tmp_path, notes_root="04 - Resources",
                  attachments_dir="06 - Attachments", frames_subdir="frames",
                  database_url="unused", embedding_model="fake",
                  models={}, prompts={}, dry_run=False)


def _seed_note(index, source):
    prov = Provenance(origin=source, input_type="youtube",
                      captured_at=date.today(), source_date=None)
    index.upsert_category("Web APIs")
    index.upsert_note(Note(path="04 - Resources/Web APIs/HTTP.md", title="HTTP",
                           category="Web APIs", content="status codes", provenance=prov))


def test_resolve_source_youtube_vs_file(tmp_path):
    from study_notes.orchestrator import resolve_source
    sid, stype, origin = resolve_source("https://youtu.be/772CUg2xYAo")
    assert stype == "youtube" and sid == "youtube:772CUg2xYAo"
    f = tmp_path / "d.txt"; f.write_text("hi")
    sid2, stype2, _ = resolve_source(str(f))
    assert stype2 == "file" and sid2.startswith("sha256:")


def test_add_skips_already_ingested(db_conn, tmp_path):
    from study_notes.ingest import IngestLog
    from study_notes.orchestrator import add

    index = VaultIndex(db_conn, FakeEmbedder())
    log = IngestLog(db_conn)
    url = "https://youtu.be/772CUg2xYAo"
    log.record("youtube:772CUg2xYAo", "youtube", url, ["old/path.md"])

    called = {"ran": False}
    def fake_run(cmd): called["ran"] = True; return "should not run"

    res = add(url, config=_cfg(tmp_path), index=index, ingest_log=log,
              run_claude=fake_run, build_system_prompt=lambda dry: "sp")
    assert res.status == "skipped"
    assert res.note_paths == ["old/path.md"]
    assert called["ran"] is False  # dedup gate short-circuits before Claude


def test_add_runs_records_and_returns_paths(db_conn, tmp_path):
    from study_notes.ingest import IngestLog
    from study_notes.orchestrator import add

    index = VaultIndex(db_conn, FakeEmbedder())
    log = IngestLog(db_conn)
    url = "https://youtu.be/772CUg2xYAo"

    def fake_run(cmd):
        _seed_note(index, url)  # simulate Claude writing a note via vault_write
        return "wrote 1 note"

    res = add(url, config=_cfg(tmp_path), index=index, ingest_log=log,
              run_claude=fake_run, build_system_prompt=lambda dry: "sp")
    assert res.status == "ingested"
    assert res.note_paths == ["04 - Resources/Web APIs/HTTP.md"]
    assert log.lookup("youtube:772CUg2xYAo").note_paths == res.note_paths  # recorded


def test_add_dry_run_does_not_record(db_conn, tmp_path):
    from study_notes.ingest import IngestLog
    from study_notes.orchestrator import add

    index = VaultIndex(db_conn, FakeEmbedder())
    log = IngestLog(db_conn)
    url = "https://youtu.be/772CUg2xYAo"

    res = add(url, config=_cfg(tmp_path), index=index, ingest_log=log,
              run_claude=lambda cmd: "proposed", build_system_prompt=lambda dry: "sp",
              dry_run=True)
    assert res.status == "dry_run"
    assert log.lookup("youtube:772CUg2xYAo") is None  # nothing recorded on dry run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.orchestrator'`.

- [ ] **Step 3: Add `paths_for_source` to `VaultIndex`**

In `src/study_notes/vault_index.py`, add a method to the `VaultIndex` class:
```python
    def paths_for_source(self, source: str) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT path FROM notes WHERE source = %s ORDER BY path;", (source,))
            return [r[0] for r in cur.fetchall()]
```

- [ ] **Step 4: Write the orchestrator**

`src/study_notes/orchestrator.py`:
```python
from dataclasses import dataclass
from pathlib import Path

from study_notes.config import Config
from study_notes.ingest import (
    IngestLog,
    SourceIdentityError,
    file_source_id,
    youtube_source_id,
)
from study_notes.vault_index import VaultIndex


@dataclass
class AddResult:
    status: str  # "ingested" | "skipped" | "dry_run"
    source_id: str
    note_paths: list[str]
    message: str


def resolve_source(raw: str) -> tuple[str, str, str]:
    try:
        return youtube_source_id(raw), "youtube", raw
    except SourceIdentityError:
        pass
    return file_source_id(Path(raw)), "file", str(raw)


def _input_prompt(origin: str, source_type: str, category, note, dry_run) -> str:
    lines = [
        f"Ingest this {source_type} source into the vault following your procedure.",
        f"Source: {origin}",
        f"Use exactly this string as the note `source`: {origin}",
    ]
    if category:
        lines.append(f"Directive: force category = {category!r}.")
    if note:
        lines.append(f"Directive: merge into target_note = {note!r}.")
    if dry_run:
        lines.append("This is a DRY RUN: do not call vault_write; report your plan.")
    return "\n".join(lines)


def add(raw_input: str, *, config: Config, index: VaultIndex, ingest_log: IngestLog,
        run_claude, build_system_prompt, category=None, note=None,
        dry_run: bool = False, force: bool = False) -> AddResult:
    source_id, source_type, origin = resolve_source(raw_input)

    if not force:
        existing = ingest_log.lookup(source_id)
        if existing is not None:
            return AddResult("skipped", source_id, existing.note_paths,
                             f"already ingested as {existing.note_paths}")

    system_prompt = build_system_prompt(dry_run)
    prompt = _input_prompt(origin, source_type, category, note, dry_run)
    # run_claude receives the fully-built command; here we pass the prompt+sp via a tuple the
    # CLI's real runner closes over. Tests stub run_claude directly.
    run_claude((prompt, system_prompt, dry_run))

    if dry_run:
        return AddResult("dry_run", source_id, [], "dry run — nothing written")

    note_paths = index.paths_for_source(origin)
    ingest_log.record(source_id, source_type, origin, note_paths)
    return AddResult("ingested", source_id, note_paths,
                     f"ingested {len(note_paths)} note(s)")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add src/study_notes/vault_index.py src/study_notes/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add-flow orchestrator (dedup gate, run, record) + paths_for_source"
```

---

### Task 5: `reindex` (vault → Postgres)

**Files:**
- Create: `src/study_notes/reindex.py`
- Create: `tests/test_reindex.py`

**Interfaces:**
- Consumes: `Config`, `VaultIndex`.
- Produces:
  - `parse_frontmatter(md: str) -> dict` — minimal YAML-frontmatter reader (the keys we write:
    `title`, `category`, `source`, `source_type`, `source_date`, `captured_at`). Pure.
  - `reindex(config: Config, index: VaultIndex) -> int` — walk `vault/notes_root/*/*.md` (skip the
    per-category `<Category>.md` MOC files), upsert each note + its category, return the count.

- [ ] **Step 1: Write the failing test**

`tests/test_reindex.py`:
```python
import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration

NOTE = """---
title: Raft
category: Distributed Systems
source: https://youtu.be/abc
source_type: youtube
source_date: 2025-11-14
captured_at: 2026-07-27
supersedes: []
---

## Core ideas
- Leaders per term.
"""


def _cfg(tmp_path):
    from study_notes.config import Config
    return Config(vault_path=tmp_path, notes_root="04 - Resources",
                  attachments_dir="06 - Attachments", frames_subdir="frames",
                  database_url="unused", embedding_model="fake",
                  models={}, prompts={}, dry_run=False)


def test_parse_frontmatter_reads_keys():
    from study_notes.reindex import parse_frontmatter
    fm = parse_frontmatter(NOTE)
    assert fm["title"] == "Raft"
    assert fm["category"] == "Distributed Systems"
    assert fm["source"] == "https://youtu.be/abc"


def test_reindex_upserts_notes_and_skips_moc(db_conn, tmp_path):
    from study_notes.reindex import reindex
    cat = tmp_path / "04 - Resources" / "Distributed Systems"
    cat.mkdir(parents=True)
    (cat / "Raft.md").write_text(NOTE)
    (cat / "Distributed Systems.md").write_text("---\ntype: moc\n---\n# MOC\n")  # skipped

    index = VaultIndex(db_conn, FakeEmbedder())
    count = reindex(_cfg(tmp_path), index)
    assert count == 1  # MOC not indexed
    hits = index.find_related("leaders per term", category="Distributed Systems", k=5)
    assert any("Raft" in p for p, _ in hits)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reindex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.reindex'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/reindex.py`:
```python
from datetime import date
from pathlib import Path

from study_notes.config import Config
from study_notes.models import Note, Provenance
from study_notes.vault_index import VaultIndex


def parse_frontmatter(md: str) -> dict:
    if not md.startswith("---"):
        return {}
    end = md.find("\n---", 3)
    if end == -1:
        return {}
    out: dict = {}
    for line in md[3:end].splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip().strip('"')
    return out


def _date(val: str | None):
    try:
        return date.fromisoformat(val) if val else None
    except ValueError:
        return None


def reindex(config: Config, index: VaultIndex) -> int:
    root = config.vault_path / config.notes_root
    count = 0
    for md_path in sorted(root.glob("*/*.md")):
        # skip the per-category MOC file (named <Category>.md inside <Category>/)
        if md_path.stem == md_path.parent.name:
            continue
        text = md_path.read_text()
        fm = parse_frontmatter(text)
        category = fm.get("category") or md_path.parent.name
        rel = str(md_path.relative_to(config.vault_path))
        index.upsert_category(category)
        prov = Provenance(
            origin=fm.get("source", ""), input_type=fm.get("source_type", ""),
            captured_at=_date(fm.get("captured_at")) or date.today(),
            source_date=_date(fm.get("source_date")),
        )
        index.upsert_note(Note(path=rel, title=fm.get("title", md_path.stem),
                               category=category, content=text, provenance=prov))
        count += 1
    return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_reindex.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/reindex.py tests/test_reindex.py
git commit -m "feat: reindex vault markdown into the Postgres index"
```

---

### Task 6: CLI wiring + console script

**Files:**
- Create: `src/study_notes/cli.py`
- Create: `tests/test_cli.py`
- Create: `config.toml` (runnable default)
- Modify: `pyproject.toml` (console script)
- Modify: `README-dev.md` (usage)

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `parse_args(argv: list[str]) -> argparse.Namespace` — `add <input> [--category][--note][--dry-run][--force][--config]` and `reindex [--config]`.
  - `build_system_prompt(config, dry_run) -> str` — reads `procedure.md` + `anti-slop.md`, concatenated.
  - `main(argv=None) -> int` — dispatches; wires real `Config`, `VaultIndex` (BGE-M3 + connect),
    `IngestLog`, a real `run_claude` closure (writes the mcp-config to a temp file, calls
    `claude_runner.run(build_command(...))`), and the orchestrator. Returns an exit code.

- [ ] **Step 1: Write the failing test (arg parsing + system-prompt assembly are the unit-testable parts)**

`tests/test_cli.py`:
```python
from pathlib import Path

from study_notes.cli import build_system_prompt, parse_args


def test_parse_add_with_flags():
    ns = parse_args(["add", "https://youtu.be/x", "--category", "Web APIs",
                     "--dry-run", "--force"])
    assert ns.command == "add"
    assert ns.input == "https://youtu.be/x"
    assert ns.category == "Web APIs"
    assert ns.dry_run is True and ns.force is True


def test_parse_reindex():
    ns = parse_args(["reindex"])
    assert ns.command == "reindex"


def test_build_system_prompt_concatenates_procedure_and_antislop(tmp_path):
    from study_notes.config import Config
    proc = tmp_path / "procedure.md"; proc.write_text("PROCEDURE-BODY")
    slop = tmp_path / "anti-slop.md"; slop.write_text("ANTISLOP-BODY")
    cfg = Config(vault_path=tmp_path, notes_root="r", attachments_dir="a",
                 frames_subdir="frames", database_url="u", embedding_model="m",
                 models={}, prompts={"procedure": str(proc), "anti_slop": str(slop)},
                 dry_run=False)
    sp = build_system_prompt(cfg, dry_run=False)
    assert "PROCEDURE-BODY" in sp and "ANTISLOP-BODY" in sp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.cli'`.

- [ ] **Step 3: Extend `Config` to carry `agent_model`**

The `[agent]` config section is new. In `src/study_notes/config.py`, add `agent_model` as the
**last** field of the `Config` dataclass **with a default**, so existing `Config(...)` constructions
(in tests and elsewhere) keep working unchanged:
```python
    agent_model: str = "claude-opus-4-8"
```
(It must be last because it's the only field with a default.) Then set it in `load_config`:
```python
        agent_model=data.get("agent", {}).get("model", "claude-opus-4-8"),
```
No test fixtures need changing — the default covers any `Config(...)` that omits it.

- [ ] **Step 4: Write the CLI**

`src/study_notes/cli.py`:
```python
import argparse
import json
import sys
import tempfile
from pathlib import Path

from study_notes.claude_runner import build_command, mcp_config_dict, run
from study_notes.config import Config, load_config
from study_notes.orchestrator import add


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="study-notes")
    p.add_argument("--config", default="config.toml")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("add", help="ingest one source")
    a.add_argument("input")
    a.add_argument("--category")
    a.add_argument("--note")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--force", action="store_true")

    sub.add_parser("reindex", help="rebuild the index from the vault")
    return p.parse_args(argv)


def build_system_prompt(config: Config, dry_run: bool) -> str:
    procedure = Path(config.prompts["procedure"]).read_text()
    anti_slop = Path(config.prompts["anti_slop"]).read_text()
    return f"{procedure}\n\n{anti_slop}"


def _make_index(config: Config):
    from study_notes.db import connect
    from study_notes.embedding import BGEM3Embedder
    from study_notes.vault_index import VaultIndex

    return VaultIndex(connect(config.database_url), BGEM3Embedder(config.embedding_model))


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(sys.argv[1:] if argv is None else argv)
    config = load_config(Path(ns.config))

    if ns.command == "reindex":
        from study_notes.reindex import reindex
        n = reindex(config, _make_index(config))
        print(f"reindexed {n} note(s)")
        return 0

    from study_notes.ingest import IngestLog
    index = _make_index(config)
    ingest_log = IngestLog(index.conn)

    def run_claude(payload) -> str:
        prompt, system_prompt, dry_run = payload
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(mcp_config_dict(str(Path(ns.config).resolve())), f)
            mcp_path = f.name
        cmd = build_command(
            input_prompt=prompt, model=config.agent_model, system_prompt=system_prompt,
            mcp_config_path=mcp_path, add_dirs=[str(config.vault_path)], dry_run=dry_run,
        )
        return run(cmd)

    res = add(ns.input, config=config, index=index, ingest_log=ingest_log,
              run_claude=run_claude,
              build_system_prompt=lambda dry: build_system_prompt(config, dry),
              category=ns.category, note=ns.note, dry_run=ns.dry_run, force=ns.force)
    print(res.message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Add the console script + write a runnable `config.toml`**

In `pyproject.toml`, add:
```toml
[project.scripts]
study-notes = "study_notes.cli:main"
```
Create `config.toml` at repo root (adjust `vault_path` to a real vault under $HOME):
```toml
vault_path = "/Users/andrewpoole/vault"
notes_root = "04 - Resources"
attachments_dir = "06 - Attachments"
frames_subdir = "frames"

[database]
url = "postgresql://postgres:postgres@localhost:5432/study_notes"

[embedding]
model = "BAAI/bge-m3"

[agent]
model = "claude-opus-4-8"

[prompts]
procedure = "prompts/procedure.md"
anti_slop = "prompts/anti-slop.md"

[run]
dry_run = false
```
Reinstall so the script + config-dependent tests resolve: `uv pip install -e ".[dev]"`

- [ ] **Step 6: Run tests to verify they pass (and fix any `Config(` fixtures needing `agent_model`)**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (3 passed).
Then run the full offline suite and fix any test that builds `Config(...)` directly to include
`agent_model="test-model"`:
Run: `uv run pytest -m "not slow and not network and not ffmpeg and not docker" -q`
Expected: PASS.

- [ ] **Step 7: Document usage in `README-dev.md`**

Append:
```markdown

## Running the tool

    docker compose up -d                      # Postgres
    uv run study-notes reindex                # build the index from your vault
    uv run study-notes add https://youtu.be/<id>
    uv run study-notes add paper.pdf --category "Machine Learning"
    uv run study-notes add https://youtu.be/<id> --dry-run   # preview, no writes
    uv run study-notes add https://youtu.be/<id> --force     # re-ingest

Requires Claude Code installed and authenticated (the run rides that auth).
```

- [ ] **Step 8: Commit**

```bash
git add src/study_notes/cli.py tests/test_cli.py src/study_notes/config.py config.toml pyproject.toml README-dev.md
git commit -m "feat: study-notes CLI (add/reindex) wiring the agentic run"
```

---

## Self-Review

**Spec coverage:**
- Single agentic `claude -p` run with MCP tools, procedure prompt, dry-run tool scoping (spec §8, §11) → Tasks 2, 3, 6. ✓
- Dedup gate (step 0) + IngestLog record + `--force` (spec §8, §9.5) → Task 4. ✓
- Anti-slop wired: `check_slop` tool + `anti-slop.md` in the system prompt + procedure step 7 (spec §10.5) → Tasks 1, 3, 6. ✓
- `study-notes add`/`reindex`, `--category`/`--note`/`--dry-run`/`--force` (spec §11) → Tasks 4, 5, 6. ✓
- Written-paths recovered from `notes.source`, not model text → Task 4 (`paths_for_source`). ✓
- Live `claude -p` behavior is validated manually (e2e), not unit-tested — stated in Global Constraints.

**Placeholder scan:** No TBD/TODO; each step has concrete code/commands.

**Type consistency:** `build_command`/`parse_result`/`run`/`mcp_config_dict`/`TOOL_NAMES`/`WRITE_TOOL`
consistent between Task 2 and Task 6. `resolve_source -> (id, type, origin)`, `AddResult`, and
`add(...)` injected-callable signature consistent between Task 4 and Task 6. `paths_for_source`
defined in Task 4, used in Task 4's `add`. `Config.agent_model` added in Task 6 Step 3 and used in
Task 6 Step 4. `config.prompts["procedure"/"anti_slop"]` keys match the spec §11 config and Task 6.

---

## Post-build validation (manual, like Plans 1/2)
After Task 6, run a real end-to-end: `uv run study-notes add https://youtu.be/<caption-bearing-id> --dry-run`
(needs Claude Code auth + DB up), then without `--dry-run`, and confirm notes land in the vault, are
indexed (`study-notes reindex` is idempotent), and a re-add is skipped by the dedup gate.
