from crawler.base import BaseCrawler
from bs4 import BeautifulSoup
from utils.country_check import detect_country_restriction


class GleamOfficialCrawler(BaseCrawler):
    def __init__(self):
        super().__init__("gleam_official", "https://gleam.io/giveaways")

    def extract_giveaways(self):
        giveaways = []
        try:
            html = self.get_page("https://gleam.io/giveaways")
            soup = BeautifulSoup(html, "html.parser")

            links = soup.select("a[href*='gleam.io/competitions/'], a[href*='gleam.io/giveaways/']")
            seen = set()
            for link in links:
                url = link.get("href", "")
                if not url or url in seen:
                    continue
                seen.add(url)

                title = link.get_text(strip=True) or link.get("title", "")
                if not title:
                    parent = link.find_parent("div")
                    if parent:
                        title = parent.get_text(strip=True)[:100]

                giveaways.append(self._parse_giveaway_card(title, url))

        except Exception as e:
            print(f"Gleam official crawl error: {e}")

        return giveaways
