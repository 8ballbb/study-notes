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

    body = trafilatura.extract(
        html, output_format="markdown", with_metadata=True, favor_recall=True
    )
    if not body or len(body) < _MIN_BODY_CHARS:
        raise ThinContentError(url)

    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata is not None else None
    source_date = metadata.date if metadata is not None else None

    return WebpageResult(url=url, title=title or "", text=body, source_date=source_date)
