import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration

NOTE = """---
title: Raft
category: Distributed Systems
source: https://youtu.be/abc
source_type: youtube
source_date: 2025-11-14
captured_at: 2026-07-27
supersedes: []
---

## Core ideas
- Leaders per term.
"""


def _cfg(tmp_path):
    from study_notes.config import Config
    return Config(vault_path=tmp_path, notes_root="04 - Resources",
                  attachments_dir="06 - Attachments", frames_subdir="frames",
                  database_url="unused", embedding_model="fake",
                  models={}, prompts={}, dry_run=False)


def test_parse_frontmatter_reads_keys():
    from study_notes.reindex import parse_frontmatter
    fm = parse_frontmatter(NOTE)
    assert fm["title"] == "Raft"
    assert fm["category"] == "Distributed Systems"
    assert fm["source"] == "https://youtu.be/abc"


def test_reindex_upserts_notes_and_skips_moc(db_conn, tmp_path):
    from study_notes.reindex import reindex
    cat = tmp_path / "04 - Resources" / "Distributed Systems"
    cat.mkdir(parents=True)
    (cat / "Raft.md").write_text(NOTE)
    (cat / "Distributed Systems.md").write_text("---\ntype: moc\n---\n# MOC\n")  # skipped

    index = VaultIndex(db_conn, FakeEmbedder())
    count = reindex(_cfg(tmp_path), index)
    assert count == 1  # MOC not indexed
    hits = index.find_related("leaders per term", category="Distributed Systems", k=5)
    assert any("Raft" in p for p, _ in hits)
