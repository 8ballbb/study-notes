from datetime import date

import pytest

from study_notes.embedding import FakeEmbedder
from study_notes.models import Note, Provenance
from study_notes.vault_index import VaultIndex

pytestmark = pytest.mark.integration


def _cfg(tmp_path):
    from study_notes.config import Config
    return Config(vault_path=tmp_path, notes_root="04 - Resources",
                  attachments_dir="06 - Attachments", frames_subdir="frames",
                  database_url="unused", embedding_model="fake",
                  models={}, prompts={}, dry_run=False)


def _seed_note(index, source):
    prov = Provenance(origin=source, input_type="youtube",
                      captured_at=date.today(), source_date=None)
    index.upsert_category("Web APIs")
    index.upsert_note(Note(path="04 - Resources/Web APIs/HTTP.md", title="HTTP",
                           category="Web APIs", content="status codes", provenance=prov))


def test_resolve_source_youtube_vs_file(tmp_path):
    from study_notes.orchestrator import resolve_source
    sid, stype, origin = resolve_source("https://youtu.be/772CUg2xYAo")
    assert stype == "youtube" and sid == "youtube:772CUg2xYAo"
    f = tmp_path / "d.txt"; f.write_text("hi")
    sid2, stype2, _ = resolve_source(str(f))
    assert stype2 == "file" and sid2.startswith("sha256:")


def test_add_skips_already_ingested(db_conn, tmp_path):
    from study_notes.ingest import IngestLog
    from study_notes.orchestrator import add

    index = VaultIndex(db_conn, FakeEmbedder())
    log = IngestLog(db_conn)
    url = "https://youtu.be/772CUg2xYAo"
    log.record("youtube:772CUg2xYAo", "youtube", url, ["old/path.md"])

    called = {"ran": False}
    def fake_engine(prompt): called["ran"] = True; return "should not run"

    res = add(url, config=_cfg(tmp_path), index=index, ingest_log=log,
              run_engine=fake_engine)
    assert res.status == "skipped"
    assert res.note_paths == ["old/path.md"]
    assert called["ran"] is False  # dedup gate short-circuits before the engine


def test_add_runs_records_and_returns_paths(db_conn, tmp_path):
    from study_notes.ingest import IngestLog
    from study_notes.orchestrator import add

    index = VaultIndex(db_conn, FakeEmbedder())
    log = IngestLog(db_conn)
    url = "https://youtu.be/772CUg2xYAo"

    def fake_engine(prompt):
        _seed_note(index, url)  # simulate the engine writing a note via vault_write
        return "wrote 1 note"

    res = add(url, config=_cfg(tmp_path), index=index, ingest_log=log,
              run_engine=fake_engine)
    assert res.status == "ingested"
    assert res.note_paths == ["04 - Resources/Web APIs/HTTP.md"]
    assert log.lookup("youtube:772CUg2xYAo").note_paths == res.note_paths  # recorded


def test_add_dry_run_does_not_record(db_conn, tmp_path):
    from study_notes.ingest import IngestLog
    from study_notes.orchestrator import add

    index = VaultIndex(db_conn, FakeEmbedder())
    log = IngestLog(db_conn)
    url = "https://youtu.be/772CUg2xYAo"

    res = add(url, config=_cfg(tmp_path), index=index, ingest_log=log,
              run_engine=lambda prompt: "proposed",
              dry_run=True)
    assert res.status == "dry_run"
    assert log.lookup("youtube:772CUg2xYAo") is None  # nothing recorded on dry run


def test_add_dry_run_returns_model_plan(db_conn, tmp_path):
    from study_notes.ingest import IngestLog
    from study_notes.orchestrator import add

    index = VaultIndex(db_conn, FakeEmbedder())
    log = IngestLog(db_conn)
    res = add("https://youtu.be/772CUg2xYAo", config=_cfg(tmp_path), index=index,
              ingest_log=log, run_engine=lambda prompt: "PROPOSED PLAN: 2 topics",
              dry_run=True)
    assert res.status == "dry_run"
    assert "PROPOSED PLAN" in res.message
