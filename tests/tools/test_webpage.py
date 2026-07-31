from pathlib import Path

import pytest

from study_notes.tools.webpage import (
    ThinContentError,
    WebpageResult,
    extract_readable,
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
