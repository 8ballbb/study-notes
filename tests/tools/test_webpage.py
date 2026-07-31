import tempfile
from pathlib import Path

import pytest

from study_notes.tools.webpage import (
    ThinContentError,
    WebpageResult,
    _is_login_wall,
    extract_readable,
    fetch_webpage,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "article.html"


def test_extract_readable_captures_article_and_strips_boilerplate():
    html = FIXTURE.read_text()
    result = extract_readable(html, "https://example.com/post")

    assert isinstance(result, WebpageResult)
    assert result.url == "https://example.com/post"
    assert "Why Sourdough Starters Fail in Winter" in result.title
    assert result.source_date == "2026-01-14"

    # Main article content survives.
    assert "Wild yeast and the lactic acid bacteria" in result.text
    assert "stiffer starter, fed at something like a 1:1:0.75" in result.text

    # Nav / ad / footer boilerplate is stripped.
    assert "Subscribe to our newsletter" not in result.text
    assert "ProKnead 9000" not in result.text
    assert "FlourCraft artisan flour" not in result.text
    assert "Privacy Policy" not in result.text
    assert "All rights reserved" not in result.text


def test_extract_readable_raises_on_thin_content():
    html = "<html><body><p>Too short.</p></body></html>"
    with pytest.raises(ThinContentError):
        extract_readable(html, "https://example.com/empty")


def test_extract_readable_raises_on_paywalled_page_with_rich_metadata():
    # Realistic paywall: a normal <title> + meta description (so the
    # with_metadata=True markdown frontmatter is populated), but the visible
    # body is just a one-sentence teaser. The frontmatter alone must not be
    # able to push the extracted content past the thin-content threshold.
    html = """
    <html>
    <head>
      <title>Why Sourdough Starters Fail in Winter</title>
      <meta name="description" content="A deep dive into cold-weather
      fermentation problems for home bakers, from a professional bread baker
      with two decades of experience running a commercial bakery.">
    </head>
    <body>
      <main>
        <article>
          <h1>Why Sourdough Starters Fail in Winter</h1>
          <p>Subscribe to read more.</p>
        </article>
      </main>
    </body>
    </html>
    """
    with pytest.raises(ThinContentError):
        extract_readable(html, "https://example.com/paywalled")


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/login",
        "https://x.com/user-login",
        "https://x.com/subscribe",
        "https://x.com/account/settings",
    ],
)
def test_is_login_wall_matches_whole_tokens(url):
    assert _is_login_wall(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/author/jane-doe",
        "https://x.com/oauth/callback",
        "https://x.com/accounting-tips",
        "https://x.com/blog/post",
    ],
)
def test_is_login_wall_ignores_substring_matches_inside_words(url):
    assert _is_login_wall(url) is False


@pytest.mark.browser
@pytest.mark.asyncio
async def test_fetch_webpage_renders_local_fixture_via_playwright():
    file_url = FIXTURE.resolve().as_uri()

    with tempfile.TemporaryDirectory() as profile_dir:
        result = await fetch_webpage(
            file_url, profile_dir=profile_dir, timeout_ms=30_000
        )

    assert isinstance(result, WebpageResult)
    assert "Why Sourdough Starters Fail in Winter" in result.title
    assert "Wild yeast and the lactic acid bacteria" in result.text
