from datetime import date

import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _note(path, title, category, content):
    prov = Provenance(origin="s", input_type="markdown",
                      captured_at=date(2026, 7, 26), source_date=None)
    return Note(path=path, title=title, category=category, content=content, provenance=prov)


def test_vault_search_returns_serializable_scoped_hits(db_conn):
    from study_notes.tools.search import vault_search

    idx = VaultIndex(db_conn, FakeEmbedder())
    idx.upsert_category("DS")
    idx.upsert_category("Bio")
    idx.upsert_note(_note("ds/raft.md", "Raft", "DS", "consensus leader term"))
    idx.upsert_note(_note("bio/cell.md", "Cell", "Bio", "consensus mitosis"))

    hits = vault_search(idx, "consensus", category="DS", k=5)
    assert isinstance(hits, list) and all(set(h) == {"path", "score"} for h in hits)
    assert all(isinstance(h["score"], float) for h in hits)
    assert all(h["path"].startswith("ds/") for h in hits)  # scoped


def test_list_categories_returns_dicts(db_conn):
    from study_notes.tools.search import list_categories

    idx = VaultIndex(db_conn, FakeEmbedder())
    idx.upsert_category("DS", "distributed systems")
    out = list_categories(idx)
    assert {"name": "DS", "description": "distributed systems"} in out
