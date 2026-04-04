from crawler.base import BaseCrawler
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None
from utils.country_check import detect_country_restriction
from utils.network import random_delay
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed


class GleamfinderCrawler(BaseCrawler):
    def __init__(self):
        super().__init__("gleamfinder", "https://gleamfinder.com/")

    def _fetch_detail(self, detail_url, title, description, deadline, country):
        """Fetch a detail page and extract the gleam.io link. Returns a dict or None."""
        try:
            detail_html = self.get_page(detail_url)
            if BeautifulSoup:
                detail_soup = BeautifulSoup(detail_html, "html.parser")
                enter_btn = detail_soup.select_one("a#enterdirectly[href*='gleam.io']")
                if enter_btn:
                    gleam_url = enter_btn.get("href", "")
                    return self._parse_giveaway_card(title, gleam_url, description, deadline, country)
            else:
                import re
                m = re.search(r'href="([^\"]*gleam.io[^\"]*)"', detail_html)
                if m:
                    return self._parse_giveaway_card(title, m.group(1), description, deadline, country)
        except Exception:
            pass
        return None

    def extract_giveaways(self):
        giveaways = []
        seen_urls = set()
        try:
            html = self.get_page("https://gleamfinder.com/")
            if not BeautifulSoup:
                # Lightweight fallback
                import re
                detail_links = re.findall(r'href="(/giveaway/[^"]+)"', html)
                tasks = []
                for dl in detail_links:
                    detail_url = urljoin("https://gleamfinder.com", dl)
                    tasks.append((detail_url, "Gleamfinder (fallback)", "", "", "worldwide"))
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(self._fetch_detail, *t) for t in tasks]
                    for future in as_completed(futures):
                        result = future.result()
                        if result and result["url"] not in seen_urls:
                            seen_urls.add(result["url"])
                            giveaways.append(result)
                return giveaways

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("div[id][data-lang] .card-body")

            # Collect all detail page tasks
            tasks = []
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

                tasks.append((detail_url, title, description, deadline, country))

            # Fetch all detail pages in parallel (max 4 concurrent)
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(self._fetch_detail, *t) for t in tasks]
                for future in as_completed(futures):
                    result = future.result()
                    if result and result["url"] not in seen_urls:
                        seen_urls.add(result["url"])
                        giveaways.append(result)

        except Exception as e:
            print(f"Gleamfinder crawl error: {e}")

        return giveaways
