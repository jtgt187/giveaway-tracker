import asyncio
import subprocess
import time
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, Future
from playwright.sync_api import sync_playwright


def _run_in_thread(fn, *args, **kwargs):
    """Run *fn* in a dedicated thread so Playwright gets a clean event loop.

    On Windows, Streamlit's already-running ``ProactorEventLoop`` cannot be
    reused by Playwright to launch browser subprocesses.  Running in a
    separate thread with a *fresh* ``ProactorEventLoop`` (via
    ``asyncio.new_event_loop()``) side-steps the issue.
    """

    def _wrapper():
        _original_loop = None
        _new_loop = None
        try:
            _original_loop = asyncio.get_event_loop()
        except RuntimeError:
            _original_loop = None
        if sys.platform == "win32":
            # ProactorEventLoop (the default on Windows) is the only loop
            # type that supports subprocess creation.  SelectorEventLoop
            # does NOT support subprocesses on Windows.
            _new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_new_loop)
        try:
            return fn(*args, **kwargs)
        finally:
            if sys.platform == "win32":
                if _new_loop is not None:
                    _new_loop.close()
                if _original_loop is not None:
                    asyncio.set_event_loop(_original_loop)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future: Future = pool.submit(_wrapper)
        return future.result()


CAPTCHA_SELECTORS = [
    '[class*="h-captcha"]',
    '[class*="hcaptcha"]',
    '[data-hcaptcha-widget-id]',
    '[class*="g-recaptcha"]',
    '[class*="recaptcha"]',
    'iframe[src*="hcaptcha"]',
    'iframe[src*="recaptcha"]',
    'iframe[src*="google.com/recaptcha"]',
]

REGION_RESTRICTED_KEYWORDS = [
    "not available in your region",
    "not available in your country",
    "sorry, this promotion",
    "promotion is not available",
    "not available to you",
    "sorry, this promotion is not available in your region",
]

ENDED_KEYWORDS = [
    "this competition has ended",
    "this giveaway has ended",
    "this promotion has ended",
    "competition has ended",
    "giveaway has ended",
    "entries are now closed",
]

# ---------------------------------------------------------------------------
# Country / region keywords used by T&C analysis
# ---------------------------------------------------------------------------

# Countries whose mention in an exclusion context means we are NOT eligible.
EXCLUDED_COUNTRIES = {
    "us": [
        "usa", "united states", "us only", "usa only",
        "united states of america", "u.s.", "u.s.a.",
    ],
    "uk": [
        "united kingdom", "uk only", "great britain", "britain",
        "england", "scotland", "wales", "northern ireland",
    ],
    "canada": ["canada", "canadian", "can only"],
    "australia": ["australia", "australian", "aus only"],
    "france": ["france", "french", "france only", "frankreich"],
    "spain": ["spain", "spanish", "spain only", "spanien"],
    "italy": ["italy", "italian", "italy only", "italien"],
    "netherlands": ["netherlands", "dutch", "holland", "niederlande"],
    "belgium": ["belgium", "belgian", "belgien"],
    "austria": ["austria", "austrian", "österreich"],
    "switzerland": ["switzerland", "swiss", "schweiz"],
    "ireland": ["ireland", "irish", "irland"],
    "sweden": ["sweden", "swedish", "schweden"],
    "norway": ["norway", "norwegian", "norwegen"],
    "denmark": ["denmark", "danish", "dänemark"],
    "finland": ["finland", "finnish", "finnland"],
    "poland": ["poland", "polish", "polen"],
    "japan": ["japan", "japanese"],
    "china": ["china", "chinese"],
    "brazil": ["brazil", "brazilian", "brasilien"],
    "india": ["india", "indian", "indien"],
    "germany": [
        "germany", "german", "deutschland", "bundesrepublik",
    ],
}

# Trigger phrases that signal the T&C text specifies excluded countries.
EXCLUSION_KEYWORDS = [
    "not eligible in",
    "not available in",
    "excluded countries",
    "countries not eligible",
    "void in",
    "void where prohibited",
    "excluding",
]

# Trigger phrases that signal the T&C text specifies *included* countries
# (positive eligibility). When found, the surrounding text is scanned for
# country / region names to determine where the giveaway IS open.
INCLUSION_KEYWORDS = [
    # English
    "only open to legal residents of",
    "only open to residents of",
    "open to legal residents of",
    "open to residents of",
    "is only open to legal residents of",
    "is only open to residents of",
    "must be a legal resident of",
    "must be a resident of",
    "must reside in",
    "available to residents of",
    "restricted to residents of",
    "limited to residents of",
    "eligible to residents of",
    "open only to individuals who are residents of",
    # Common "open worldwide" / "open to" phrasing
    "is open worldwide",
    "open worldwide",
    "sweepstakes is open to",
    "giveaway is open to",
    "contest is open to",
    "promotion is open to",
    # German
    "nur offen für bewohner von",
    "nur offen für einwohner von",
    "nur für teilnehmer aus",
    "teilnahmeberechtigt sind personen mit wohnsitz in",
    "offen für teilnehmer aus",
    "wohnhaft in",
    "teilnahme nur aus",
]

# Regions detected from inclusive phrases (positive match).
INCLUDED_REGIONS = {
    "dach": [
        "dach", "d-a-ch", "dach-raum", "dach-region",
        "germany, austria and switzerland",
        "germany, austria, and switzerland",
        "germany, austria & switzerland",
        "deutschland, österreich und schweiz",
        "deutschland, österreich und der schweiz",
        "deutschland, österreich, schweiz",
    ],
    "eu": [
        "european union", "eu member", "eu countries",
        "european economic area", "eea",
        "europäische union", "eu-länder",
    ],
    "worldwide": [
        "worldwide", "global", "international",
        "all countries", "no restriction",
        "weltweit", "keine länderbeschränkung",
    ],
}


# ---------------------------------------------------------------------------
# Gleam.io T&C selectors
# ---------------------------------------------------------------------------

# Ordered from gleam-specific (Angular ng-click) to generic fallbacks.
TERMS_SELECTORS = [
    # Gleam.io AngularJS widget: the actual ng-click toggle
    "a[ng-click*='toggleTermsAndConditions']",
    "a[ng-click*='ermsAndConditions']",
    # Gleam T&C heading that also acts as a toggle
    "h2.entry-heading--toc",
    # Gleam data-track attribute
    "a[data-track-event*='Terms']",
    # Generic Angular ng-click for terms
    "a[ng-click*='terms']",
    "a[ng-click*='Terms']",
    # Standard link selectors (non-gleam sites, or external T&C links)
    "a:has-text('Terms & Conditions')",
    "a:has-text('Terms and Conditions')",
    "a:has-text('T&C')",
    "a:has-text('Official Rules')",
    "a[href*='terms']",
    "a:has-text('Terms')",
    "a:has-text('Rules')",
    "details:has-text('Terms')",
    "summary:has-text('Terms')",
    "span:has-text('Terms & Conditions')",
    "span:has-text('Terms and Conditions')",
]

# Selectors for the container that appears after clicking the T&C toggle.
# Ordered from most specific (gleam) to generic.
TERMS_CONTAINER_SELECTORS = [
    "#terms-and-conditions",
    ".user-fragment[ng-bind-html*='terms_and_conditions']",
    ".user-fragment",
    "div[ng-show*='showTermsAndConditions']",
    ".terms-content",
    ".competition-terms",
    ".modal-body",
    ".popup-content",
]


def detect_region_restriction(page):
    page_text = page.inner_text("body")
    for keyword in REGION_RESTRICTED_KEYWORDS:
        if keyword in page_text.lower():
            return True
    return False


def detect_ended(page):
    """Check if the giveaway page shows a 'competition ended' message."""
    page_text = page.inner_text("body")
    for keyword in ENDED_KEYWORDS:
        if keyword in page_text.lower():
            return True
    return False


def detect_captcha(page):
    for selector in CAPTCHA_SELECTORS:
        if page.locator(selector).count() > 0:
            return True
    page_text = page.inner_text("body")
    captcha_keywords = ["captcha", "verify you are human", "prove you are human", "security check"]
    for keyword in captcha_keywords:
        if keyword in page_text.lower():
            return True
    return False


def wait_for_captcha_solve(page, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        if not detect_captcha(page):
            return True
        time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# T&C text analysis helpers (pure functions, no browser needed)
# ---------------------------------------------------------------------------

def _extract_tc_text(page):
    """Try to read T&C text from the gleam-specific container first,
    falling back to the full page body text."""
    for selector in TERMS_CONTAINER_SELECTORS:
        try:
            el = page.locator(selector)
            if el.count() > 0 and el.first.is_visible():
                return el.first.inner_text().lower()
        except Exception:
            continue
    # Fallback: full page
    return page.inner_text("body").lower()


def _detect_excluded_countries(text):
    """Scan *text* for exclusion trigger phrases and return a list of
    excluded country codes (e.g. ["us", "uk", "canada"])."""
    found_exclusion = any(kw in text for kw in EXCLUSION_KEYWORDS)
    if not found_exclusion:
        return []

    excluded = []
    for country, keywords in EXCLUDED_COUNTRIES.items():
        for keyword in keywords:
            if keyword in text:
                if country not in excluded:
                    excluded.append(country)
                break
    return excluded


def _detect_included_region(text):
    """Scan *text* for inclusive eligibility phrases and determine the
    region/country the giveaway is open to.

    Returns one of: "worldwide", "eu", "dach", "germany", or None if
    no inclusive phrase was found.
    """
    has_inclusion = False
    # Find the sentence containing the inclusion keyword so we can
    # check which countries/regions are mentioned nearby.
    inclusion_context = ""
    for kw in INCLUSION_KEYWORDS:
        pos = text.find(kw)
        if pos != -1:
            has_inclusion = True
            # Grab surrounding context (up to 500 chars after the keyword)
            start = max(0, pos - 50)
            end = min(len(text), pos + len(kw) + 500)
            inclusion_context += " " + text[start:end]

    if not has_inclusion:
        return None

    # Check for known regions first (DACH, EU, worldwide)
    for region, keywords in INCLUDED_REGIONS.items():
        for keyword in keywords:
            if keyword in inclusion_context:
                return region

    # Check if DACH countries are listed individually (before single-country check)
    has_germany = any(kw in inclusion_context for kw in ["germany", "deutschland"])
    has_austria = any(kw in inclusion_context for kw in ["austria", "österreich"])
    has_switzerland = any(kw in inclusion_context for kw in ["switzerland", "schweiz"])
    if has_germany and has_austria and has_switzerland:
        return "dach"
    if has_germany and has_austria:
        return "dach"  # Close enough to DACH

    # Check if Germany is explicitly mentioned as an included country
    if has_germany:
        return "germany"

    # Inclusion phrase found but Germany not mentioned -> not eligible
    return "restricted"


def analyze_terms_text(text):
    """Analyse T&C text and return (excluded_countries, detected_region).

    This is a pure function (no browser interaction) so it can be unit-tested.

    Returns:
        excluded_countries: list of country codes found in exclusion context
        detected_region: str or None -- the region the giveaway is open to
            based on inclusive phrases ("worldwide", "eu", "dach", "germany",
            "restricted", or None if no inclusive phrase was found)
    """
    excluded = _detect_excluded_countries(text)
    region = _detect_included_region(text)
    return excluded, region


# ---------------------------------------------------------------------------
# Playwright-based T&C check
# ---------------------------------------------------------------------------

def _click_terms_toggle(page):
    """Click the T&C link/toggle on a gleam.io page.

    Tries gleam-specific Angular selectors first, then falls back to
    generic link selectors. After clicking, waits for the T&C container
    to become visible.

    Returns True if a T&C element was found and clicked.
    """
    clicked = False
    for selector in TERMS_SELECTORS:
        try:
            el = page.locator(selector).first
            if el.count() > 0:
                # Scroll into view and click
                el.scroll_into_view_if_needed()
                el.click()
                clicked = True
                break
        except Exception:
            continue

    if not clicked:
        return False

    # Wait for the gleam T&C container to appear (ng-show toggle)
    for selector in TERMS_CONTAINER_SELECTORS:
        try:
            page.wait_for_selector(selector, state="visible", timeout=5000)
            return True
        except Exception:
            continue

    # Container selector didn't match -- give JS a moment to render
    time.sleep(2)
    return True


def check_terms_conditions(page, url):
    """Check Terms & Conditions for country eligibility.

    Returns:
        excluded_countries: list of excluded country codes
        detected_region: str or None -- region detected from inclusive
            phrases (e.g. "worldwide", "eu", "dach", "germany", "restricted")
    """
    # Step 1: Click the T&C toggle to reveal content
    _click_terms_toggle(page)

    # Step 2: Extract T&C text (prefer gleam container, fallback to body)
    tc_text = _extract_tc_text(page)

    # Step 3: Analyse the text
    excluded, region = analyze_terms_text(tc_text)

    return excluded, region


def find_browser_profile():
    possible_paths = []
    if os.name == "nt":
        appdata = os.environ.get("LOCALAPPDATA", "")
        possible_paths.extend([
            os.path.join(appdata, "Google", "Chrome", "User Data"),
            os.path.join(appdata, "Microsoft", "Edge", "User Data"),
        ])
    else:
        possible_paths.extend([
            os.path.expanduser("~/.config/google-chrome"),
            os.path.expanduser("~/.config/chromium"),
        ])

    for path in possible_paths:
        if os.path.exists(path):
            return path
    return None


def auto_enter_giveaway(url, callback=None):
    profile_path = find_browser_profile()
    log = []

    def emit(msg):
        log.append(msg)
        if callback:
            callback(msg)

    def _do_enter():
        emit(f"Opening giveaway: {url}")

        with sync_playwright() as p:
            launch_args = {
                "headless": False,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            }

            if profile_path:
                launch_args["channel"] = "chrome"
                launch_args["user_data_dir"] = profile_path
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=False,
                    args=launch_args["args"],
                )
                page = browser.pages[0] if browser.pages else browser.new_page()
            else:
                browser = p.chromium.launch(headless=False, args=launch_args["args"])
                context = browser.new_context()
                page = context.new_page()

            try:
                emit("Navigating to giveaway page...")
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(3)

                if detect_region_restriction(page):
                    emit("Region restriction detected! This giveaway is not available in your country.")
                    return "region_restricted", log

                if detect_ended(page):
                    emit("This competition has ended!")
                    return "ended", log

                if detect_captcha(page):
                    emit("CAPTCHA detected! Please solve it manually in the opened browser...")
                    solved = wait_for_captcha_solve(page, timeout=120)
                    if solved:
                        emit("CAPTCHA solved, continuing...")
                    else:
                        emit("CAPTCHA timeout, skipping this giveaway")
                        return False, log

                emit("Looking for Gleam entry widget...")

                entry_buttons = page.locator("button:has-text('Enter'), a:has-text('Enter'), .gleam-widget button")
                if entry_buttons.count() > 0:
                    entry_buttons.first.click()
                    emit("Clicked entry button")
                    time.sleep(2)

                if detect_captcha(page):
                    emit("CAPTCHA detected after entry! Please solve it manually...")
                    solved = wait_for_captcha_solve(page, timeout=120)
                    if not solved:
                        emit("CAPTCHA timeout after entry")
                        return False, log

                emit("Looking for simple entry methods...")
                simple_methods = page.locator(
                    'button:has-text("Follow"), button:has-text("Visit"), button:has-text("Click"), '
                    'a:has-text("Follow"), a:has-text("Visit"), a:has-text("Click")'
                )
                count = simple_methods.count()
                for i in range(min(count, 5)):
                    try:
                        simple_methods.nth(i).click()
                        emit(f"Completed entry method {i + 1}")
                        time.sleep(2)

                        if detect_captcha(page):
                            emit("CAPTCHA detected during entries! Please solve it manually...")
                            wait_for_captcha_solve(page, timeout=120)

                    except Exception as e:
                        emit(f"Entry method {i + 1} failed: {str(e)}")

                emit("Entry completed successfully!")
                return True, log

            except Exception as e:
                emit(f"Error during auto-entry: {str(e)}")
                return False, log
            finally:
                try:
                    if hasattr(browser, 'close'):
                        browser.close()
                except Exception:
                    pass

    return _run_in_thread(_do_enter)


def check_giveaway_terms(url, callback=None):
    """Check T&C of a giveaway URL for country eligibility.

    Returns:
        (excluded_countries, detected_region, log)
        - excluded_countries: list of excluded country codes
        - detected_region: str or None
        - log: list of log messages
    """
    profile_path = find_browser_profile()
    log = []

    def emit(msg):
        log.append(msg)
        if callback:
            callback(msg)

    def _do_check():
        excluded_countries = []
        detected_region = None

        with sync_playwright() as p:
            launch_args = {
                "headless": False,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            }

            if profile_path:
                launch_args["channel"] = "chrome"
                launch_args["user_data_dir"] = profile_path
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=False,
                    args=launch_args["args"],
                )
                page = browser.pages[0] if browser.pages else browser.new_page()
            else:
                browser = p.chromium.launch(headless=False, args=launch_args["args"])
                context = browser.new_context()
                page = context.new_page()

            try:
                emit(f"Checking T&C: {url}")
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(3)

                excluded_countries, detected_region = check_terms_conditions(page, url)

                if excluded_countries:
                    emit(f"Excluded countries: {', '.join(excluded_countries)}")
                if detected_region:
                    emit(f"Detected region: {detected_region}")
                if not excluded_countries and not detected_region:
                    emit("No country restrictions found in T&C")

                return excluded_countries, detected_region, log

            except Exception as e:
                emit(f"Error checking T&C: {str(e)}")
                return [], None, log
            finally:
                try:
                    if hasattr(browser, 'close'):
                        browser.close()
                except Exception:
                    pass

    return _run_in_thread(_do_check)


def check_giveaway_terms_batch(urls, callback=None):
    """Check T&C for multiple giveaway URLs using a single browser instance.

    Returns:
        list of (url, excluded_countries, detected_region) tuples
    """
    if not urls:
        return []

    profile_path = find_browser_profile()

    def emit(msg):
        if callback:
            callback(msg)

    def _do_batch():
        results = []

        with sync_playwright() as p:
            launch_args = {
                "headless": False,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            }

            if profile_path:
                launch_args["channel"] = "chrome"
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=False,
                    args=launch_args["args"],
                )
                page = browser.pages[0] if browser.pages else browser.new_page()
            else:
                browser = p.chromium.launch(headless=False, args=launch_args["args"])
                context = browser.new_context()
                page = context.new_page()

            try:
                for i, url in enumerate(urls, 1):
                    emit(f"[{i}/{len(urls)}] Checking T&C: {url}")
                    try:
                        page.goto(url, wait_until="networkidle", timeout=30000)
                        time.sleep(2)

                        excluded, region = check_terms_conditions(page, url)

                        if excluded:
                            emit(f"  Excluded: {', '.join(excluded)}")
                        if region:
                            emit(f"  Region: {region}")
                        if not excluded and not region:
                            emit(f"  No restrictions found")

                        results.append((url, excluded, region))
                    except Exception as e:
                        emit(f"  Error: {str(e)}")
                        results.append((url, [], None))
            finally:
                try:
                    if hasattr(browser, 'close'):
                        browser.close()
                except Exception:
                    pass

        return results

    return _run_in_thread(_do_batch)
