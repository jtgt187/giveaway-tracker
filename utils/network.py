import random
import time
from fake_useragent import UserAgent

ua = UserAgent()

COMMON_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def get_random_headers(referer=None):
    headers = COMMON_HEADERS.copy()
    headers["User-Agent"] = ua.random
    if referer:
        headers["Referer"] = referer
    return headers


def random_delay(min_sec=3, max_sec=10):
    delay = random.uniform(float(min_sec), float(max_sec))
    time.sleep(delay)
    return delay
