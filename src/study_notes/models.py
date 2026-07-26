from dataclasses import dataclass
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
