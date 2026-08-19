import re

import psycopg
from pgvector import Vector

from study_notes.embedding import Embedder
from study_notes.models import Category, Note

RRF_K = 60

# {cat} is a static predicate fragment (not user data — the category VALUE stays a
# bound %(cat)s param), so scoped vs. cross-category share one template.
_HYBRID_SQL_TMPL = """
WITH dense AS (
    SELECT path, ROW_NUMBER() OVER (ORDER BY dense_vec <=> %(qvec)s) AS rank
    FROM notes
    WHERE {cat}dense_vec IS NOT NULL
    ORDER BY dense_vec <=> %(qvec)s
    LIMIT %(k)s
),
lexical AS (
    SELECT path,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(fts, plainto_tsquery('english', %(q)s)) DESC
           ) AS rank
    FROM notes
    WHERE {cat}fts @@ plainto_tsquery('english', %(q)s)
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

_HYBRID_SQL = _HYBRID_SQL_TMPL.format(cat="category = %(cat)s AND ")  # category-scoped
_HYBRID_SQL_ALL = _HYBRID_SQL_TMPL.format(cat="")  # across all categories


RELATED_HEADING = "## Related"


_WIKILINK_BULLET = re.compile(r"^- \[\[.*\]\]$")


def strip_related_section(text: str) -> str:
    """Drop the auto-generated `## Related` block (heading and everything after it)
    that `study-notes link` appends to note bodies. Those are navigation wikilinks for
    Obsidian, not retrieval content, so they must not reach the embedding or the `fts`
    column. `reindex` re-reads the file verbatim, so the strip has to sit here at the
    single indexing seam to stay clean for both the linker and reindex.

    Only the *managed* block is stripped: a `## Related` heading whose following non-blank
    lines are all `- [[...]]` bullets (exactly what `apply_related_section` emits). A note
    that legitimately uses a `## Related` heading over prose is left untouched, so real
    content never gets dropped from the stored `content`/embedding."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != RELATED_HEADING:
            continue
        tail = [ln.strip() for ln in lines[i + 1 :] if ln.strip()]
        if tail and all(_WIKILINK_BULLET.match(ln) for ln in tail):
            return "\n".join(lines[:i]).rstrip()
    return text.rstrip()


def _embed_text(note: Note) -> str:
    """Text handed to the embedder: a one-line source frame (Anthropic contextual
    retrieval) prepended to the note so an isolated note keeps its parent-source
    context. The frame is never stored or displayed, and the related-links block is
    stripped so navigation wikilinks don't pollute the signal."""
    frame = f"Part of {note.provenance.origin}. Topic area: {note.category}."
    return f"{frame}\n{note.title}\n{strip_related_section(note.content)}"


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
        vec = self.embedder.embed([_embed_text(note)])[0]
        p = note.provenance
        content = strip_related_section(note.content)  # keep the related block out of fts too
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
                    "path": note.path,
                    "title": note.title,
                    "category": note.category,
                    "content": content,
                    "captured_at": p.captured_at,
                    "source": p.origin,
                    "source_type": p.input_type,
                    "source_date": p.source_date,
                    "vec": Vector(vec),
                },
            )
        self.conn.commit()

    def paths_for_source(self, source: str) -> list[str]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT path FROM notes WHERE source = %s ORDER BY path;", (source,))
            return [r[0] for r in cur.fetchall()]

    def find_related(
        self, query: str, category: str | None = None, k: int = 5
    ) -> list[tuple[str, float]]:
        """Hybrid (dense + FTS, RRF-fused) retrieval. category=None searches all categories."""
        qvec = self.embedder.embed([query])[0]
        params = {"qvec": Vector(qvec), "q": query, "k": k, "rrf": RRF_K}
        if category is None:
            sql = _HYBRID_SQL_ALL
        else:
            sql = _HYBRID_SQL
            params["cat"] = category
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return [(path, float(score)) for path, score in cur.fetchall()]

    def get_notes(self, paths: list[str]) -> list[tuple[str, str, str]]:
        """(path, title, content) for the given note paths; missing paths are omitted."""
        if not paths:
            return []
        with self.conn.cursor() as cur:
            cur.execute("SELECT path, title, content FROM notes WHERE path = ANY(%s);", (paths,))
            return [(p, t, c) for p, t, c in cur.fetchall()]
