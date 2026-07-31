from dataclasses import dataclass

_MIN_BODY_CHARS = 200


@dataclass
class WebpageResult:
    url: str
    title: str
    text: str
    source_date: str | None


class ThinContentError(Exception):
    """Extraction yielded almost nothing (paywall, login wall, empty page)."""


def extract_readable(html: str, url: str) -> WebpageResult:
    """Pure, browser-free readable-text extraction from already-fetched HTML.

    No network, no Playwright — just trafilatura over the passed-in `html`.
    """
    import trafilatura

    # Gate on the actual article content length, not the with_metadata=True
    # markdown, which prepends a YAML frontmatter block (title/description/date)
    # that can inflate a thin, paywalled body past the threshold.
    content = trafilatura.extract(html, output_format="txt", favor_recall=True)
    if not content or len(content) < _MIN_BODY_CHARS:
        raise ThinContentError(f"{url}: thin content")

    body = trafilatura.extract(
        html, output_format="markdown", with_metadata=True, favor_recall=True
    )
    if not body:
        raise ThinContentError(f"{url}: thin content")

    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata is not None else None
    source_date = metadata.date if metadata is not None else None

    return WebpageResult(url=url, title=title or "", text=body, source_date=source_date)
