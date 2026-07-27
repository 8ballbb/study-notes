import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

_YT_ID = re.compile(r"(?:[?&]v=|/shorts/|youtu\.be/|/embed/|/v/)([0-9A-Za-z_-]{11})")


class SourceIdentityError(Exception):
    """The source could not be identified (e.g. no YouTube id in the URL)."""


def youtube_source_id(url: str) -> str:
    m = _YT_ID.search(url)
    if not m:
        raise SourceIdentityError(f"no YouTube video id in {url!r}")
    return f"youtube:{m.group(1)}"


def file_source_id(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


@dataclass
class IngestRecord:
    source_id: str
    source_type: str
    origin: str
    note_paths: list[str]


class IngestLog:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def lookup(self, source_id: str) -> IngestRecord | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, source_type, origin, note_paths "
                "FROM sources WHERE source_id = %s;",
                (source_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return IngestRecord(source_id=row[0], source_type=row[1],
                            origin=row[2], note_paths=list(row[3]))

    def record(self, source_id: str, source_type: str, origin: str,
               note_paths: list[str]) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sources (source_id, source_type, origin, note_paths) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "  source_type = EXCLUDED.source_type, origin = EXCLUDED.origin, "
                "  note_paths = EXCLUDED.note_paths, ingested_at = now();",
                (source_id, source_type, origin, note_paths),
            )
        self.conn.commit()
