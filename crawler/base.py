import requests
from bs4 import BeautifulSoup
from utils.network import get_random_headers, random_delay


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

    def _parse_giveaway_card(self, title, url, description="", deadline="", country="worldwide"):
        return {
            "title": title.strip(),
            "url": url.strip(),
            "source": self.name,
            "description": description.strip(),
            "deadline": deadline.strip(),
            "country_restriction": country,
        }
