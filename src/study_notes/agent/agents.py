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
