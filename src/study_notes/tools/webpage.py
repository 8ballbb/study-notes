import os
import re
from dataclasses import dataclass

_MIN_BODY_CHARS = 200

_LOGIN_WALL_PATTERN = re.compile(
    r"\b(login|signin|sign-in|subscribe|account|auth|paywall)\b", re.IGNORECASE
)


def _is_login_wall(url: str) -> bool:
    """True if `url` looks like a login/subscribe/paywall page.

    Matches whole tokens only (word-boundary anchored) so it doesn't
    substring-match inside unrelated words like /author/, /oauth/callback,
    /accounting-tips, or /subscribers-only.
    """
    return bool(_LOGIN_WALL_PATTERN.search(url))


@dataclass
class WebpageResult:
    url: str
    title: str
    text: str
    source_date: str | None


class ThinContentError(Exception):
    """Extraction yielded almost nothing (paywall, login wall, empty page)."""


class LoginRequiredError(Exception):
    """Extraction failed and the final URL looks like a login/subscribe wall."""


class WebpageFetchError(Exception):
    """Playwright failed to render the page (navigation error, timeout, ...)."""


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


async def fetch_webpage(
    url: str, *, profile_dir: str, timeout_ms: int, headless: bool = True
) -> WebpageResult:
    """Render `url` in a persistent Chromium profile and extract readable text.

    Uses a persistent context (so a prior manual `study-notes login` can
    reuse cookies/session) rather than a fresh incognito browser.
    """
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    expanded_profile_dir = os.path.expanduser(profile_dir)

    try:
        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                expanded_profile_dir, headless=headless
            )
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                html = await page.content()
                final_url = page.url
            finally:
                await ctx.close()
    except PlaywrightError as exc:
        raise WebpageFetchError(f"{url}: failed to render page: {exc}") from exc

    try:
        return extract_readable(html, final_url)
    except ThinContentError:
        if _is_login_wall(final_url):
            raise LoginRequiredError(f"log in first: study-notes login {url}") from None
        raise
