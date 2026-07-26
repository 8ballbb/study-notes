from datetime import date

import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance

pytestmark = pytest.mark.integration


def _note(path, title, category, content):
    prov = Provenance(origin="src", input_type="markdown",
                      captured_at=date(2026, 7, 26), source_date=None)
    return Note(path=path, title=title, category=category, content=content, provenance=prov)


def _index(db_conn):
    from study_notes.vault_index import VaultIndex

    return VaultIndex(db_conn, FakeEmbedder(dim=1024))


def test_upsert_and_list_categories(db_conn):
    idx = _index(db_conn)
    idx.upsert_category("Distributed Systems", "consensus etc")
    idx.upsert_category("Biology", "cells")
    names = sorted(c.name for c in idx.list_categories())
    assert names == ["Biology", "Distributed Systems"]


def test_find_related_is_category_scoped(db_conn):
    idx = _index(db_conn)
    idx.upsert_category("Distributed Systems")
    idx.upsert_category("Biology")
    idx.upsert_note(_note("ds/raft.md", "Raft", "Distributed Systems",
                          "leader election consensus term log replication"))
    idx.upsert_note(_note("ds/paxos.md", "Paxos", "Distributed Systems",
                          "consensus quorum proposals"))
    idx.upsert_note(_note("bio/mitosis.md", "Mitosis", "Biology",
                          "consensus is also a word about cells dividing"))

    results = idx.find_related("consensus algorithm", category="Distributed Systems", k=5)
    paths = [p for p, _ in results]

    assert "bio/mitosis.md" not in paths          # never crosses categories
    assert all(p.startswith("ds/") for p in paths)
    assert len(paths) >= 1


def test_upsert_note_updates_in_place(db_conn):
    idx = _index(db_conn)
    idx.upsert_category("Distributed Systems")
    idx.upsert_note(_note("ds/raft.md", "Raft", "Distributed Systems", "old body"))
    idx.upsert_note(_note("ds/raft.md", "Raft", "Distributed Systems", "new body text"))
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*), max(content) FROM notes WHERE path = %s;", ("ds/raft.md",))
        count, content = cur.fetchone()
    assert count == 1
    assert content == "new body text"
