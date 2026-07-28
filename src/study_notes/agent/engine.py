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
            if message.is_error:
                raise EngineError(
                    f"agent run failed (subtype={message.subtype}): {message.result!r}")
            # In claude-agent-sdk 0.2.128, `ResultMessage.result` is typed
            # `str | None` (not a dict), so a plain string check covers the
            # observed shape. We still guard for a dict defensively in case
            # a future SDK version nests the text under a "result" key.
            r = message.result
            if isinstance(r, dict):
                final = r.get("result", final) or final
            elif isinstance(r, str) and r:
                final = r
    return final
