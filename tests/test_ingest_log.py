import pytest

from study_notes.ingest import IngestLog, IngestRecord

pytestmark = pytest.mark.integration


def test_lookup_miss_returns_none(db_conn):
    log = IngestLog(db_conn)
    assert log.lookup("youtube:missing0000") is None


def test_record_then_lookup_roundtrips(db_conn):
    log = IngestLog(db_conn)
    log.record("youtube:772CUg2xYAo", "youtube", "https://youtu.be/772CUg2xYAo",
               ["04 - Resources/Web APIs/HTTP Status Codes.md"])
    rec = log.lookup("youtube:772CUg2xYAo")
    assert rec == IngestRecord(
        source_id="youtube:772CUg2xYAo", source_type="youtube",
        origin="https://youtu.be/772CUg2xYAo",
        note_paths=["04 - Resources/Web APIs/HTTP Status Codes.md"],
    )


def test_record_is_idempotent_upsert(db_conn):
    log = IngestLog(db_conn)
    log.record("sha256:abc", "file", "/tmp/a.pdf", ["p/one.md"])
    log.record("sha256:abc", "file", "/tmp/a.pdf", ["p/one.md", "p/two.md"])  # re-ingest
    rec = log.lookup("sha256:abc")
    assert rec.note_paths == ["p/one.md", "p/two.md"]
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM sources WHERE source_id = %s;", ("sha256:abc",))
        assert cur.fetchone()[0] == 1
