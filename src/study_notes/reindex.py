from datetime import date
from pathlib import Path

from study_notes.config import Config
from study_notes.models import Note, Provenance
from study_notes.vault_index import VaultIndex


def parse_frontmatter(md: str) -> dict:
    if not md.startswith("---"):
        return {}
    end = md.find("\n---", 3)
    if end == -1:
        return {}
    out: dict = {}
    for line in md[3:end].splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip().strip('"')
    return out


def _date(val: str | None):
    try:
        return date.fromisoformat(val) if val else None
    except ValueError:
        return None


def reindex(config: Config, index: VaultIndex) -> int:
    root = config.vault_path / config.notes_root
    count = 0
    for md_path in sorted(root.glob("*/*.md")):
        # skip the per-category MOC file (named <Category>.md inside <Category>/)
        if md_path.stem == md_path.parent.name:
            continue
        text = md_path.read_text()
        fm = parse_frontmatter(text)
        category = fm.get("category") or md_path.parent.name
        rel = str(md_path.relative_to(config.vault_path))
        index.upsert_category(category)
        prov = Provenance(
            origin=fm.get("source", ""), input_type=fm.get("source_type", ""),
            captured_at=_date(fm.get("captured_at")) or date.today(),
            source_date=_date(fm.get("source_date")),
        )
        index.upsert_note(Note(path=rel, title=fm.get("title", md_path.stem),
                               category=category, content=text, provenance=prov))
        count += 1
    return count
