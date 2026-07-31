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


def rewrite_for_paywall(url: str, rules) -> str:
    """Route a URL through a reader/mirror when its host matches a paywall rule.

    `rules` is a list of ``{"hosts": [...], "via": "https://mirror/{url}"}`` dicts
    (from ``[paywall]`` config). If `url`'s host equals or is a subdomain of any
    rule host, return the rule's ``via`` template with ``{url}`` replaced by the
    ORIGINAL url; otherwise return `url` unchanged. Fetch through the mirror, but
    keep the original url as the note's source. Mirror domains rotate, so the
    ``via`` base is user-configured, never hardcoded.
    """
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return url
    for rule in rules or ():
        for h in rule.get("hosts", []):
            h = str(h).lower().lstrip(".")
            if h and (host == h or host.endswith("." + h)):
                return str(rule.get("via", "{url}")).replace("{url}", url)
    return url


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


def browser_login(profile_dir: str, url: str | None = None) -> None:
    """Open a headed, persistent Chromium profile so the user can log in by hand.

    Cookies/session state are written to `profile_dir` on close, so a later
    `fetch_webpage` call against the same profile reuses the session.
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    expanded_profile_dir = os.path.expanduser(profile_dir)

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                expanded_profile_dir, headless=False
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                if url:
                    page.goto(url)
                print(
                    "A browser window opened. Log in to the site, then press "
                    "Enter here to save the session…"
                )
                input()
            finally:
                context.close()
    except PlaywrightError as exc:
        raise WebpageFetchError(f"login failed: {exc}") from exc


async def fetch_webpage(
    url: str, *, profile_dir: str, timeout_ms: int, headless: bool = True,
    paywall_rules=(),
) -> WebpageResult:
    """Render `url` in a persistent Chromium profile and extract readable text.

    Uses a persistent context (so a prior manual `study-notes login` can
    reuse cookies/session) rather than a fresh incognito browser. When `url`
    matches a `paywall_rules` entry, the page is fetched through the configured
    reader/mirror, but the returned `WebpageResult.url` stays the ORIGINAL url so
    the note's source/provenance points at the real article, not the mirror.
    """
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    expanded_profile_dir = os.path.expanduser(profile_dir)
    fetch_url = rewrite_for_paywall(url, paywall_rules)

    try:
        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                expanded_profile_dir, headless=headless
            )
            try:
                page = ctx.pages[0] if ctx.pages else await ctx.new_page()
                await page.goto(fetch_url, wait_until="networkidle", timeout=timeout_ms)
                html = await page.content()
                final_url = page.url
            finally:
                await ctx.close()
    except PlaywrightError as exc:
        raise WebpageFetchError(f"{url}: failed to render page: {exc}") from exc

    try:
        return extract_readable(html, url)  # provenance = original url, even via a mirror
    except ThinContentError:
        if _is_login_wall(final_url):
            raise LoginRequiredError(f"log in first: study-notes login {url}") from None
        raise
