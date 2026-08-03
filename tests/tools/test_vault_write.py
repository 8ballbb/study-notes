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
        vault_path=vault,
        notes_root="Notes",
        attachments_dir="Attachments",
        frames_subdir="frames",
        database_url="unused",
        embedding_model="fake",
        models={},
        prompts={},
        dry_run=False,
    )


def _topic(title="Raft"):
    prov = Provenance(
        origin="u",
        input_type="youtube",
        captured_at=date(2026, 7, 26),
        source_date=date(2025, 11, 14),
    )
    return Topic(
        title=title,
        tags=["consensus"],
        summary=["Leaders per term."],
        cards=[Card("Q?", "A.")],
        provenance=prov,
    )


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


def _prov():
    return Provenance(
        origin="https://youtube.com/watch?v=abc",
        input_type="youtube",
        captured_at=date(2026, 7, 26),
        source_date=date(2025, 11, 14),
    )


def test_write_markdown_adds_okf_frontmatter_when_model_omits_it(tmp_path, db_conn):
    # The model routinely returns a bare body with no frontmatter — the note must
    # still come out OKF-conformant with metadata filled from provenance.
    w = _writer(tmp_path, db_conn)
    body = "# Raft Consensus\n\nRaft elects one leader per term to keep a replicated log."
    path = w.write_markdown("Raft Consensus", "Distributed Systems", body, _prov())
    text = (tmp_path / path).read_text()
    assert text.startswith("---\n")
    assert "type: study-note" in text  # OKF required field
    assert "resource: https://youtube.com/watch?v=abc" in text  # OKF resource URI
    assert "timestamp: 2026-07-26" in text  # OKF timestamp
    assert "source_type: youtube" in text
    assert "description: Raft elects one leader per term" in text  # derived from body
    assert "# Raft Consensus" in text  # body preserved
    assert text.count("type: study-note") == 1  # exactly one canonical block
    assert text.count("---") == 2  # opened + closed once


def test_write_markdown_harvests_and_normalizes_model_frontmatter(tmp_path, db_conn):
    # If the model DID include its own frontmatter, harvest tags/description from it
    # and emit exactly one canonical OKF block (no duplicate/stale fields).
    w = _writer(tmp_path, db_conn)
    md = (
        "---\ndescription: How layers connect\ntags: [neural-nets, sigmoid]\n"
        "source: junk\n---\n\n# One Layer\n\nWeighted sums feed the next layer."
    )
    path = w.write_markdown("One Layer", "Machine Learning", md, _prov())
    text = (tmp_path / path).read_text()
    assert "tags: [neural-nets, sigmoid]" in text
    assert "description: How layers connect" in text
    assert "resource: https://youtube.com/watch?v=abc" in text
    assert "source: junk" not in text  # stale model field dropped
    assert text.count("---") == 2  # one frontmatter block, opened+closed


def test_rewrite_markdown_preserves_frontmatter_and_replaces_body(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    md = (
        "---\ndescription: How layers connect\ntags: [neural-nets, sigmoid]\n---\n\n"
        "# One Layer\n\nOriginal body."
    )
    path = w.write_markdown("One Layer", "Machine Learning", md, _prov())

    assert w.rewrite_markdown(path, "# One Layer\n\nRewritten, clearer body.") == path
    text = (tmp_path / path).read_text()

    assert "Rewritten, clearer body." in text and "Original body." not in text  # body swapped
    # Every frontmatter field the red-team flagged as loss-prone survives:
    assert "title: One Layer" in text
    assert "category: Machine Learning" in text
    assert "description: How layers connect" in text
    assert "tags: [neural-nets, sigmoid]" in text
    assert "resource: https://youtube.com/watch?v=abc" in text
    assert "source_type: youtube" in text
    assert "source_date: 2025-11-14" in text
    assert "timestamp: 2026-07-26" in text  # capture date NOT reset to today
    assert text.count("type: study-note") == 1
    # index updated with the rewritten content
    hits = w.index.find_related("rewritten clearer", category="Machine Learning", k=5)
    assert any(Path(p).stem == Path(path).stem for p, _ in hits)


def test_rewrite_markdown_missing_note_raises(tmp_path, db_conn):
    w = _writer(tmp_path, db_conn)
    with pytest.raises(FileNotFoundError):
        w.rewrite_markdown("Notes/Machine Learning/Nope.md", "# X\n\nbody")


def test_rewrite_markdown_rejects_title_rename(tmp_path, db_conn):
    from study_notes.tools.vault_write import VaultWriteError

    w = _writer(tmp_path, db_conn)
    path = w.write_markdown("One Layer", "Machine Learning", "# One Layer\n\nBody.", _prov())
    f = tmp_path / path
    f.write_text(f.read_text().replace("title: One Layer", "title: A Different Title"))
    with pytest.raises(VaultWriteError):
        w.rewrite_markdown(path, "# whatever\n\nnew body")
