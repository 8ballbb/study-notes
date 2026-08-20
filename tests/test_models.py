from datetime import date

from study_notes.models import Note, Provenance


def test_note_shape():
    prov = Provenance(
        origin="f.pdf", input_type="pdf", captured_at=date(2026, 7, 26), source_date=None
    )
    n = Note(path="a/b.md", title="T", category="Cat", content="# body", provenance=prov)
    assert n.path == "a/b.md"
