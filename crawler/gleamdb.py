from crawler.base import BaseCrawler
from bs4 import BeautifulSoup
from utils.country_check import detect_country_restriction
from utils.network import random_delay


class GleamDBCrawler(BaseCrawler):
    def __init__(self):
        super().__init__("gleamdb", "https://gleamdb.info/")

    def extract_giveaways(self):
        giveaways = []
        try:
            html = self.get_page("https://gleamdb.info/")
            soup = BeautifulSoup(html, "html.parser")

            rows = soup.select("table tr, .giveaway-row, .competition-row")
            for row in rows:
                link = row.select_one("a[href*='gleam.io']")
                if not link:
                    continue

                url = link.get("href", "")
                title = link.get_text(strip=True)
                if not title or not url:
                    continue

                cells = row.select("td")
                description = ""
                deadline = ""
                country = "worldwide"
                if len(cells) > 1:
                    description = cells[1].get_text(strip=True)[:200] if len(cells) > 1 else ""
                    deadline = cells[-2].get_text(strip=True) if len(cells) > 2 else ""
                    country_text = cells[-1].get_text(strip=True).lower() if len(cells) > 3 else ""
                    if "worldwide" in country_text or "global" in country_text:
                        country = "worldwide"
                    elif "germany" in country_text or "de" in country_text:
                        country = "germany"
                    elif "us" in country_text:
                        country = "us"
                    else:
                        country = detect_country_restriction(row.get_text())

                giveaways.append(self._parse_giveaway_card(title, url, description, deadline, country))
                random_delay(3, 8)

        except Exception as e:
            print(f"GleamDB crawl error: {e}")

        return giveaways
