from dataclasses import dataclass
from datetime import date


@dataclass
class Provenance:
    origin: str
    input_type: str
    captured_at: date
    source_date: date | None = None


@dataclass
class Category:
    name: str
    description: str = ""


@dataclass
class Note:
    path: str
    title: str
    category: str
    content: str
    provenance: Provenance
