from crawler.base import BaseCrawler
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None
from utils.country_check import detect_country_restriction
from utils.network import random_delay
from urllib.parse import urljoin


class GleamfinderCrawler(BaseCrawler):
    def __init__(self):
        super().__init__("gleamfinder", "https://gleamfinder.com/")

    def extract_giveaways(self):
        giveaways = []
        seen_urls = set()
        try:
            html = self.get_page("https://gleamfinder.com/")
            if BeautifulSoup:
                soup = BeautifulSoup(html, "html.parser")
            else:
                soup = None

            if BeautifulSoup:
                cards = soup.select("div[id][data-lang] .card-body")
                for card in cards:
                    title_el = card.select_one("h2.card-title")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)

                    detail_link = card.select_one("a[href*='/giveaway/']")
                    if not detail_link:
                        continue

                    detail_url = urljoin("https://gleamfinder.com", detail_link.get("href", ""))

                    description = ""
                    desc_el = card.select_one("p.card-text")
                    if desc_el:
                        description = desc_el.get_text(strip=True)[:200]

                    deadline = ""
                    deadline_el = card.select_one("span.giveawayenddate")
                    if deadline_el:
                        deadline = deadline_el.get_text(strip=True)

                    country = "worldwide"
                    country_els = card.select("p.card-text")
                    if len(country_els) > 1:
                        country_text = country_els[1].get_text(strip=True).lower()
                        country = detect_country_restriction(country_text)

                    try:
                        detail_html = self.get_page(detail_url)
                        if BeautifulSoup:
                            detail_soup = BeautifulSoup(detail_html, "html.parser")
                            enter_btn = detail_soup.select_one("a#enterdirectly[href*='gleam.io']")
                            if enter_btn:
                                gleam_url = enter_btn.get("href", "")
                            else:
                                continue
                        else:
                            # Fallback simple regex-based extraction would be ideal here;
                            # for now skip if no BS4 available for detail parsing.
                            continue
                    except Exception:
                        continue

                    if gleam_url in seen_urls:
                        continue
                    seen_urls.add(gleam_url)

                    giveaways.append(self._parse_giveaway_card(title, gleam_url, description, deadline, country))
                    random_delay(1, 2)
            else:
                # Lightweight fallback when BeautifulSoup is not available
                import re
                detail_links = re.findall(r'href="(/giveaway/[^"]+)"', html)
                for dl in detail_links:
                    detail_url = urljoin("https://gleamfinder.com", dl)
                    try:
                        detail_html = self.get_page(detail_url)
                        m = re.search(r'href="([^\"]*gleam.io[^\"]*)"', detail_html)
                        if m:
                            gleam_url = m.group(1)
                        else:
                            continue
                    except Exception:
                        continue
                    if gleam_url in seen_urls:
                        continue
                    seen_urls.add(gleam_url)
                    giveaways.append(self._parse_giveaway_card("Gleamfinder (fallback)", gleam_url, "", "", "worldwide"))
                    random_delay(1, 2)
        except Exception as e:
            print(f"Gleamfinder crawl error: {e}")

        return giveaways
