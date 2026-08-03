import hashlib
from pathlib import Path

import pytest

from study_notes.ingest import SourceIdentityError, file_source_id, youtube_source_id

FIXTURE = Path(__file__).parent / "fixtures" / "hash_me.txt"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=772CUg2xYAo",
        "https://youtu.be/772CUg2xYAo",
        "https://www.youtube.com/watch?v=772CUg2xYAo&list=PLxyz&index=2",
        "https://www.youtube.com/shorts/772CUg2xYAo",
        "https://www.youtube.com/embed/772CUg2xYAo",
    ],
)
def test_youtube_source_id_canonicalizes(url):
    assert youtube_source_id(url) == "youtube:772CUg2xYAo"


def test_youtube_source_id_rejects_non_youtube():
    with pytest.raises(SourceIdentityError):
        youtube_source_id("https://example.com/not-a-video")


def test_file_source_id_matches_sha256():
    expected = "sha256:" + hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    assert file_source_id(FIXTURE) == expected
