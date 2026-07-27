# Notes Orchestrator–Workers Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single `claude -p` run with an in-process **orchestrator–workers** engine on the Claude Agent SDK: an opus lead agent decomposes + judges + integrates while cheap `AgentDefinition` subagents (extractor, enricher) do scoped per-topic work — extraction guided by a note-writing guide, enrichment via web search — with our existing tool functions exposed as in-process SDK tools.

**Architecture:** A `create_sdk_mcp_server` wraps the Plan-2 tool functions (fetch, search, frame, write, list-categories, slop-check) as in-process `@tool`s — no subprocess, so the yt-dlp/stdio and headless-permission problems can't recur. `ClaudeAgentOptions` sets `model=opus` for the lead, an orchestrator system prompt, and `agents={extractor, enricher}` with their own (cheaper) models. The lead delegates per topic; subagents run in isolated contexts. Python keeps the deterministic edges (dedup gate, record-from-`notes.source`, CLI) and drives the async `query()`.

**Tech Stack:** Python 3.12+ (async), `claude-agent-sdk`, plus merged Plans 1/2/2.5. Built-in `WebSearch`/`WebFetch` tools for enrichment.

## Global Constraints

- Python 3.12+; the engine is **async** (`asyncio`); the CLI bridges sync→async with `asyncio.run`.
- SDK imports: `from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition, tool, create_sdk_mcp_server, AssistantMessage, ResultMessage, TextBlock`.
- `@tool(name, description, input_schema)` wraps an `async def f(args: dict) -> dict` returning `{"content": [{"type": "text", "text": <str>}]}`. In-process tools are named `mcp__<server>__<tool>`.
- `AgentDefinition(description, prompt, tools=None, model=None, ...)` — note **camelCase** extras (`disallowedTools`, `permissionMode`). `ClaudeAgentOptions(agents=..., allowed_tools=..., mcp_servers=..., model=..., system_prompt=..., permission_mode=...)`.
- **Reuse, do not reimplement:** `study_notes.tools.{youtube,frames,search,vault_write}`, `VaultIndex`, `IngestLog`, `slop_check`, and the existing `orchestrator.add` dedup-gate/record edges + `cli`. The tool *functions* are wrapped, not rewritten.
- Written note paths are still recovered from `notes.source` (never model text); the orchestrator prompt instructs the lead to pass the exact `source` to `vault_write`.
- No format enum / no per-note format metadata. A single `prompts/note-writing.md` guide drives structure; soft consistency = show one neighbor note.
- `permission_mode="bypassPermissions"` in-process (no interactive prompts; toolset is scoped by `allowed_tools`).
- No LLM API keys in code (SDK rides Claude Code auth). TDD; commit after green. DRY, YAGNI.
- The old `claude_runner.py` + `prompts/procedure.md` are removed once the engine replaces them (Task 7).

---

### Task 1: Add the SDK + a context object for tools

**Files:**
- Modify: `pyproject.toml` (add `claude-agent-sdk`)
- Create: `src/study_notes/agent/__init__.py`
- Create: `src/study_notes/agent/context.py`
- Create: `tests/agent/__init__.py`
- Create: `tests/agent/test_context.py`

**Interfaces:**
- Produces: `@dataclass EngineContext{ config: Config, index: VaultIndex, writer: VaultWriter }` — the shared handles the in-process tools close over.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml` `dependencies`, add:
```toml
    "claude-agent-sdk>=0.1.0",
```
Run: `uv pip install -e ".[dev]"` and confirm import: `uv run python -c "import claude_agent_sdk; print('ok')"` → `ok`.

- [ ] **Step 2: Write the failing test**

`tests/agent/__init__.py`:
```python
```
`tests/agent/test_context.py`:
```python
from study_notes.agent.context import EngineContext


def test_engine_context_holds_handles():
    ctx = EngineContext(config="C", index="I", writer="W")
    assert ctx.config == "C" and ctx.index == "I" and ctx.writer == "W"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.agent'`.

- [ ] **Step 4: Write minimal implementation**

`src/study_notes/agent/__init__.py`:
```python
```
`src/study_notes/agent/context.py`:
```python
from dataclasses import dataclass

from study_notes.config import Config
from study_notes.tools.vault_write import VaultWriter
from study_notes.vault_index import VaultIndex


@dataclass
class EngineContext:
    config: Config
    index: VaultIndex
    writer: VaultWriter
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_context.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/study_notes/agent/__init__.py src/study_notes/agent/context.py tests/agent/__init__.py tests/agent/test_context.py
git commit -m "feat: add claude-agent-sdk dep + EngineContext"
```

---

### Task 2: In-process tool server (wrap the Plan-2 tool functions)

**Files:**
- Create: `src/study_notes/agent/tools.py`
- Create: `tests/agent/test_tools.py`

**Interfaces:**
- Consumes: `EngineContext` (Task 1); the tool functions `youtube.fetch_youtube_transcript`, `search.vault_search`/`list_categories`, `frames.download_video`/`extract_frame`/`frame_filename`, `VaultWriter`, `slop_check`.
- Produces: `build_tool_server(ctx: EngineContext)` → `(server_config, tool_functions)` where `server_config` is the `create_sdk_mcp_server(...)` result (name `"study-notes"`) and `tool_functions` is a dict of the raw async callables (for unit testing). Tools: `fetch_youtube_transcript`, `list_categories`, `vault_search`, `extract_frame`, `vault_write`, `check_slop`.

- [ ] **Step 1: Write the failing test**

`tests/agent/test_tools.py`:
```python
import json
from datetime import date

import pytest

from study_notes.agent.context import EngineContext
from study_notes.config import Config
from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance
from study_notes.tools.vault_write import VaultWriter
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _ctx(tmp_path, db_conn):
    cfg = Config(vault_path=tmp_path, notes_root="04 - Resources",
                 attachments_dir="06 - Attachments", frames_subdir="frames",
                 database_url="unused", embedding_model="fake",
                 models={}, prompts={}, dry_run=False)
    index = VaultIndex(db_conn, FakeEmbedder())
    return EngineContext(config=cfg, index=index, writer=VaultWriter(cfg, index))


def _text(result: dict) -> str:
    return result["content"][0]["text"]


async def _call(tools, name, args):
    return await tools[name](args)


@pytest.mark.asyncio
async def test_list_categories_and_search_tools(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    ctx = _ctx(tmp_path, db_conn)
    ctx.index.upsert_category("Web APIs", "http")
    prov = Provenance(origin="u", input_type="youtube", captured_at=date.today(), source_date=None)
    ctx.index.upsert_note(Note(path="04 - Resources/Web APIs/HTTP.md", title="HTTP",
                               category="Web APIs", content="status codes", provenance=prov))
    _, tools = build_tool_server(ctx)

    cats = json.loads(_text(await _call(tools, "list_categories", {})))
    assert any(c["name"] == "Web APIs" for c in cats)

    hits = json.loads(_text(await _call(tools, "vault_search",
                                        {"query": "status codes", "category": "Web APIs"})))
    assert any("HTTP" in h["path"] for h in hits)


@pytest.mark.asyncio
async def test_check_slop_tool(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    _, tools = build_tool_server(_ctx(tmp_path, db_conn))
    findings = json.loads(_text(await _call(tools, "check_slop",
                                            {"text": "Here's the thing. Studies show it."})))
    assert findings  # detects slop


@pytest.mark.asyncio
async def test_vault_write_tool_writes_note(tmp_path, db_conn):
    from study_notes.agent.tools import build_tool_server

    ctx = _ctx(tmp_path, db_conn)
    _, tools = build_tool_server(ctx)
    out = json.loads(_text(await _call(tools, "vault_write", {
        "title": "Raft", "category": "Distributed Systems",
        "markdown": "---\ntitle: Raft\ncategory: Distributed Systems\n---\n\n## Notes\n- x\n",
        "source": "https://youtu.be/abc", "source_type": "youtube", "source_date": "2025-11-14",
    })))
    assert out["path"].endswith("Raft.md")
    assert (tmp_path / out["path"]).exists()
```

**Note on `vault_write` tool shape:** unlike the old MCP tool (which built a `Topic` from cards), the extractor now produces finished **markdown** directly (per the note-writing guide), so the tool accepts the rendered `markdown` plus metadata, wraps it via `VaultWriter` writing that markdown into the category. Add a `VaultWriter.write_markdown(title, category, markdown, provenance) -> str` helper in Step 3 (a thin sibling of `write_new` that takes pre-rendered markdown and still does folder/MOC creation, clobber-refusal, atomic write, index upsert, read-back).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.agent.tools'`.

- [ ] **Step 3: Add `VaultWriter.write_markdown` then write the tool server**

In `src/study_notes/tools/vault_write.py`, add to `VaultWriter`:
```python
    def write_markdown(self, title: str, category: str, markdown: str,
                       provenance) -> str:
        self._validate_category(category)
        self._ensure_category(category)
        path = self.note_path(category, title)
        abs_path = self._abs_within_vault(path)
        if abs_path.exists():
            raise VaultWriteConflict(path)
        _atomic_write(abs_path, markdown)
        self._add_moc_link(category, abs_path.stem)
        self.index.upsert_note(Note(path=path, title=title, category=category,
                                    content=markdown, provenance=provenance))
        if abs_path.read_text() != markdown:
            raise VaultWriteError(f"read-back verification failed for {path}")
        return path
```

`src/study_notes/agent/tools.py`:
```python
import json
from datetime import date

from claude_agent_sdk import create_sdk_mcp_server, tool

from study_notes.agent.context import EngineContext
from study_notes.models import Provenance
from study_notes.slop_check import slop_check
from study_notes.tools import frames, search, youtube


def _ok(payload) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def build_tool_server(ctx: EngineContext):
    @tool("fetch_youtube_transcript", "Fetch a YouTube transcript with timestamps.",
          {"url": str})
    async def fetch_youtube_transcript(args: dict) -> dict:
        r = youtube.fetch_youtube_transcript(args["url"])
        return _ok({"url": r.url, "video_id": r.video_id, "title": r.title,
                    "upload_date": r.upload_date,
                    "segments": [{"start": s.start, "text": s.text} for s in r.segments]})

    @tool("list_categories", "List existing vault categories.", {})
    async def list_categories(args: dict) -> dict:
        return _ok(search.list_categories(ctx.index))

    @tool("vault_search", "Find related notes within a category.",
          {"query": str, "category": str})
    async def vault_search(args: dict) -> dict:
        return _ok(search.vault_search(ctx.index, args["query"], args["category"]))

    @tool("extract_frame", "Save the video frame at a timestamp into the vault.",
          {"video_url": str, "timestamp": str, "prefix": str})
    async def extract_frame(args: dict) -> dict:
        c = ctx.config
        fdir = c.vault_path / c.attachments_dir / c.frames_subdir
        fdir.mkdir(parents=True, exist_ok=True)
        video = frames.download_video(args["video_url"], fdir)
        out = fdir / frames.frame_filename(args["prefix"], args["timestamp"])
        try:
            frames.extract_frame(video, args["timestamp"], out)
        finally:
            video.unlink(missing_ok=True)
        return _ok({"embed_path": f"{c.attachments_dir}/{c.frames_subdir}/{out.name}"})

    @tool("vault_write", "Write a finished note (markdown) into a category, non-destructively.",
          {"title": str, "category": str, "markdown": str, "source": str,
           "source_type": str, "source_date": str})
    async def vault_write(args: dict) -> dict:
        sd = args.get("source_date") or None
        prov = Provenance(origin=args["source"], input_type=args["source_type"],
                          captured_at=date.today(),
                          source_date=date.fromisoformat(sd) if sd else None)
        path = ctx.writer.write_markdown(args["title"], args["category"],
                                         args["markdown"], prov)
        return _ok({"path": path})

    @tool("check_slop", "Flag AI-slop writing patterns in a draft.", {"text": str})
    async def check_slop(args: dict) -> dict:
        return _ok([{"pattern": f.pattern, "snippet": f.snippet}
                    for f in slop_check(args["text"])])

    fns = {
        "fetch_youtube_transcript": fetch_youtube_transcript, "list_categories": list_categories,
        "vault_search": vault_search, "extract_frame": extract_frame,
        "vault_write": vault_write, "check_slop": check_slop,
    }
    server = create_sdk_mcp_server(name="study-notes", version="1.0.0",
                                   tools=list(fns.values()))
    return server, fns
```

**Note:** the `@tool`-decorated objects are `SdkMcpTool`s; the test calls the underlying async callables. If the decorator returns a wrapper whose callable isn't directly awaitable, expose the raw functions in `fns` *before* decoration (define `async def _fetch(...)`, register `tool(...)(_fetch)` in the server list, and put `_fetch` in `fns`). Adjust in Step 4 if the Step-5 run shows the decorated object isn't callable.

- [ ] **Step 4: Ensure the pytest-asyncio plugin is available**

Add to `pyproject.toml` dev deps: `"pytest-asyncio>=0.23"`, and under `[tool.pytest.ini_options]` add `asyncio_mode = "auto"`. Reinstall: `uv pip install -e ".[dev]"`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_tools.py -v`
Expected: PASS (3 passed). (Requires DB container.) If a decorated tool isn't directly awaitable, apply the Step-3 note's raw-function adjustment and re-run.

- [ ] **Step 6: Commit**

```bash
git add src/study_notes/agent/tools.py src/study_notes/tools/vault_write.py tests/agent/test_tools.py pyproject.toml
git commit -m "feat: in-process SDK tool server wrapping the vault tools"
```

---

### Task 3: The three prompts (orchestrator, note-writing, enrichment)

**Files:**
- Create: `prompts/orchestrator.md`, `prompts/note-writing.md`, `prompts/enrichment.md`
- Create: `tests/test_agent_prompts.py`

**Interfaces:** content artifacts loaded by the engine (Task 5) and subagents (Task 4).

- [ ] **Step 1: Write the failing test**

`tests/test_agent_prompts.py`:
```python
from pathlib import Path


def test_orchestrator_prompt_covers_flow():
    t = Path("prompts/orchestrator.md").read_text().lower()
    for kw in ["decompose", "extractor", "enricher", "list_categories",
               "vault_search", "vault_write", "source", "verify"]:
        assert kw in t, kw


def test_note_writing_guide_is_toolbox_not_qa_default():
    t = Path("prompts/note-writing.md").read_text().lower()
    assert "understand" in t and "concise" in t
    assert "compose" in t or "toolbox" in t  # formats combine, not one-per-note


def test_enrichment_guide_requires_sources():
    t = Path("prompts/enrichment.md").read_text().lower()
    assert "websearch" in t or "web search" in t
    assert "source" in t and ("cite" in t or "url" in t)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent_prompts.py -v`
Expected: FAIL (files missing).

- [ ] **Step 3: Write the prompts**

`prompts/orchestrator.md`:
```markdown
# Study-notes orchestrator

You are the lead. Turn one source into concise, well-written study notes, delegating the
bulky work to your subagents and keeping your own context lean. Do not ask the user anything.

## Inputs
The user message gives the source (a YouTube URL or a file path) and the exact `source`
string to record, plus optional directives: a forced `category`, a forced merge `target_note`,
and whether this is a dry run.

## Procedure
1. **Read + decompose.** For a YouTube URL call `fetch_youtube_transcript`; for a file read it
   directly. Split the material into distinct topics — a title, scope, and the source slice for
   each. Skip non-content (sponsor reads, intros). Do the splitting yourself; it needs judgment.
2. **Resolve placement per topic.** Use the forced `category` if given, else call
   `list_categories` and pick a fitting existing category or a genuinely new one. Then, unless a
   `target_note` was forced, call `vault_search(query, category)` to decide new-note vs merge.
   When merging or when the category exists, fetch one existing note from that category to pass
   the extractor as a style reference.
3. **Delegate, in parallel where possible.** For each topic, invoke the `extractor` subagent
   (give it: the topic's source slice, the note-writing guide is already its system prompt, and
   the neighbor note if any) and the `enricher` subagent (give it the topic's key claims). Issue
   multiple subagent calls together so they run concurrently.
4. **Integrate.** Merge each extractor's note with its enricher's cited additions into one final
   note. Keep enrichment meaningful; keep every external claim's source URL.
5. **Screen.** Call `check_slop` on each final note; revise wording you agree reads as slop.
6. **Write.** Call `vault_write` with the finished `markdown`, passing the EXACT `source` string
   you were given. New notes never overwrite; category folders/MOCs are handled for you.
7. **Verify.** Confirm each note is well-formed, grounded, correctly placed, and complete.

## Dry run
If told this is a dry run, do steps 1–5 and report the proposed topics, categories, placements,
and a sample of the note content. Do NOT call `vault_write`.

## Finish
End with a one-line summary of what you wrote (or proposed).
```

`prompts/note-writing.md`:
```markdown
# Writing a study note

Write the note so it teaches the idea and is retained — understanding first, concise always.
You are given one topic's source material (and maybe a neighbor note to match in shape).

## Compose from this toolbox as the content warrants (combine freely; these are not modes)
- Explain the idea from first principles in a teaching voice.
- Structured breakdown: what it is / why it matters / how it works / common mistake.
- Step-by-step for a process; a comparison table for options/tradeoffs.
- A worked example; a decision guide ("use X when…"); an analogy for an abstract idea.
- Cause→effect for a mechanism; a timeline for evolution; a cheat-sheet for reference facts.
- Rote Q&A cards ONLY when the material is genuinely drill-worthy — not by default.

## Rules
- Lead with the point. Active voice. Concrete specifics over abstractions. Keep it tight.
- If a neighbor note is provided, match its structure and depth for consistency.
- Output a complete Obsidian markdown note with YAML frontmatter (title, category, tags,
  source, source_type, source_date, captured_at). Do not invent facts beyond the source and the
  enrichment you are given.
- Follow the anti-slop guide.
```

`prompts/enrichment.md`:
```markdown
# Enriching a note with research

You are given one topic's key claims. Use WebSearch/WebFetch to make the note better than the
source — do not pad.

## Do
- Verify the key claims; flag any that are outdated or wrong.
- Add authoritative context or a concrete example the source skipped.
- Surface one or two closely related ideas worth a link.

## Rules
- Every external claim MUST carry a source URL. Return a compact list of additions, each with
  its URL, that the orchestrator can merge. If you find nothing solid, return nothing — the note
  is fine from the source alone.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_agent_prompts.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add prompts/orchestrator.md prompts/note-writing.md prompts/enrichment.md tests/test_agent_prompts.py
git commit -m "feat: orchestrator + note-writing + enrichment prompts"
```

---

### Task 4: Subagent definitions

**Files:**
- Create: `src/study_notes/agent/agents.py`
- Create: `tests/agent/test_agents.py`

**Interfaces:**
- Consumes: `Config` (for per-role models + prompt paths), `anti-slop.md`.
- Produces: `build_agents(config: Config) -> dict[str, AgentDefinition]` with keys `"extractor"` and `"enricher"`. The extractor's `prompt` = note-writing guide + anti-slop guide, `model` = `config.models["extractor"]`, `tools` = the write/frame tools it needs. The enricher's `prompt` = enrichment guide, `model` = `config.models["enricher"]`, `tools` = `["WebSearch", "WebFetch"]`.

- [ ] **Step 1: Write the failing test**

`tests/agent/test_agents.py`:
```python
from pathlib import Path

from study_notes.config import Config


def _cfg(tmp_path):
    nw = tmp_path / "nw.md"; nw.write_text("NOTE-WRITING")
    en = tmp_path / "en.md"; en.write_text("ENRICH")
    sl = tmp_path / "slop.md"; sl.write_text("ANTISLOP")
    return Config(vault_path=tmp_path, notes_root="r", attachments_dir="a",
                  frames_subdir="frames", database_url="u", embedding_model="m",
                  models={"extractor": "sonnet", "enricher": "haiku"},
                  prompts={"note_writing": str(nw), "enrichment": str(en), "anti_slop": str(sl)},
                  dry_run=False)


def test_build_agents_sets_models_and_prompts(tmp_path):
    from study_notes.agent.agents import build_agents

    agents = build_agents(_cfg(tmp_path))
    assert set(agents) == {"extractor", "enricher"}
    assert agents["extractor"].model == "sonnet"
    assert "NOTE-WRITING" in agents["extractor"].prompt
    assert "ANTISLOP" in agents["extractor"].prompt
    assert agents["enricher"].model == "haiku"
    assert "ENRICH" in agents["enricher"].prompt
    assert "WebSearch" in agents["enricher"].tools
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_agents.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.agent.agents'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/agent/agents.py`:
```python
from pathlib import Path

from claude_agent_sdk import AgentDefinition

from study_notes.config import Config

_SN = "mcp__study-notes__"


def build_agents(config: Config) -> dict[str, AgentDefinition]:
    note_writing = Path(config.prompts["note_writing"]).read_text()
    enrichment = Path(config.prompts["enrichment"]).read_text()
    anti_slop = Path(config.prompts["anti_slop"]).read_text()

    extractor = AgentDefinition(
        description="Writes one finished study note from a topic's source slice.",
        prompt=f"{note_writing}\n\n{anti_slop}",
        model=config.models["extractor"],
        tools=[f"{_SN}extract_frame", f"{_SN}check_slop"],
    )
    enricher = AgentDefinition(
        description="Researches a topic online and returns cited additions.",
        prompt=enrichment,
        model=config.models["enricher"],
        tools=["WebSearch", "WebFetch"],
    )
    return {"extractor": extractor, "enricher": enricher}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_agents.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/agent/agents.py tests/agent/test_agents.py
git commit -m "feat: extractor + enricher subagent definitions"
```

---

### Task 5: The engine (options + async run)

**Files:**
- Create: `src/study_notes/agent/engine.py`
- Create: `tests/agent/test_engine.py`

**Interfaces:**
- Consumes: `EngineContext`, `build_tool_server`, `build_agents`, `Config`.
- Produces:
  - `build_options(ctx: EngineContext) -> ClaudeAgentOptions` — assembles: `model = ctx.config.models["orchestrator"]`, `system_prompt` = `orchestrator.md`, `agents = build_agents(...)`, `mcp_servers = {"study-notes": <server>}`, `allowed_tools` = the six `mcp__study-notes__*` names + `"WebSearch"` + `"WebFetch"`, `permission_mode = "bypassPermissions"`, `cwd` = vault path.
  - `async run_ingest(ctx, input_prompt: str) -> str` — drives `query(prompt=input_prompt, options=build_options(ctx))`, returns the final result text.

- [ ] **Step 1: Write the failing test (options are unit-testable; the live run is e2e)**

`tests/agent/test_engine.py`:
```python
from pathlib import Path

import pytest

from study_notes.agent.context import EngineContext
from study_notes.config import Config
from study_notes.embedding import FakeEmbedder
from study_notes.tools.vault_write import VaultWriter
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _ctx(tmp_path, db_conn):
    for n in ["orchestrator", "note_writing", "enrichment", "anti_slop"]:
        (tmp_path / f"{n}.md").write_text(n)
    cfg = Config(vault_path=tmp_path, notes_root="04 - Resources",
                 attachments_dir="06 - Attachments", frames_subdir="frames",
                 database_url="unused", embedding_model="fake",
                 models={"orchestrator": "opus", "extractor": "sonnet", "enricher": "haiku"},
                 prompts={"orchestrator": str(tmp_path / "orchestrator.md"),
                          "note_writing": str(tmp_path / "note_writing.md"),
                          "enrichment": str(tmp_path / "enrichment.md"),
                          "anti_slop": str(tmp_path / "anti_slop.md")},
                 dry_run=False)
    index = VaultIndex(db_conn, FakeEmbedder())
    return EngineContext(config=cfg, index=index, writer=VaultWriter(cfg, index))


def test_build_options_wires_models_agents_tools(tmp_path, db_conn):
    from study_notes.agent.engine import build_options

    opts = build_options(_ctx(tmp_path, db_conn))
    assert opts.model == "opus"
    assert set(opts.agents) == {"extractor", "enricher"}
    assert "study-notes" in opts.mcp_servers
    assert "mcp__study-notes__vault_write" in opts.allowed_tools
    assert "WebSearch" in opts.allowed_tools
    assert opts.permission_mode == "bypassPermissions"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/agent/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'study_notes.agent.engine'`.

- [ ] **Step 3: Write minimal implementation**

`src/study_notes/agent/engine.py`:
```python
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from study_notes.agent.agents import build_agents
from study_notes.agent.context import EngineContext
from study_notes.agent.tools import build_tool_server

_SN = "mcp__study-notes__"
_TOOLS = [f"{_SN}{n}" for n in (
    "fetch_youtube_transcript", "list_categories", "vault_search",
    "extract_frame", "vault_write", "check_slop",
)]


def build_options(ctx: EngineContext) -> ClaudeAgentOptions:
    server, _ = build_tool_server(ctx)
    return ClaudeAgentOptions(
        model=ctx.config.models["orchestrator"],
        system_prompt=Path(ctx.config.prompts["orchestrator"]).read_text(),
        agents=build_agents(ctx.config),
        mcp_servers={"study-notes": server},
        allowed_tools=[*_TOOLS, "WebSearch", "WebFetch"],
        permission_mode="bypassPermissions",
        cwd=str(ctx.config.vault_path),
    )


async def run_ingest(ctx: EngineContext, input_prompt: str) -> str:
    options = build_options(ctx)
    final = ""
    async for message in query(prompt=input_prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    final = block.text
        elif isinstance(message, ResultMessage):
            r = message.result
            if isinstance(r, dict):
                final = r.get("result", final) or final
            elif isinstance(r, str):
                final = r
    return final
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/agent/test_engine.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add src/study_notes/agent/engine.py tests/agent/test_engine.py
git commit -m "feat: agent engine (build_options + async run_ingest)"
```

---

### Task 6: Config — per-role models + prompt paths

**Files:**
- Modify: `src/study_notes/config.py`
- Modify: `config.toml`
- Modify: `tests/fixtures/config_ok.toml` and `tests/test_config.py` (extend to the new keys)

**Interfaces:**
- Produces: `Config.models` now carries `orchestrator`/`extractor`/`enricher`; `Config.prompts` carries `orchestrator`/`note_writing`/`enrichment`/`anti_slop`. `load_config` reads `[models]` and `[prompts]` tables as-is (already `dict(data.get("models", {}))` / `dict(data["prompts"])`), so no code change beyond documenting the expected keys — but the `[agent]` single-model reading and `agent_model` field are removed.

- [ ] **Step 1: Update the config fixture + failing test**

In `tests/fixtures/config_ok.toml`, replace the `[models]`/`[prompts]` blocks:
```toml
[models]
orchestrator = "claude-opus-4-8"
extractor = "claude-sonnet-5"
enricher = "claude-sonnet-5"

[prompts]
orchestrator = "prompts/orchestrator.md"
note_writing = "prompts/note-writing.md"
enrichment = "prompts/enrichment.md"
anti_slop = "prompts/anti-slop.md"
```
In `tests/test_config.py::test_load_config_reads_all_fields`, change the assertions to:
```python
    assert cfg.models["orchestrator"] == "claude-opus-4-8"
    assert cfg.prompts["note_writing"] == "prompts/note-writing.md"
```
and remove any `agent_model` assertion.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL on the changed assertions (or on `agent_model` removal) until Step 3.

- [ ] **Step 3: Remove `agent_model`; keep `models`/`prompts` generic**

In `src/study_notes/config.py`: delete the `agent_model: str = "..."` field and the `agent_model=data.get("agent", {}).get(...)` line in `load_config`. `models`/`prompts` stay as free dicts.

- [ ] **Step 4: Write the real `config.toml`**

Replace `config.toml` `[agent]`/`[models]`/`[prompts]` sections with:
```toml
[models]
orchestrator = "claude-opus-4-8"
extractor = "claude-sonnet-5"
enricher = "claude-sonnet-5"

[prompts]
orchestrator = "prompts/orchestrator.md"
note_writing = "prompts/note-writing.md"
enrichment = "prompts/enrichment.md"
anti_slop = "prompts/anti-slop.md"
```

- [ ] **Step 5: Run the config + full offline suite**

Run: `uv run pytest tests/test_config.py -v` → PASS.
Run: `uv run pytest -m "not slow and not network and not ffmpeg and not docker" -q` → PASS (fix any test still referencing `agent_model`).

- [ ] **Step 6: Commit**

```bash
git add src/study_notes/config.py config.toml tests/fixtures/config_ok.toml tests/test_config.py
git commit -m "feat: per-role model + prompt config (orchestrator/extractor/enricher)"
```

---

### Task 7: Wire the engine into `add`; retire the old run

**Files:**
- Modify: `src/study_notes/orchestrator.py`
- Modify: `src/study_notes/cli.py`
- Delete: `src/study_notes/claude_runner.py`, `prompts/procedure.md`, `tests/test_claude_runner.py`, `tests/test_procedure_prompt.py`
- Modify: `tests/test_orchestrator.py` (the injected callable becomes the async engine)

**Interfaces:**
- `orchestrator.add(...)` keeps its shape but its injected `run_claude`/`build_system_prompt` are replaced by a single injected `run_engine(source_prompt: str) -> str` async-or-sync callable (tests stub it sync); the dedup gate + `paths_for_source` record are unchanged.
- `cli.main` builds `EngineContext`, and `run_engine = lambda prompt: asyncio.run(run_ingest(ctx, prompt))`.

- [ ] **Step 1: Update `test_orchestrator.py` to the new seam**

Replace the `run_claude=..., build_system_prompt=...` kwargs in every `add(...)` call with `run_engine=<stub>` (a plain function taking the input prompt string and returning text). Keep the four behavioral assertions (skip-before-engine, records-from-DB, dry-run-no-record, resolve_source) — e.g.:
```python
    called = {"ran": False}
    def fake_engine(prompt): called["ran"] = True; return "ok"
    res = add(url, config=cfg, index=index, ingest_log=log, run_engine=fake_engine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: FAIL (`add()` still expects `run_claude`/`build_system_prompt`).

- [ ] **Step 3: Simplify `orchestrator.add`**

In `src/study_notes/orchestrator.py`, change `add`'s signature to
`add(raw_input, *, config, index, ingest_log, run_engine, category=None, note=None, dry_run=False, force=False)`.
Replace the body's prompt/system-prompt building with a single input-prompt builder (keep `_input_prompt`) and call `output = run_engine(_input_prompt(origin, source_type, category, note, dry_run))`. Keep the dedup gate, the dry-run early return (carrying `output`), and the `paths_for_source` + `record`. Remove the `build_system_prompt` param.

- [ ] **Step 4: Rewire `cli.main`**

In `src/study_notes/cli.py`: remove the `claude_runner` imports and the `run_claude` closure. Add:
```python
import asyncio
from study_notes.agent.context import EngineContext
from study_notes.agent.engine import run_ingest
from study_notes.tools.vault_write import VaultWriter
...
    index = _make_index(config)
    ctx = EngineContext(config=config, index=index, writer=VaultWriter(config, index))
    ingest_log = IngestLog(index.conn)

    def run_engine(prompt: str) -> str:
        return asyncio.run(run_ingest(ctx, prompt))

    from study_notes.claude_runner import ClaudeRunError  # DELETE this import
```
Replace the `add(...)` call to pass `run_engine=run_engine` (drop `run_claude`/`build_system_prompt`), and drop the `ClaudeRunError` try/except (the SDK raises its own exceptions — wrap `add(...)` in a broad `except Exception as e: print(f"error: {e}", file=sys.stderr); return 1`). `build_system_prompt` is deleted.

- [ ] **Step 5: Delete the retired files**

```bash
git rm src/study_notes/claude_runner.py prompts/procedure.md tests/test_claude_runner.py tests/test_procedure_prompt.py
```

- [ ] **Step 6: Run the full offline suite**

Run: `uv run pytest -m "not slow and not network and not ffmpeg and not docker" -q`
Expected: PASS (all green; no references to the deleted modules remain).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: drive add() through the agent engine; retire the single claude -p run"
```

---

### Task 8: End-to-end validation (marked, manual)

**Files:**
- Create: `tests/test_engine_e2e.py`
- Modify: `README-dev.md`

**Interfaces:** an `e2e`-marked test that runs the real engine (needs Claude Code auth, DB, network).

- [ ] **Step 1: Register the `e2e` marker + write the test**

Add `"e2e: runs the real Claude Agent SDK engine (auth + network + DB)"` to pyproject markers.
`tests/test_engine_e2e.py`:
```python
import asyncio

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.integration]


def test_dry_run_ingest_produces_a_plan(tmp_path, db_conn):
    from study_notes.agent.context import EngineContext
    from study_notes.agent.engine import run_ingest
    from study_notes.config import load_config
    from study_notes.embedding import BGEM3Embedder
    from study_notes.tools.vault_write import VaultWriter
    from study_notes.vault_index import VaultIndex
    from pathlib import Path

    cfg = load_config(Path("config.toml"))
    cfg = type(cfg)(**{**cfg.__dict__, "vault_path": tmp_path})  # sandbox the vault
    index = VaultIndex(db_conn, BGEM3Embedder(cfg.embedding_model))
    ctx = EngineContext(config=cfg, index=index, writer=VaultWriter(cfg, index))
    prompt = ("Ingest this youtube source. Source: https://www.youtube.com/watch?v=772CUg2xYAo "
              "Use exactly this string as the note source: "
              "https://www.youtube.com/watch?v=772CUg2xYAo. This is a DRY RUN: do not call "
              "vault_write; report your plan.")
    out = asyncio.run(run_ingest(ctx, prompt))
    assert out and len(out) > 50  # produced a plan
```

- [ ] **Step 2: Run it for real (once)**

Run: `uv run pytest tests/test_engine_e2e.py -m e2e -v` (DB up, `docker compose up -d`; Claude Code authenticated).
Expected: PASS; inspect the printed plan for quality (adaptive format, enrichment with sources), and time it — confirm it's minutes, and that parallel subagents fire.

- [ ] **Step 3: Document usage**

Append to `README-dev.md` the new engine note: `study-notes add <url>` now runs the in-process Agent-SDK orchestrator (no MCP subprocess); `[models]` sets per-role models. Note the MCP server (`mcp_server.py`) is retained only for an interactive "Claude drives the tools" mode.

- [ ] **Step 4: Commit**

```bash
git add tests/test_engine_e2e.py README-dev.md pyproject.toml
git commit -m "test: e2e engine dry-run + usage docs"
```

---

## Self-Review

**Spec coverage:**
- Orchestrator (opus) decompose + judge + integrate, lean context (spec §4) → Tasks 3, 5 (orchestrator prompt + engine). ✓
- Extractor + enricher workers, isolated context, per-role models, parallel (spec §4) → Tasks 4, 5 (AgentDefinitions + SDK subagent delegation). ✓
- Note-writing guide replaces format catalog/metadata; neighbor-note soft consistency (spec §5) → Task 3 + orchestrator step 2/3. ✓
- Web-research enrichment with cited sources (spec §6) → Tasks 3 (enrichment guide), 4 (enricher tools=WebSearch/WebFetch). ✓
- Claude Agent SDK build mechanism; in-process tools (spec §7) → Tasks 1, 2, 5. ✓
- Per-role model config (spec §7) → Task 6. ✓
- Reuse tool functions + deterministic edges; dedup + record-from-notes.source unchanged (spec §3, §8) → Tasks 2, 7. ✓
- MCP server becomes optional (spec §3) → Task 8 doc; `mcp_server.py` left intact, unused by `add`. ✓
- Vault safety unchanged (non-destructive `write_markdown` reuses clobber/atomic/read-back) → Task 2. ✓
- Testing: workers/tools in isolation, options unit-tested, e2e marked (spec §9) → Tasks 2, 4, 5, 8. ✓

**Placeholder scan:** No TBD/TODO. Two explicit "verify at runtime and adjust" notes (Task 2 tool-callable shape; SDK message result field in Task 5) are concrete fallbacks with exact adjustments, tied to the just-fetched SDK reference — not placeholders.

**Type consistency:** `EngineContext{config,index,writer}` consistent across Tasks 1,2,5,7. `build_tool_server(ctx)->(server,fns)`, `build_agents(config)->dict`, `build_options(ctx)->ClaudeAgentOptions`, `run_ingest(ctx,prompt)->str` consistent between definition and callers. Tool name prefix `mcp__study-notes__*` consistent in Tasks 2,4,5. `run_engine(prompt)->str` seam consistent between Task 7's `add` and CLI. `VaultWriter.write_markdown(title,category,markdown,provenance)->str` defined in Task 2, used by the `vault_write` tool.

---

## Post-build validation (manual)
Run `uv run study-notes add https://www.youtube.com/watch?v=772CUg2xYAo --dry-run`, confirm: a plan in minutes, adaptive note structure (not blurb+Q&A), enrichment additions carrying source URLs, parallel subagents; then a real run writes the note; a re-add is dedup-skipped.
