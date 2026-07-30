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

class EngineError(Exception):
    """The agent run ended in an error result."""


_SN = "mcp__study-notes__"
_TOOLS = [f"{_SN}{n}" for n in (
    "fetch_youtube_transcript", "list_categories", "vault_search",
    "prepare_video", "select_keyframes", "keep_frame", "vault_write", "check_slop",
)]


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


async def run_ingest(ctx: EngineContext, input_prompt: str) -> str:
    options = build_options(ctx)
    final = ""
    error: ResultMessage | None = None
    # Consume the FULL stream — do not break on the first ResultMessage. A `result`
    # frame ends one TURN, not the run: when the orchestrator dispatches subagents
    # they run as in-flight tasks and the SDK keeps the stream open, waking the
    # orchestrator for follow-up turns until a final `result` arrives with no tasks
    # in flight (see claude_agent_sdk _internal/query.py, #1088). Breaking on the
    # first result returns a half-finished plan ("I'll wait for the subagents…") and,
    # because background tasks are still live, triggers
    # "aclose(): asynchronous generator is already running". Iterating to natural
    # closure both lets the run complete and avoids the aclose error.
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
                # In claude-agent-sdk 0.2.128, `ResultMessage.result` is typed
                # `str | None` (not a dict); guard for a dict defensively too.
                r = message.result
                if isinstance(r, dict):
                    final = r.get("result", final) or final
                elif isinstance(r, str) and r:
                    final = r
    if error is not None:
        raise EngineError(
            f"agent run failed (subtype={error.subtype}): {error.result!r}")
    return final
