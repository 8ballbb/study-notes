from datetime import date
from pathlib import Path

import pytest

from study_notes.config import Config
from study_notes.embedding import FakeEmbedder
from study_notes.models import Card, Provenance, Topic
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _config(vault: Path) -> Config:
    return Config(
        vault_path=vault, notes_root="Notes",
        attachments_dir="Attachments", frames_subdir="frames",
        database_url="unused", embedding_model="fake",
        models={}, prompts={}, dry_run=False,
    )


def _topic(title="Raft"):
    prov = Provenance(origin="u", input_type="youtube",
                      captured_at=date(2026, 7, 26), source_date=date(2025, 11, 14))
    return Topic(title=title, tags=["consensus"], summary=["Leaders per term."],
                 cards=[Card("Q?", "A.")], provenance=prov)


def _writer(vault, db_conn):
    from study_notes.tools.vault_write import VaultWriter

    return VaultWriter(_config(vault), VaultIndex(db_conn, FakeEmbedder()))


def test_write_new_creates_folder_moc_and_note(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    path = w.write_new(_topic(), category="Distributed Systems")
    note_file = tmp_path / path
    assert note_file.exists()
    assert "title: Raft" in note_file.read_text()
    moc = tmp_path / "Notes/Distributed Systems/Distributed Systems.md"
    assert moc.exists()
    assert f"[[{Path(path).stem}]]" in moc.read_text()  # MOC links the note


def test_write_new_refuses_to_clobber(tmp_path, db_conn):
    from study_notes.tools.vault_write import VaultWriteConflict

    w = _writer(tmp_path, db_conn)
    w.write_new(_topic(), category="Distributed Systems")
    with pytest.raises(VaultWriteConflict):
        w.write_new(_topic(), category="Distributed Systems")


def test_write_merge_appends_dated_update(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    path = w.write_new(_topic(), category="Distributed Systems")
    merged = w.write_merge(path, _topic(), on=date(2026, 7, 27))
    body = (tmp_path / merged).read_text()
    assert "## Update (2026-07-27)" in body
    assert body.count("title: Raft") == 1  # frontmatter not duplicated


def test_write_new_upserts_into_index(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    w.write_new(_topic(), category="Distributed Systems")
    hits = w.index.find_related("leaders per term", category="Distributed Systems", k=5)
    assert any("Raft" in p for p, _ in hits)


def test_write_merge_missing_target_raises(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    with pytest.raises(FileNotFoundError):
        w.write_merge("Notes/DS/Nope.md", _topic(), on=date(2026, 7, 27))


def test_write_new_rejects_category_traversal(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    with pytest.raises(ValueError):
        w.write_new(_topic(), category="../../evil")
    # nothing was written outside the vault
    assert not (tmp_path.parent / "evil").exists()


def test_write_merge_upserts_into_index(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    path = w.write_new(_topic(), category="Distributed Systems")
    w.write_merge(path, _topic(), on=date(2026, 7, 27))
    hits = w.index.find_related("leaders per term", category="Distributed Systems", k=5)
    assert any("Raft" in p for p, _ in hits)
