from crawler.base import BaseCrawler
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None
from urllib.parse import urljoin


class BestOfGleamCrawler(BaseCrawler):
    def __init__(self):
        super().__init__("bestofgleam", "https://bestofgleam.com/")

    def extract_giveaways(self):
        giveaways = []
        seen_urls = set()
        try:
            html = self.get_page("https://bestofgleam.com/")
        except Exception as e:
            print(f"BestOfGleam: failed to fetch page: {e}")
            return giveaways

        try:
            if BeautifulSoup:
                soup = BeautifulSoup(html, "html.parser")
                articles = soup.select("article.post")
                for article in articles:
                    title_el = article.select_one("h2.entry-title a")
                    if not title_el:
                        continue
                    title = title_el.get_text(strip=True)

                    gleam_link = article.select_one(".entry-content a[href*='gleam.io']")
                    if not gleam_link:
                        continue
                    url = gleam_link.get("href", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    deadline = ""
                    deadline_el = article.select_one("span.giveawayenddate")
                    if deadline_el:
                        deadline = deadline_el.get_text(strip=True)

                    description = ""
                    desc_els = article.select(".entry-content p")
                    for p in desc_els:
                        text = p.get_text(strip=True)
                        if text and "Giveaway Ends" not in text and len(text) > 20:
                            description = text[:200]
                            break

                    giveaways.append(self._parse_giveaway_card(title, url, description, deadline))
            else:
                # Lightweight fallback when BeautifulSoup is not available
                import re
                gleam_links = re.findall(r'href="([^\"]*gleam.io[^"]*)"', html)
                for url in gleam_links:
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    giveaways.append(self._parse_giveaway_card("BestOfGleam (fallback)", url, "", ""))
        except Exception as e:
            print(f"BestOfGleam crawl error: {e}")

        return giveaways
