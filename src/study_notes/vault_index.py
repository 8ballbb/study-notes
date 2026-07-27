import psycopg
from pgvector import Vector

from study_notes.embedding import Embedder
from study_notes.models import Category, Note

RRF_K = 60

_HYBRID_SQL = """
WITH dense AS (
    SELECT path, ROW_NUMBER() OVER (ORDER BY dense_vec <=> %(qvec)s) AS rank
    FROM notes
    WHERE category = %(cat)s AND dense_vec IS NOT NULL
    ORDER BY dense_vec <=> %(qvec)s
    LIMIT %(k)s
),
lexical AS (
    SELECT path,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(fts, plainto_tsquery('english', %(q)s)) DESC
           ) AS rank
    FROM notes
    WHERE category = %(cat)s AND fts @@ plainto_tsquery('english', %(q)s)
    ORDER BY ts_rank(fts, plainto_tsquery('english', %(q)s)) DESC
    LIMIT %(k)s
)
SELECT n.path,
       COALESCE(1.0 / (%(rrf)s + d.rank), 0.0)
     + COALESCE(1.0 / (%(rrf)s + l.rank), 0.0) AS score
FROM notes n
LEFT JOIN dense   d ON n.path = d.path
LEFT JOIN lexical l ON n.path = l.path
WHERE (d.path IS NOT NULL OR l.path IS NOT NULL)
ORDER BY score DESC
LIMIT %(k)s;
"""


class VaultIndex:
    def __init__(self, conn: psycopg.Connection, embedder: Embedder) -> None:
        self.conn = conn
        self.embedder = embedder

    def upsert_category(self, name: str, description: str = "") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO categories (name, description) VALUES (%s, %s) "
                "ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description;",
                (name, description),
            )
        self.conn.commit()

    def list_categories(self) -> list[Category]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT name, description FROM categories ORDER BY name;")
            return [Category(name=n, description=d) for n, d in cur.fetchall()]

    def upsert_note(self, note: Note) -> None:
        vec = self.embedder.embed([f"{note.title}\n{note.content}"])[0]
        p = note.provenance
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notes (path, title, category, content, captured_at,
                                   source, source_type, source_date, dense_vec)
                VALUES (%(path)s, %(title)s, %(category)s, %(content)s, %(captured_at)s,
                        %(source)s, %(source_type)s, %(source_date)s, %(vec)s)
                ON CONFLICT (path) DO UPDATE SET
                    title = EXCLUDED.title,
                    category = EXCLUDED.category,
                    content = EXCLUDED.content,
                    captured_at = EXCLUDED.captured_at,
                    source = EXCLUDED.source,
                    source_type = EXCLUDED.source_type,
                    source_date = EXCLUDED.source_date,
                    dense_vec = EXCLUDED.dense_vec;
                """,
                {
                    "path": note.path, "title": note.title, "category": note.category,
                    "content": note.content, "captured_at": p.captured_at,
                    "source": p.origin, "source_type": p.input_type,
                    "source_date": p.source_date, "vec": Vector(vec),
                },
            )
        self.conn.commit()

    def paths_for_source(self, source: str) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT path FROM notes WHERE source = %s ORDER BY path;", (source,))
            return [r[0] for r in cur.fetchall()]

    def find_related(self, query: str, category: str, k: int = 5) -> list[tuple[str, float]]:
        qvec = self.embedder.embed([query])[0]
        with self.conn.cursor() as cur:
            cur.execute(_HYBRID_SQL,
                        {"qvec": Vector(qvec), "q": query, "cat": category, "k": k, "rrf": RRF_K})
            return [(path, float(score)) for path, score in cur.fetchall()]
