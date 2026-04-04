import asyncio
import sys
import requests
from bs4 import BeautifulSoup
from utils.network import get_random_headers, random_delay
from utils.country_check import is_region_blocked, is_ended


def _fetch_with_cloudscraper(url, timeout=30):
    """Fetch a page using cloudscraper (handles simple bot-detection 403s)."""
    try:
        import cloudscraper
    except ImportError:
        return None
    scraper = cloudscraper.create_scraper()
    resp = scraper.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _setup_win32_event_loop():
    """Create a fresh ProactorEventLoop on Windows worker threads.

    Returns (new_loop, original_loop) so the caller can restore state.
    ProactorEventLoop is the only loop type that supports subprocess
    creation on Windows (SelectorEventLoop does NOT).
    """
    original = None
    new_loop = None
    try:
        original = asyncio.get_event_loop()
    except RuntimeError:
        original = None

    if sys.platform == "win32":
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)

    return new_loop, original


def _teardown_win32_event_loop(new_loop, original):
    """Close the temporary loop and restore the original."""
    if sys.platform == "win32":
        if new_loop is not None:
            new_loop.close()
        if original is not None:
            asyncio.set_event_loop(original)


def _fetch_with_playwright(url, timeout=30, wait_until="domcontentloaded"):
    """Fetch a page using a real headless browser (bypasses Cloudflare).

    *wait_until* controls when the page is considered loaded:
      - ``"domcontentloaded"`` — fast, sufficient for static HTML
      - ``"networkidle"``      — waits for all network activity to settle,
        needed for JS-heavy SPAs like gleam.io where content is rendered
        client-side by Angular.
    """
    from playwright.sync_api import sync_playwright

    new_loop, original = _setup_win32_event_loop()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, timeout=timeout * 1000, wait_until=wait_until)
                html = page.content()
            finally:
                browser.close()
        return html
    finally:
        _teardown_win32_event_loop(new_loop, original)


def _fetch_gleam_rendered(url, timeout=30):
    """Fetch a gleam.io page and wait for Angular to finish rendering.

    Gleam.io is an Angular SPA — region-blocking and "ended" messages are
    rendered client-side via ``ng-if`` after an API call.  A plain HTTP
    request (or Playwright with ``domcontentloaded``) will never see them.

    Strategy:
      1. Navigate with ``domcontentloaded`` (fast, doesn't hang on
         persistent connections or Cloudflare challenges).
      2. Wait up to 10 s for Angular to bootstrap (signalled by the
         ``.ng-scope`` class it adds to compiled elements).
      3. If Angular never appears (Cloudflare stuck, etc.) grab whatever
         HTML we have — the caller's keyword checks will just not match
         and the giveaway will be skipped with ``"error"``.
    """
    from playwright.sync_api import sync_playwright

    new_loop, original = _setup_win32_event_loop()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                # Wait for Angular to compile templates — it adds .ng-scope
                # to every element it processes.  This covers both the
                # region-blocked and ended states.
                try:
                    page.wait_for_selector(".ng-scope", timeout=10000)
                except Exception:
                    pass
                # Small extra buffer for Angular to finish evaluating
                # ng-if conditions after the initial compile.
                page.wait_for_timeout(1000)
                html = page.content()
            finally:
                browser.close()
        return html
    finally:
        _teardown_win32_event_loop(new_loop, original)


class BaseCrawler:
    def __init__(self, name, base_url):
        self.name = name
        self.base_url = base_url

    def get_page(self, url):
        headers = get_random_headers(referer=self.base_url)
        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 403:
                # Site is blocking requests — try cloudscraper first (lightweight),
                # then fall back to a full headless browser if needed.
                try:
                    html = _fetch_with_cloudscraper(url)
                    if html:
                        return html
                except Exception:
                    pass
                return _fetch_with_playwright(url)
            raise

    def extract_giveaways(self):
        raise NotImplementedError

    def validate_gleam_url(self, url):
        """Fetch a gleam.io URL with a real browser and check status.

        Gleam.io is an Angular SPA — region-blocking and "ended" states
        are rendered client-side, so we must use Playwright (not plain
        ``requests.get``) to see them.

        Returns:
            "ok"              - page is accessible and active
            "region_blocked"  - page shows region restriction message
            "ended"           - page shows competition ended message
            "error"           - failed to fetch the page
        """
        try:
            html = _fetch_gleam_rendered(url)
            if is_region_blocked(html):
                return "region_blocked"
            if is_ended(html):
                return "ended"
            return "ok"
        except Exception:
            return "error"

    def _parse_giveaway_card(self, title, url, description="", deadline="", country="worldwide"):
        return {
            "title": title.strip(),
            "url": url.strip(),
            "source": self.name,
            "description": description.strip(),
            "deadline": deadline.strip(),
            "country_restriction": country,
        }
