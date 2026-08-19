"""Auto-linking: give each note a managed `## Related` section of `[[wikilinks]]` to
genuinely related notes across all categories, using the existing BGE-M3 + pgvector
hybrid index. `study-notes link` runs one idempotent, bidirectional pass over the vault.

The section lives in the note BODY (never in a MOC file), so it survives `reindex`
(bodies are re-read verbatim; `_rebuild_moc` would drop links written into MOCs).
`## Related` is a reserved heading; the pass regenerates it wholesale each run.
"""

import logging
from pathlib import Path

from study_notes.config import Config
from study_notes.reindex import parse_frontmatter
from study_notes.tools.vault_write import VaultWriteError, VaultWriter, _split_frontmatter
from study_notes.vault_index import RELATED_HEADING, VaultIndex, strip_related_section

logger = logging.getLogger(__name__)

RELATED_K = 5


def apply_related_section(body: str, stems: list[str]) -> str:
    """Return `body` with its `## Related` block regenerated from `stems`. Idempotent;
    empty `stems` strips the block."""
    base = strip_related_section(body)
    if not stems:
        return base
    links = "\n".join(f"- [[{s}]]" for s in stems)
    section = f"{RELATED_HEADING}\n{links}"
    return f"{base}\n\n{section}" if base else section


def related_stems(
    index: VaultIndex, path: str, title: str, content: str, *, k: int = RELATED_K
) -> list[str]:
    """Cross-category hybrid retrieval to note stems for wikilinks, excluding self.

    Top-k only: RRF scores (`1/(60+rank)`) are not a calibrated similarity, so a score
    threshold would be arbitrary. Add a raw-cosine floor later only if links prove noisy.
    """
    hits = index.find_related(f"{title}\n{content}", category=None, k=k + 1)
    stems: list[str] = []
    for hit_path, _score in hits:
        if hit_path == path:
            continue
        # Dedup by basename: an Obsidian `[[stem]]` resolves by filename, so two related
        # notes sharing a stem across categories are indistinguishable as links anyway —
        # collapsing them to one is correct, not a dropped link.
        stem = Path(hit_path).stem
        if stem not in stems:
            stems.append(stem)
        if len(stems) >= k:
            break
    return stems


def run_link(config: Config, index: VaultIndex) -> tuple[int, int]:
    """Rebuild every note's `## Related` block from the index. Returns
    (notes_linked, total_links) counting only notes changed this run.

    Notes that aren't rewritable OKF notes (no frontmatter, or a title that no longer
    matches the filename) are skipped with a warning, so one hand-authored note dropped
    into a category folder can't abort the whole pass.
    """
    writer = VaultWriter(config, index)
    root = config.vault_path / config.notes_root
    notes_linked = 0
    total_links = 0
    for md_path in sorted(root.glob("*/*.md")):
        if md_path.stem == md_path.parent.name:  # skip the per-category MOC file
            continue
        text = md_path.read_text()
        title = parse_frontmatter(text).get("title", "")
        _, body = _split_frontmatter(text)
        clean = strip_related_section(body)  # query on real content, not prior links
        rel = str(md_path.relative_to(config.vault_path))
        stems = related_stems(index, rel, title, clean)
        new_body = apply_related_section(clean, stems)
        if new_body == body.rstrip():
            continue  # already up to date — skip the rewrite + re-embed
        try:
            writer.rewrite_markdown(rel, new_body)
        except (KeyError, ValueError, VaultWriteError) as e:
            logger.warning("link: skipping %s (not a rewritable OKF note: %s)", rel, e)
            continue
        if stems:
            notes_linked += 1
            total_links += len(stems)
    return notes_linked, total_links
