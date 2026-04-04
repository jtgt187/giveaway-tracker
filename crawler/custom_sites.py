from crawler.base import BaseCrawler
from bs4 import BeautifulSoup
from utils.country_check import detect_country_restriction
from utils.network import random_delay


class CustomSitesCrawler(BaseCrawler):
    def __init__(self):
        super().__init__("custom_sites", "")

    def extract_giveaways(self, sites):
        giveaways = []
        for site_url in sites:
            try:
                self.base_url = site_url
                html = self.get_page(site_url)
                soup = BeautifulSoup(html, "html.parser")

                links = soup.select("a[href*='gleam.io']")
                for link in links:
                    url = link.get("href", "")
                    title = link.get_text(strip=True) or link.get("title", "")
                    if not url or not title:
                        continue
                    if not url.startswith("http"):
                        if url.startswith("/"):
                            from urllib.parse import urlparse
                            parsed = urlparse(site_url)
                            url = f"{parsed.scheme}://{parsed.netloc}{url}"
                        else:
                            url = site_url.rstrip("/") + "/" + url

                    description = ""
                    parent = link.find_parent("div") or link.find_parent("li") or link.find_parent("article")
                    if parent:
                        desc_el = parent.select_one("p, .description, .excerpt, .meta")
                        if desc_el:
                            description = desc_el.get_text(strip=True)[:200]

                    country = detect_country_restriction(html)

                    try:
                        gleam_html = self.get_page(url)
                        gleam_country = detect_country_restriction(gleam_html)
                        if gleam_country != "worldwide":
                            country = gleam_country
                        elif country == "worldwide" and gleam_country == "worldwide":
                            country = "worldwide"
                    except Exception:
                        pass

                    giveaways.append(self._parse_giveaway_card(title, url, description, "", country))
                    random_delay(1, 3)

                random_delay(3, 8)

            except Exception as e:
                print(f"Custom site crawl error for {site_url}: {e}")

        return giveaways
