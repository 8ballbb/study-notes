from datetime import date
from pathlib import Path

from study_notes.config import Config
from study_notes.models import Note, Provenance
from study_notes.tools.vault_write import _atomic_write
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
        v = val.strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        out[key.strip()] = v
    return out


def _date(val: str | None):
    try:
        return date.fromisoformat(val) if val else None
    except ValueError:
        return None


def _rebuild_moc(moc_path: Path, category: str, note_stems: list[str]) -> None:
    """Rewrite a category's index note from the notes that actually exist on disk,
    preserving its description. Prunes links to deleted/renamed notes."""
    description = ""
    if moc_path.exists():
        description = parse_frontmatter(moc_path.read_text()).get("description", "")
    lines = [
        "---", "type: moc", f"category: {category}",
        f'description: "{description}"', "---", "", f"# {category}", "", "## Notes",
    ]
    lines += [f"- [[{stem}]]" for stem in sorted(note_stems)]
    _atomic_write(moc_path, "\n".join(lines) + "\n")


def reindex(config: Config, index: VaultIndex) -> int:
    root = config.vault_path / config.notes_root
    count = 0
    moc_notes: dict[str, list[str]] = {}  # category folder name -> note stems
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
        moc_notes.setdefault(md_path.parent.name, []).append(md_path.stem)
        count += 1

    # Rebuild every category's index note from truth (prunes stale links).
    for cat_dir in sorted(p for p in root.glob("*") if p.is_dir()):
        _rebuild_moc(cat_dir / f"{cat_dir.name}.md", cat_dir.name,
                     moc_notes.get(cat_dir.name, []))
    return count
