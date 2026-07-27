import hashlib
import re
from pathlib import Path

_YT_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/v/)([0-9A-Za-z_-]{11})")


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
