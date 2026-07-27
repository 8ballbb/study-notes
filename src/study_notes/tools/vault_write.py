from datetime import date
from pathlib import Path

from study_notes.config import Config
from study_notes.models import Note, Topic
from study_notes.renderer import render_note, render_update_section
from study_notes.vault_index import VaultIndex


class VaultWriteConflict(Exception):
    """A new note would overwrite an existing file."""


def slug(title: str) -> str:
    kept = "".join(c if (c.isalnum() or c in " -_") else "" for c in title)
    return " ".join(kept.split())[:80].strip() or "note"


class VaultWriter:
    def __init__(self, config: Config, index: VaultIndex) -> None:
        self.config = config
        self.index = index

    def _category_dir(self, category: str) -> Path:
        return self.config.vault_path / self.config.notes_root / category

    def note_path(self, category: str, title: str) -> str:
        return f"{self.config.notes_root}/{category}/{slug(title)}.md"

    def _ensure_category(self, category: str) -> None:
        cdir = self._category_dir(category)
        cdir.mkdir(parents=True, exist_ok=True)
        moc = cdir / f"{category}.md"
        if not moc.exists():
            moc.write_text(
                f"---\ntype: moc\ncategory: {category}\ndescription: \"\"\n---\n\n"
                f"# {category}\n\n## Notes\n"
            )
        self.index.upsert_category(category)

    def _add_moc_link(self, category: str, note_stem: str) -> None:
        moc = self._category_dir(category) / f"{category}.md"
        text = moc.read_text()
        link = f"- [[{note_stem}]]"
        if link not in text:
            moc.write_text(text.rstrip() + f"\n{link}\n")

    def _upsert(self, path: str, topic: Topic, category: str, body: str) -> None:
        self.index.upsert_note(Note(
            path=path, title=topic.title, category=category,
            content=body, provenance=topic.provenance,
        ))

    def write_new(self, topic: Topic, category: str,
                  frame_paths: dict[int, str] | None = None) -> str:
        self._ensure_category(category)
        path = self.note_path(category, topic.title)
        abs_path = self.config.vault_path / path
        if abs_path.exists():
            raise VaultWriteConflict(path)
        markdown = render_note(topic, category=category, frame_paths=frame_paths)
        abs_path.write_text(markdown)
        self._add_moc_link(category, abs_path.stem)
        self._upsert(path, topic, category, markdown)
        assert abs_path.read_text() == markdown  # read-back verification
        return path

    def write_merge(self, target_path: str, topic: Topic, on: date,
                    frame_paths: dict[int, str] | None = None) -> str:
        abs_path = self.config.vault_path / target_path
        if not abs_path.exists():
            raise FileNotFoundError(target_path)
        existing = abs_path.read_text()
        section = render_update_section(topic, on=on, frame_paths=frame_paths)
        merged = existing.rstrip() + f"\n\n{section}"
        abs_path.write_text(merged)
        category = Path(target_path).parent.name
        self._upsert(target_path, topic, category, merged)
        assert abs_path.read_text() == merged  # read-back verification
        return target_path
