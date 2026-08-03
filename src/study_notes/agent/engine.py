import asyncio
import shutil
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ProcessError,
    ResultMessage,
    TextBlock,
    query,
)

from study_notes.agent.agents import build_agents
from study_notes.agent.context import EngineContext
from study_notes.agent.tools import build_tool_server


class EngineError(Exception):
    """The agent run ended in an error result."""


def _frame_work_dir(ctx: EngineContext) -> Path:
    """The scratch dir prepare_video/select_keyframes write into (videos + candidate
    frames). Kept frames are copied out to the frames dir, so this is pure scratch."""
    return ctx.config.vault_path / ctx.config.attachments_dir / ctx.config.frames_subdir / "_work"


def clean_frame_work(ctx: EngineContext) -> None:
    """Remove the frame scratch dir. Idempotent; never raises."""
    shutil.rmtree(_frame_work_dir(ctx), ignore_errors=True)


_SN = "mcp__study-notes__"
_TOOLS = [
    f"{_SN}{n}"
    for n in (
        "fetch_youtube_transcript",
        "fetch_webpage",
        "list_categories",
        "vault_search",
        "prepare_video",
        "select_keyframes",
        "keep_frame",
        "vault_write",
        "check_slop",
    )
]


def build_options(ctx: EngineContext) -> ClaudeAgentOptions:
    server, _ = build_tool_server(ctx)
    return ClaudeAgentOptions(
        model=ctx.config.models["orchestrator"],
        system_prompt=Path(ctx.config.prompts["orchestrator"]).read_text(),
        agents=build_agents(ctx.config),
        mcp_servers={"study-notes": server},
        allowed_tools=[*_TOOLS, "WebSearch", "WebFetch", "Read"],
        permission_mode="bypassPermissions",
        cwd=str(ctx.config.vault_path),
        # SDK isolation: do NOT inherit the host's ~/.claude world. Without this the
        # subprocess loads ["user","project"] settings and picks up ambient tooling
        # (the user's hooks, MCP servers, ScheduleWakeup/Task machinery), which both
        # leaks unrelated tools into every ingest and destabilises teardown. Our
        # prompt, agents, in-process MCP server, and core tools are passed directly.
        setting_sources=[],
        strict_mcp_config=True,
    )


def _approval_hook(ctx: EngineContext):
    """PreToolUse gate: show the pending write, block on the user, allow/deny. Hard-enforces
    'agree before writing' and works under bypassPermissions (the SDK-sanctioned way to gate
    a tool under bypass is a PreToolUse hook)."""

    async def hook(input_data: dict, tool_use_id, context):
        ti = input_data.get("tool_input", {})
        label = ti.get("title") or ti.get("path") or "(note)"
        body = ti.get("markdown", "")
        prompt = (
            f"\n=== ABOUT TO WRITE: {label} ===\n"
            f"{body[:1500]}{'…' if len(body) > 1500 else ''}\n"
            "=== approve this write? [y/N] > "
        )
        ask = ctx.ask_fn or input
        try:
            answer = (await asyncio.get_running_loop().run_in_executor(None, ask, prompt)).strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""  # no input / interrupted -> fail closed (deny below)
        if answer.lower() in ("y", "yes"):
            return {
                "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
            }
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"User did not approve this write. Their words: {answer!r}. Revise accordingly, "
                "reconfirm via ask_user, then try again.",
            }
        }

    return hook


def build_interactive_options(
    ctx: EngineContext, *, system_prompt: str, allowed: list[str], approve_tools: list[str]
) -> ClaudeAgentOptions:
    """Like build_options but for an interactive session: `ask_user` is allow-listed and the
    write tool(s) in `approve_tools` are gated behind the human approval hook."""
    server, _ = build_tool_server(ctx)
    return ClaudeAgentOptions(
        model=ctx.config.models["orchestrator"],
        system_prompt=system_prompt,
        agents=build_agents(ctx.config),
        mcp_servers={"study-notes": server},
        allowed_tools=[*allowed, "WebSearch", "WebFetch", "Read"],
        permission_mode="bypassPermissions",
        cwd=str(ctx.config.vault_path),
        setting_sources=[],
        strict_mcp_config=True,
        hooks={
            "PreToolUse": [
                HookMatcher(matcher=t, hooks=[_approval_hook(ctx)], timeout=3600)
                for t in approve_tools
            ]
        },
    )


def _is_spurious_success_teardown(e: ProcessError) -> bool:
    # The SDK sometimes reformats a non-zero CLI-subprocess exit at teardown as a
    # ProcessError even after a terminal success ResultMessage already arrived —
    # the stderr reads `error: Claude Code returned an error result: success`.
    # Match on the literal "error result: success" phrase; the "success" subtype
    # in an error frame is the tell.
    haystack = f"{e} {getattr(e, 'stderr', '') or ''}"
    return "error result: success" in haystack


async def run_ingest(
    ctx: EngineContext, input_prompt: str, options: ClaudeAgentOptions | None = None
) -> str:
    options = options or build_options(ctx)
    final = ""
    error: ResultMessage | None = None
    saw_success = False
    # Consume the FULL stream — do not break on the first ResultMessage. A `result`
    # frame ends one TURN, not the run: when the orchestrator dispatches subagents
    # they run as in-flight tasks and the SDK keeps the stream open, waking the
    # orchestrator for follow-up turns until a final `result` arrives with no tasks
    # in flight (see claude_agent_sdk _internal/query.py, #1088). Breaking on the
    # first result returns a half-finished plan ("I'll wait for the subagents…") and,
    # because background tasks are still live, triggers
    # "aclose(): asynchronous generator is already running". Iterating to natural
    # closure both lets the run complete and avoids the aclose error.
    try:
        try:
            async for message in query(prompt=input_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            final = block.text
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        error = message
                    else:
                        # A successful turn supersedes an earlier turn's error.
                        error = None
                        saw_success = True
                        # In claude-agent-sdk 0.2.128, `ResultMessage.result` is typed
                        # `str | None` (not a dict); guard for a dict defensively too.
                        r = message.result
                        if isinstance(r, dict):
                            final = r.get("result", final) or final
                        elif isinstance(r, str) and r:
                            final = r
        except ProcessError as e:
            # Swallow the spurious teardown ProcessError iff a terminal success
            # ResultMessage already arrived. Anything else propagates unchanged.
            if not (saw_success and _is_spurious_success_teardown(e)):
                raise
    finally:
        # _work holds only scratch (the download + unchosen candidate frames);
        # kept frames were already copied into the frames dir. Clear it so it does
        # not grow across ingests.
        clean_frame_work(ctx)
    if error is not None:
        raise EngineError(f"agent run failed (subtype={error.subtype}): {error.result!r}")
    return final
