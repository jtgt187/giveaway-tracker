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


def _fetch_with_playwright(url, timeout=30):
    """Fetch a page using a real headless browser (bypasses Cloudflare).

    Creates a new asyncio event loop when called from a non-main thread
    (e.g. inside ThreadPoolExecutor) to avoid the Windows
    NotImplementedError with subprocess creation.
    """
    from playwright.sync_api import sync_playwright

    # On Windows, threads other than main lack a usable event loop for
    # subprocess creation.  Setting a new SelectorEventLoop fixes this.
    _original_loop = None
    try:
        _original_loop = asyncio.get_event_loop()
    except RuntimeError:
        _original_loop = None

    if sys.platform == "win32":
        # SelectorEventLoop supports subprocesses on worker threads on Windows
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                html = page.content()
            finally:
                browser.close()
        return html
    finally:
        if sys.platform == "win32" and _original_loop is not None:
            asyncio.set_event_loop(_original_loop)


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
        """Fetch a gleam.io URL and check if it is region-blocked or ended.

        Returns:
            "ok"              - page is accessible and active
            "region_blocked"  - page shows region restriction message
            "ended"           - page shows competition ended message
            "error"           - failed to fetch the page
        """
        try:
            html = self.get_page(url)
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
