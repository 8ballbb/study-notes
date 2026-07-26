from datetime import date

from study_notes.models import Card, Topic


def render_card(card: Card, frame_path: str | None = None) -> str:
    multiline = frame_path is not None or "\n" in card.answer
    if not multiline:
        return f"{card.question}::{card.answer}"
    lines = [card.question, "?", card.answer]
    if frame_path is not None:
        lines.append(f"![[{frame_path}]]")
    return "\n".join(lines)


def _yaml_scalar(value: str) -> str:
    """Quote a YAML scalar only when needed, so normal values stay unquoted."""
    needs_quote = (
        value == ""
        or value != value.strip()
        or value[0] in "!&*?|>%@`\"'#[]{},"
        or ": " in value
        or value.endswith(":")
        or "#" in value
        or '"' in value
        or "\n" in value
    )
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _frontmatter(topic: Topic, category: str) -> str:
    p = topic.provenance
    rows = [
        "---",
        f"title: {_yaml_scalar(topic.title)}",
        f"category: {_yaml_scalar(category)}",
        "type: study-note",
        f"tags: [{', '.join(topic.tags)}]",
        f"source: {p.origin}",
        f"source_type: {p.input_type}",
        f"source_date: {p.source_date.isoformat()}" if p.source_date else "source_date:",
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
