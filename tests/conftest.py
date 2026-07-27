import os

import pytest


TEST_DB_URL = os.environ.get(
    "STUDY_NOTES_TEST_DB",
    "postgresql://postgres:postgres@localhost:5432/study_notes_test",
)


@pytest.fixture
def db_conn():
    """A clean schema-applied connection; rows are torn down after each test."""
    from study_notes.db import apply_schema, connect

    conn = connect(TEST_DB_URL)
    apply_schema(conn)
    with conn.cursor() as cur:
        cur.execute("TRUNCATE notes, categories, sources CASCADE;")
    conn.commit()
    yield conn
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE notes, categories, sources CASCADE;")
    conn.commit()
    conn.close()
