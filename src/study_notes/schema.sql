CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS categories (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS notes (
    path        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    category    TEXT NOT NULL REFERENCES categories(name) ON UPDATE CASCADE,
    content     TEXT NOT NULL,
    captured_at DATE NOT NULL,
    source      TEXT,
    source_type TEXT,
    source_date DATE,
    dense_vec   vector(1024),
    fts         tsvector GENERATED ALWAYS AS
                (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,''))) STORED
);

CREATE INDEX IF NOT EXISTS notes_dense_idx ON notes USING hnsw (dense_vec vector_cosine_ops);
CREATE INDEX IF NOT EXISTS notes_fts_idx   ON notes USING gin (fts);
CREATE INDEX IF NOT EXISTS notes_cat_idx   ON notes (category);

CREATE TABLE IF NOT EXISTS sources (
    source_id   TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    origin      TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    note_paths  TEXT[] NOT NULL DEFAULT '{}'
);
