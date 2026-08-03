"""Read-only `query` command: retrieve across the vault and answer, grounded + cited."""

import asyncio
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage
from claude_agent_sdk import query as sdk_query

from study_notes.config import Config
from study_notes.vault_index import VaultIndex

MAX_NOTES = 8  # cap notes fed to synthesis (bounds context/token cost)
MAX_NOTE_CHARS = 4000  # per-note truncation


class QueryError(RuntimeError):
    """Query synthesis failed or produced no result."""


def _build_user_prompt(question: str, notes: list[tuple[str, str, str]]) -> str:
    blocks = []
    for i, (path, title, content) in enumerate(notes, 1):
        body = (
            content
            if len(content) <= MAX_NOTE_CHARS
            else content[:MAX_NOTE_CHARS] + "\n…(truncated)"
        )
        blocks.append(f"--- NOTE {i}: {title} (path: {path}) ---\n{body}")
    return (
        f"Question: {question}\n\n"
        "Answer using ONLY the notes below. Cite each claim with its note title as [[title]].\n\n"
        + "\n\n".join(blocks)
    )


async def _synthesize(system_prompt: str, user_prompt: str, model: str) -> str:
    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        allowed_tools=[],  # read-only: synthesis needs no tools (structural guardrail)
        permission_mode="bypassPermissions",
        setting_sources=[],
        strict_mcp_config=True,
    )
    answer = None
    async for message in sdk_query(prompt=user_prompt, options=options):
        if isinstance(message, ResultMessage):
            if message.is_error:
                raise QueryError(f"query synthesis failed: {message.result or message.subtype}")
            result = message.result
            answer = result if isinstance(result, str) else str(result)
    if answer is None:
        raise QueryError("query synthesis produced no result")
    return answer


def answer_question(
    config: Config, index: VaultIndex, question: str, category: str | None = None, k: int = 5
) -> str:
    """Retrieve top notes (across all categories unless `category` is given) and answer."""
    hits = index.find_related(question, category=category, k=k)
    if not hits:
        return "No matching notes found in the vault for that question."
    order = {p: i for i, (p, _) in enumerate(hits)}
    notes = index.get_notes([p for p, _ in hits])
    notes.sort(key=lambda n: order.get(n[0], len(order)))  # preserve retrieval ranking
    notes = notes[:MAX_NOTES]
    system_prompt = Path(config.prompts.get("query", "prompts/query.md")).read_text()
    user_prompt = _build_user_prompt(question, notes)
    model = config.models.get("query", config.models["orchestrator"])
    return asyncio.run(_synthesize(system_prompt, user_prompt, model))
