import os
import tempfile
from datetime import date
from pathlib import Path

from study_notes.config import Config
from study_notes.models import Note, Topic
from study_notes.renderer import _yaml_scalar, render_note, render_update_section
from study_notes.vault_index import VaultIndex


def _split_frontmatter(md: str) -> tuple[dict, str]:
    """Split a leading YAML frontmatter block off `md`. Returns (fields, body).
    If there is no frontmatter, returns ({}, md). Tolerant, line-based parse."""
    lines = md.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, md
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            fm: dict = {}
            for line in lines[1:i]:
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()
            return fm, "\n".join(lines[i + 1:]).lstrip("\n")
    return {}, md


def _parse_tags(raw: str | None) -> list[str]:
    raw = (raw or "").strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    return [t.strip().strip("'\"") for t in raw.split(",") if t.strip()]


def _derive_description(body: str) -> str:
    """First real sentence of the body — used when the model gave no description."""
    for line in body.splitlines():
        s = line.strip()
        if s and s[0] not in "#!|>-*`":
            return s.split(". ")[0].rstrip(".")[:200]
    return ""


def okf_note_frontmatter(title: str, category: str, provenance,
                         description: str, tags: list[str]) -> str:
    """Canonical OKF-aligned frontmatter for a study note. `type` is the only field
    OKF requires; `resource`/`tags`/`description`/`title` are its recommended fields;
    `category`/`source_type`/`source_date` are project-specific provenance we keep."""
    p = provenance
    rows = ["---", "type: study-note", f"title: {_yaml_scalar(title)}"]
    if description:
        rows.append(f"description: {_yaml_scalar(description)}")
    rows.append(f"resource: {p.origin}" if p.origin else "resource:")
    rows.append(f"tags: [{', '.join(tags)}]")
    rows.append(f"category: {_yaml_scalar(category)}")
    rows.append(f"source_type: {p.input_type}")
    rows.append(f"source_date: {p.source_date.isoformat()}" if p.source_date else "source_date:")
    rows.append(f"timestamp: {p.captured_at.isoformat()}")
    rows.append("---")
    return "\n".join(rows)


class VaultWriteConflict(Exception):
    """A new note would overwrite an existing file."""


class VaultWriteError(Exception):
    """A write did not round-trip correctly (read-back mismatch)."""


def slug(title: str) -> str:
    kept = "".join(c if (c.isalnum() or c in " -_") else "" for c in title)
    return " ".join(kept.split())[:80].strip() or "note"


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class VaultWriter:
    def __init__(self, config: Config, index: VaultIndex) -> None:
        self.config = config
        self.index = index

    def _validate_category(self, category: str) -> None:
        if not category.strip() or "/" in category or "\\" in category or ".." in category:
            raise ValueError(f"invalid category name: {category!r}")

    def _abs_within_vault(self, rel_path: str) -> Path:
        base = self.config.vault_path.resolve()
        candidate = (self.config.vault_path / rel_path).resolve()
        if not candidate.is_relative_to(base):
            raise ValueError(f"path escapes vault: {rel_path!r}")
        return candidate

    def _category_dir(self, category: str) -> Path:
        return self.config.vault_path / self.config.notes_root / category

    def note_path(self, category: str, title: str) -> str:
        return f"{self.config.notes_root}/{category}/{slug(title)}.md"

    def _ensure_category(self, category: str) -> None:
        self._validate_category(category)
        cdir = self._category_dir(category)
        cdir.mkdir(parents=True, exist_ok=True)
        moc = cdir / f"{category}.md"
        if not moc.exists():
            _atomic_write(
                moc,
                f"---\ntype: moc\ncategory: {category}\ndescription: \"\"\n---\n\n"
                f"# {category}\n\n## Notes\n",
            )
        self.index.upsert_category(category)

    def _add_moc_link(self, category: str, note_stem: str) -> None:
        moc = self._category_dir(category) / f"{category}.md"
        text = moc.read_text()
        link = f"- [[{note_stem}]]"
        if link not in text:
            _atomic_write(moc, text.rstrip() + f"\n{link}\n")

    def _upsert(self, path: str, topic: Topic, category: str, body: str) -> None:
        self.index.upsert_note(Note(
            path=path, title=topic.title, category=category,
            content=body, provenance=topic.provenance,
        ))

    def write_new(self, topic: Topic, category: str,
                  frame_paths: dict[int, str] | None = None) -> str:
        self._validate_category(category)
        self._ensure_category(category)
        path = self.note_path(category, topic.title)
        abs_path = self._abs_within_vault(path)
        if abs_path.exists():
            raise VaultWriteConflict(path)
        markdown = render_note(topic, category=category, frame_paths=frame_paths)
        _atomic_write(abs_path, markdown)
        self._add_moc_link(category, abs_path.stem)
        self._upsert(path, topic, category, markdown)
        if abs_path.read_text() != markdown:
            raise VaultWriteError(f"read-back verification failed for {path}")
        return path

    def write_markdown(self, title: str, category: str, markdown: str,
                       provenance) -> str:
        self._validate_category(category)
        self._ensure_category(category)
        path = self.note_path(category, title)
        abs_path = self._abs_within_vault(path)
        if abs_path.exists():
            raise VaultWriteConflict(path)
        # The model's markdown may or may not carry its own frontmatter, and when it
        # does it's inconsistent. Strip any leading block, harvest tags/description
        # from it if present, and prepend a canonical OKF-aligned block built from the
        # provenance we already hold — so every note is OKF-conformant and never ends
        # up with no metadata (the model routinely omits frontmatter entirely).
        model_fm, body = _split_frontmatter(markdown)
        description = model_fm.get("description") or _derive_description(body)
        tags = _parse_tags(model_fm.get("tags"))
        fm = okf_note_frontmatter(title, category, provenance, description, tags)
        final = f"{fm}\n\n{body}\n" if body else f"{fm}\n"
        _atomic_write(abs_path, final)
        self._add_moc_link(category, abs_path.stem)
        self.index.upsert_note(Note(path=path, title=title, category=category,
                                    content=final, provenance=provenance))
        if abs_path.read_text() != final:
            raise VaultWriteError(f"read-back verification failed for {path}")
        return path

    def write_merge(self, target_path: str, topic: Topic, on: date,
                    frame_paths: dict[int, str] | None = None) -> str:
        abs_path = self._abs_within_vault(target_path)
        if not abs_path.exists():
            raise FileNotFoundError(target_path)
        existing = abs_path.read_text()
        section = render_update_section(topic, on=on, frame_paths=frame_paths)
        merged = existing.rstrip() + f"\n\n{section}"
        _atomic_write(abs_path, merged)
        category = Path(target_path).parent.name
        self._upsert(target_path, topic, category, merged)
        if abs_path.read_text() != merged:
            raise VaultWriteError(f"read-back verification failed for {target_path}")
        return target_path
