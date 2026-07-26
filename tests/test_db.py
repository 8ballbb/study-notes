import pytest

pytestmark = pytest.mark.integration


def test_apply_schema_is_idempotent(db_conn):
    from study_notes.db import apply_schema

    apply_schema(db_conn)  # second application must not error
    with db_conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.notes'), to_regclass('public.categories');")
        notes_tbl, cats_tbl = cur.fetchone()
    assert notes_tbl == "notes"
    assert cats_tbl == "categories"


def test_insert_note_row(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO categories (name, description) VALUES (%s, %s);",
                    ("Distributed Systems", "d"))
        cur.execute(
            "INSERT INTO notes (path, title, category, content, captured_at) "
            "VALUES (%s, %s, %s, %s, %s);",
            ("a/Raft.md", "Raft", "Distributed Systems", "consensus body", "2026-07-26"),
        )
    db_conn.commit()
    with db_conn.cursor() as cur:
        cur.execute("SELECT title FROM notes WHERE path = %s;", ("a/Raft.md",))
        assert cur.fetchone()[0] == "Raft"
