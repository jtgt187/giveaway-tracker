import requests
from bs4 import BeautifulSoup
from utils.network import get_random_headers, random_delay
from utils.country_check import is_region_blocked, is_ended


class BaseCrawler:
    def __init__(self, name, base_url):
        self.name = name
        self.base_url = base_url

    def get_page(self, url):
        headers = get_random_headers(referer=self.base_url)
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.text

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
