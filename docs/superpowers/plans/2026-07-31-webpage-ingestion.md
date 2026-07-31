# Webpage Ingestion (JS-heavy + paywalled) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use TDD; each task ends green + committed.

**Goal:** add **webpage** as a third input type to `study-notes add` — including JS-heavy and paywalled pages — reusing the existing decompose → extractor/enricher → OKF-write pipeline.

**Architecture:** a non-YouTube `http(s)` URL resolves to `source_type="webpage"` (`source_id=url:<normalized>`); the orchestrator calls a new in-process `fetch_webpage` tool that renders the page with a headless **Playwright** persistent context (logged-in for paywalls) and extracts readable text + metadata with **trafilatura**. A `study-notes login <url>` command does one-time per-site auth. `resolve_source` is hardened to reject unsupported inputs with a clear error instead of a `FileNotFoundError`.

**Tech Stack:** Python 3.12+, Playwright (async render + sync headed login), trafilatura, existing Claude Agent SDK engine.

## Global Constraints
- Reuse patterns: `fetch_youtube_transcript` (`src/study_notes/tools/youtube.py`) is the template for `fetch_webpage` + its `agent/tools.py` wrapper; the `frames`/`whisper` config pattern (`config.py:17-18,35-36`) is the template for `[browser]`.
- Fetch tools are **best-effort**: render/extract failure raises a typed error; the run fails cleanly (no half-written note).
- **Separate render from extraction** so extraction is unit-testable without a browser.
- `source_id = url:<normalized>` (dedupe by URL, not content). Text-only notes (no frames from pages).
- New deps: `playwright`, `trafilatura`; one-time `playwright install chromium`. Playwright/trafilatura run host-side, in-process (parent process, where the in-process MCP tools live).

---

### Task 1 — deps + `[browser]` config
**Files:** `pyproject.toml` (+`playwright>=1.44`, `trafilatura>=1.9`); `src/study_notes/config.py` (field `browser: dict = field(default_factory=dict)`; `browser=dict(data.get("browser", {}))` in `load_config`); `config.toml` + `tests/fixtures/config_ok.toml` (`[browser]` → `profile="~/.study-notes/browser"`, `timeout_ms=30000`, `headless=true`).
- Write test in `tests/test_config.py`: `cfg.browser["profile"]` present, `cfg.browser["timeout_ms"] == 30000`.
- `uv sync`. Do NOT run `playwright install` in tests. Run `tests/test_config.py`.

### Task 2 — source identity + `resolve_source` hardening
**Files:** `src/study_notes/ingest.py`, `src/study_notes/orchestrator.py`, `tests/test_ingest.py` (new) or `tests/test_orchestrator.py`.
- `ingest.py`: `webpage_source_id(url) -> str` — accept only `http`/`https` (else `SourceIdentityError`); normalise via `urllib.parse`: lowercase scheme+host, drop fragment, drop trailing slash, strip tracking params (`utm_*`, `fbclid`, `gclid`, `mc_eid`, `ref`, `ref_src`); return `url:<norm>`. Add `class UnsupportedSourceError(Exception)`.
- `orchestrator.py` `resolve_source`: order → YouTube → **webpage (http/https)** → existing file (`Path(raw).exists()` guard **before** `file_source_id`) → else `raise UnsupportedSourceError("not a YouTube URL, an http(s) URL, or an existing file: …")`.
- Tests: normalisation (utm/fragment/trailing-slash stripped, host lowercased); rejects `ftp://`/`mailto:`; `resolve_source` → `("webpage",…)` for an article URL, `("file",…)` for an existing tmp file, `UnsupportedSourceError` for a non-existent path / garbage.

### Task 3 — pure extraction helper (unit-testable, no browser)
**Files:** create `src/study_notes/tools/webpage.py`; `tests/tools/test_webpage.py`; `tests/fixtures/article.html`.
- Dataclass `WebpageResult{url, title, text, source_date}`; `extract_readable(html, url) -> WebpageResult` using `trafilatura.extract(html, output_format="markdown", with_metadata=True, favor_recall=True)` for body + `trafilatura.extract_metadata(html)` for title/date (`source_date` → `YYYY-MM-DD`). Raise `ThinContentError` if body < ~200 chars.
- Test against `article.html` (realistic article + nav/ads boilerplate): title present, main paragraphs survive, boilerplate stripped; near-empty HTML → `ThinContentError`.

### Task 4 — `fetch_webpage` (Playwright render + login-wall detection)
**Files:** `src/study_notes/tools/webpage.py`; `tests/tools/test_webpage.py` (browser-marked); register `browser` marker.
- `async def fetch_webpage(url, *, profile_dir, timeout_ms, headless=True) -> WebpageResult`: `async_playwright()` → `launch_persistent_context(profile_dir, headless=…)` → `page.goto(url, wait_until="networkidle", timeout=timeout_ms)` → `html = await page.content()` → close → `extract_readable(html, page.url)`. On `ThinContentError` + a login/paywall signal (final URL matches login/subscribe pattern) raise `LoginRequiredError("log in first: study-notes login <url>")`. Wrap Playwright/timeout failures in `WebpageFetchError`.
- `@pytest.mark.browser` test (manual): render a bundled local `file://` fixture → expected title/text.

### Task 5 — `study-notes login` command
**Files:** `src/study_notes/tools/webpage.py` (`browser_login(profile_dir, url|None)` using **sync** Playwright, `headless=False`); `src/study_notes/cli.py` (new `login` subparser, optional `url`; handled in `main()` **before** DB/index setup).
- `browser_login`: headed persistent context at `profile_dir`, `goto(url)` if given, prompt "Log in, then press Enter to save the session…", wait on stdin, close (cookies persist).
- Test: `parse_args(["login","https://x"])` parses; browser flow is manual.

### Task 6 — wire the tool into the agent
**Files:** `src/study_notes/agent/tools.py` (`fetch_webpage` wrapper reading `ctx.config.browser` → `webpage.fetch_webpage(...)` → `{"url","title","text","source_date"}`; add to `fns` + `sdk_tools` schema `{"url": str}`); `src/study_notes/agent/engine.py` (`_TOOLS += "fetch_webpage"`); `prompts/orchestrator.md` step 1 (add "For a webpage (http/https, non-YouTube) call `fetch_webpage`; its text is the source."); `tests/test_agent_prompts.py` (assert `fetch_webpage` in orchestrator prompt).
- Test: `tests/agent/test_tools.py` — wrapper returns `_ok` shape (monkeypatch `webpage.fetch_webpage`).

### Task 7 — onboarding & docs
**Files:** `scripts/doctor.sh` (checks: `import playwright`, `import trafilatura`, Chromium present; note the one-time `study-notes login`); `README.md` (input list, `[browser]` config, `playwright install chromium` + `login` in Setup, add a **webpage** branch to the Mermaid diagram); `CLAUDE.md` (input types + browser dep). Verified by `./scripts/doctor.sh`.

## Verification
1. Token-free unit suite: `uv run pytest -m "not slow and not docker and not e2e and not browser"`.
2. Browser (manual): `uv run playwright install chromium`; `uv run pytest -m browser`.
3. Gated live e2e (ask first — costs tokens): `study-notes login <site>` then `study-notes add "<article-url>" --dry-run --category "…"`; and `study-notes add not-a-real-thing` → clean `UnsupportedSourceError`.

## Non-goals (v1)
Re-ingesting changed pages, crawling multiple pages, image/frame extraction from pages, reusing the real Chrome profile. Login is per-site, manual, one-time.
