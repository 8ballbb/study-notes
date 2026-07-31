import pytest

from study_notes.ingest import SourceIdentityError, webpage_source_id


def test_webpage_source_id_strips_utm_params():
    url = "https://example.com/article?utm_source=x&utm_medium=y"
    assert webpage_source_id(url) == "url:https://example.com/article"


def test_webpage_source_id_drops_fragment():
    url = "https://example.com/article#section-2"
    assert webpage_source_id(url) == "url:https://example.com/article"


def test_webpage_source_id_drops_trailing_slash():
    url = "https://example.com/article/"
    assert webpage_source_id(url) == "url:https://example.com/article"


def test_webpage_source_id_lowercases_host():
    url = "https://EXAMPLE.com/article"
    assert webpage_source_id(url) == "url:https://example.com/article"


def test_webpage_source_id_keeps_meaningful_query_params():
    url = "https://example.com/search?q=rust&page=2"
    assert webpage_source_id(url) == "url:https://example.com/search?q=rust&page=2"


def test_webpage_source_id_strips_all_known_tracking_params():
    url = ("https://example.com/article"
           "?utm_source=x&fbclid=1&gclid=2&mc_eid=3&ref=4&ref_src=5&keep=yes")
    assert webpage_source_id(url) == "url:https://example.com/article?keep=yes"


@pytest.mark.parametrize("url", [
    "ftp://example.com/file.txt",
    "mailto:someone@example.com",
])
def test_webpage_source_id_rejects_non_http_schemes(url):
    with pytest.raises(SourceIdentityError):
        webpage_source_id(url)
