"""Feature 2: the full `run_link` pass over a real vault + Postgres (FakeEmbedder,
sandboxed tmp vault). Marked `integration` — runs with the DB up, spends no tokens."""

from datetime import date

import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.linker import run_link
from study_notes.models import Provenance
from study_notes.tools.vault_write import VaultWriter
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _cfg(tmp_path):
    from study_notes.config import Config

    return Config(
        vault_path=tmp_path,
        notes_root="Notes",
        attachments_dir="Attachments",
        frames_subdir="frames",
        database_url="unused",
        embedding_model="fake",
        models={},
        prompts={},
        dry_run=False,
    )


def _prov():
    return Provenance(
        origin="https://youtu.be/x", input_type="youtube", captured_at=date(2026, 8, 4)
    )


def _seed_two_notes(cfg, index):
    writer = VaultWriter(cfg, index)
    writer.write_markdown(
        "Alpha", "Distributed Systems", "# Alpha\n\nRaft leader election per term.", _prov()
    )
    writer.write_markdown(
        "Beta", "Distributed Systems", "# Beta\n\nPaxos consensus among replicas.", _prov()
    )


def _read(tmp_path, stem):
    return (tmp_path / "Notes" / "Distributed Systems" / f"{stem}.md").read_text()


def test_run_link_adds_bidirectional_related_sections(tmp_path, db_conn):
    cfg = _cfg(tmp_path)
    index = VaultIndex(db_conn, FakeEmbedder())
    _seed_two_notes(cfg, index)

    linked, total = run_link(cfg, index)
    assert (linked, total) == (2, 2)  # each note links to the one other note

    alpha, beta = _read(tmp_path, "Alpha"), _read(tmp_path, "Beta")
    assert "## Related" in alpha and "[[Beta]]" in alpha
    assert "## Related" in beta and "[[Alpha]]" in beta
    # links live in the body, never in the MOC (which reindex would rebuild)
    moc = _read(tmp_path, "Distributed Systems")
    assert "## Related" not in moc


def test_run_link_is_idempotent(tmp_path, db_conn):
    cfg = _cfg(tmp_path)
    index = VaultIndex(db_conn, FakeEmbedder())
    _seed_two_notes(cfg, index)

    linked_first, _ = run_link(cfg, index)
    once = _read(tmp_path, "Alpha")
    linked_second, _ = run_link(cfg, index)
    twice = _read(tmp_path, "Alpha")
    assert linked_first == 2
    assert linked_second == 0  # second pass changes nothing
    assert once == twice
    assert once.count("## Related") == 1  # no duplicated section


def test_run_link_keeps_related_block_out_of_the_index(tmp_path, db_conn):
    # the block is on disk for Obsidian, but must not pollute the embedded/fts content
    cfg = _cfg(tmp_path)
    index = VaultIndex(db_conn, FakeEmbedder())
    _seed_two_notes(cfg, index)
    run_link(cfg, index)

    assert "## Related" in _read(tmp_path, "Alpha")  # present on disk
    rows = index.get_notes(["Notes/Distributed Systems/Alpha.md"])
    assert rows and "## Related" not in rows[0][2]  # absent from the indexed content


def test_run_link_skips_unrewritable_notes(tmp_path, db_conn):
    # a hand-authored note with no OKF frontmatter must not abort the whole pass
    cfg = _cfg(tmp_path)
    index = VaultIndex(db_conn, FakeEmbedder())
    _seed_two_notes(cfg, index)
    bad = tmp_path / "Notes" / "Distributed Systems" / "handwritten.md"
    original = "# Handwritten\n\nNo frontmatter here.\n"
    bad.write_text(original)

    linked, _ = run_link(cfg, index)  # must not raise
    assert linked == 2  # the two well-formed notes still get linked
    assert bad.read_text() == original  # the malformed note is left untouched
