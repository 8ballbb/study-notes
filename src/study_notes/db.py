from importlib.resources import files

import psycopg
from pgvector.psycopg import register_vector


def connect(database_url: str) -> psycopg.Connection:
    conn = psycopg.connect(database_url)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.commit()
    register_vector(conn)
    return conn


def apply_schema(conn: psycopg.Connection) -> None:
    sql = files("study_notes").joinpath("schema.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def connect_and_prepare(database_url: str) -> psycopg.Connection:
    """Connect and ensure the schema exists (idempotent) — the production entry point."""
    conn = connect(database_url)
    apply_schema(conn)
    return conn
