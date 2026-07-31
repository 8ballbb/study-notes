from dataclasses import dataclass
from pathlib import Path

from study_notes.config import Config
from study_notes.ingest import (
    IngestLog,
    SourceIdentityError,
    UnsupportedSourceError,
    file_source_id,
    webpage_source_id,
    youtube_source_id,
)
from study_notes.vault_index import VaultIndex


@dataclass
class AddResult:
    status: str  # "ingested" | "skipped" | "dry_run" | "failed"
    source_id: str
    note_paths: list[str]
    message: str


def resolve_source(raw: str) -> tuple[str, str, str]:
    try:
        return youtube_source_id(raw), "youtube", raw
    except SourceIdentityError:
        pass
    try:
        return webpage_source_id(raw), "webpage", raw
    except SourceIdentityError:
        pass
    if Path(raw).exists():
        return file_source_id(Path(raw)), "file", str(raw)
    raise UnsupportedSourceError(
        "not a YouTube URL, an http(s) URL, or an existing file: " + raw
    )


def _input_prompt(origin: str, source_type: str, category, note, dry_run) -> str:
    lines = [
        f"Ingest this {source_type} source into the vault following your procedure.",
        f"Source: {origin}",
        f"Use exactly this string as the note `source`: {origin}",
    ]
    if category:
        lines.append(f"Directive: force category = {category!r}.")
    if note:
        lines.append(f"Directive: merge into target_note = {note!r}.")
    if dry_run:
        lines.append("This is a DRY RUN: do not call vault_write; report your plan.")
    return "\n".join(lines)


def add(raw_input: str, *, config: Config, index: VaultIndex, ingest_log: IngestLog,
        run_engine, category=None, note=None,
        dry_run: bool = False, force: bool = False) -> AddResult:
    source_id, source_type, origin = resolve_source(raw_input)

    if not force:
        existing = ingest_log.lookup(source_id)
        if existing is not None:
            return AddResult("skipped", source_id, existing.note_paths,
                             f"already ingested as {existing.note_paths}")

    output = run_engine(_input_prompt(origin, source_type, category, note, dry_run))

    if dry_run:
        return AddResult("dry_run", source_id, [], output or "dry run — nothing written")

    note_paths = index.paths_for_source(origin)
    if not note_paths:
        return AddResult(
            "failed", source_id, [],
            "no note was written — the source may need `study-notes login` first, or the fetch/agent run failed. "
            "Nothing was recorded; re-run to retry.",
        )
    ingest_log.record(source_id, source_type, origin, note_paths)
    return AddResult("ingested", source_id, note_paths,
                     f"ingested {len(note_paths)} note(s)")
