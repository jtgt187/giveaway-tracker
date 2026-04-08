import asyncio
import logging
import subprocess
import time
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from playwright.sync_api import sync_playwright

logger = logging.getLogger("enrichment")


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
            # Ensure the ProactorEventLoop policy is active in this thread
            # so subprocess creation is supported (required on Python 3.12+).
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            _new_loop = asyncio.ProactorEventLoop()
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
# NOTE: Keywords are matched with word-boundary awareness via _word_in_text()
# to avoid substring false positives (e.g. "austria" matching "australia").
EXCLUDED_COUNTRIES = {
    "us": [
        "usa", "united states", "usa only",
        "united states of america", "u.s.", "u.s.a.",
    ],
    "uk": [
        "united kingdom", "uk only", "great britain", "britain",
        "england", "scotland", "wales", "northern ireland",
    ],
    "canada": ["canada", "canadian"],
    "australia": ["australia", "australian", "aus only"],
    "france": ["france", "france only", "frankreich"],
    "spain": ["spain", "spain only", "spanien"],
    "italy": ["italy", "italy only", "italien"],
    "netherlands": ["netherlands", "dutch", "holland", "niederlande"],
    "belgium": ["belgium", "belgian", "belgien"],
    "austria": ["austria", "austrian", "österreich"],
    "switzerland": ["switzerland", "swiss", "schweiz"],
    "ireland": ["ireland", "irish", "irland"],
    "sweden": ["sweden", "swedish", "schweden"],
    "norway": ["norway", "norwegian", "norwegen"],
    "denmark": ["denmark", "danish", "dänemark"],
    "finland": ["finland", "finnish", "finnland"],
    "poland": ["poland", "polen"],
    "japan": ["japan", "japanese"],
    "china": ["china", "chinese"],
    "brazil": ["brazil", "brazilian", "brasilien"],
    "india": ["india", "indian", "indien"],
    "germany": [
        "germany", "german", "deutschland", "bundesrepublik",
    ],
}

# Trigger phrases that signal the T&C text specifies excluded countries.
# NOTE: "excluding" was removed because it matches "excluding taxes/shipping"
# and then falsely flags all countries found anywhere in the text.
EXCLUSION_KEYWORDS = [
    "not eligible in",
    "not available in",
    "excluded countries",
    "countries not eligible",
    "void in",
    "void where prohibited",
    "excluding residents",
    "excluding countries",
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
    # Gleam data-track attribute (embedded giveaways use ###APP_NAME### Click|Terms)
    "a[data-track-event*='Terms']",
    # Embedded giveaway button with data-hide (toggles .popup-block container)
    "a[data-hide*='popup-block']",
    # German-language Gleam pages
    "a:has-text('Teilnahmebedingungen')",
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

# CSS classes and attributes that identify gleam entry-method links.
# Elements matching any of these should NEVER be treated as a T&C toggle.
_ENTRY_METHOD_INDICATORS = [
    "enter-link",
    "email_subscribe",
    "email-border",
    "email_subscribe-border",
]

# data-track-event values that belong to entry methods, not T&C.
_ENTRY_TRACK_EVENT_BLACKLIST = [
    "email", "subscribe", "follow", "retweet", "like", "visit",
    "watch", "share", "click|email", "click|subscribe",
]


def _is_entry_method_element(el):
    """Return True if the Playwright element handle looks like an entry-method
    button rather than a T&C toggle.  Checks CSS classes and
    ``data-track-event`` against known entry-method patterns."""
    try:
        classes = el.get_attribute("class") or ""
        for indicator in _ENTRY_METHOD_INDICATORS:
            if indicator in classes:
                return True
        track_event = (el.get_attribute("data-track-event") or "").lower()
        if track_event:
            for keyword in _ENTRY_TRACK_EVENT_BLACKLIST:
                if keyword in track_event:
                    return True
    except Exception:
        pass
    return False


def _dismiss_expanded_entry_methods(page):
    """Collapse any auto-expanded gleam entry methods so they don't block T&C.

    Gleam auto-expands the first mandatory entry method (often an email
    subscription).  This clicks the entry-method header to collapse it,
    or presses Escape to close any overlay, so the T&C toggle becomes
    accessible.
    """
    # Try clicking the expanded entry-method header to collapse it
    collapse_selectors = [
        # Expanded entry method that is currently shown
        ".entry-method.expanded .enter-link",
        "a.enter-link.actioned",
        "a.enter-link.mandatory.default",
        # Angular expanded state
        "[ng-class*='expanded']",
    ]
    for selector in collapse_selectors:
        try:
            els = page.locator(selector)
            if els.count() > 0:
                # Click the body (outside the entry method) to deselect
                page.click("body", position={"x": 10, "y": 10}, force=True)
                time.sleep(0.5)
                return True
        except Exception:
            continue

    # Fallback: press Escape to dismiss any modal/overlay
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass

    return False


def _detect_email_entry_blocking(page):
    """Detect if an email subscription entry method is expanded and blocking
    the page, preventing T&C extraction.

    Returns True if blocking email entry is detected.
    """
    blocking_selectors = [
        "a.enter-link.email_subscribe-border",
        "a.enter-link.email-border",
        "a[data-track-event*='email'][data-track-event*='subscribe']",
        ".entry-method .email-input:visible",
        "input[type='email']:visible",
    ]
    for selector in blocking_selectors:
        try:
            if page.locator(selector).count() > 0:
                return True
        except Exception:
            continue
    return False

# Selectors for the container that appears after clicking the T&C toggle.
# Ordered from most specific (gleam) to generic.
TERMS_CONTAINER_SELECTORS = [
    "#terms-and-conditions",
    ".user-fragment[ng-bind-html*='terms_and_conditions']",
    ".user-fragment",
    "div[ng-show*='showTermsAndConditions']",
    # Embedded giveaways: popup-block container toggled via data-hide attribute
    ".popup-block",
    ".terms-content",
    ".competition-terms",
    ".modal-body",
    ".popup-content",
]


def detect_region_restriction(page):
    try:
        page_text = page.inner_text("body")
    except Exception:
        return False
    for keyword in REGION_RESTRICTED_KEYWORDS:
        if keyword in page_text.lower():
            return True
    return False


def detect_ended(page):
    """Check if the giveaway page shows a 'competition ended' message."""
    try:
        page_text = page.inner_text("body")
    except Exception:
        return False
    for keyword in ENDED_KEYWORDS:
        if keyword in page_text.lower():
            return True
    return False


def detect_captcha(page):
    for selector in CAPTCHA_SELECTORS:
        if page.locator(selector).count() > 0:
            return True
    try:
        page_text = page.inner_text("body")
    except Exception:
        return False
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
    try:
        return page.inner_text("body").lower()
    except Exception:
        return ""


# Pre-compiled regex cache for word-boundary matching
_WORD_RE_CACHE = {}


def _word_in_text(word, text):
    """Check if *word* appears in *text* with word boundaries.

    Prevents 'austria' from matching inside 'australia', etc.
    """
    if word not in _WORD_RE_CACHE:
        # Escape the word for regex, wrap in word boundaries
        _WORD_RE_CACHE[word] = re.compile(r'\b' + re.escape(word) + r'\b', re.IGNORECASE)
    return bool(_WORD_RE_CACHE[word].search(text))


def _detect_excluded_countries(text):
    """Scan *text* for exclusion trigger phrases and return a list of
    excluded country codes (e.g. ["us", "uk", "canada"]).

    Only scans for countries in the vicinity of exclusion keywords
    to avoid false positives from country names elsewhere in the text.
    """
    # Find exclusion context: text around each exclusion keyword
    exclusion_context = ""
    for kw in EXCLUSION_KEYWORDS:
        pos = text.find(kw)
        if pos != -1:
            start = max(0, pos - 50)
            end = min(len(text), pos + len(kw) + 500)
            exclusion_context += " " + text[start:end]

    if not exclusion_context:
        return []

    excluded = []
    for country, keywords in EXCLUDED_COUNTRIES.items():
        for keyword in keywords:
            if _word_in_text(keyword, exclusion_context):
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
    has_germany = any(_word_in_text(kw, inclusion_context) for kw in ["germany", "deutschland"])
    has_austria = any(_word_in_text(kw, inclusion_context) for kw in ["austria", "österreich"])
    has_switzerland = any(_word_in_text(kw, inclusion_context) for kw in ["switzerland", "schweiz"])
    if has_germany and has_austria and has_switzerland:
        return "dach"
    if has_germany and has_austria:
        # Only DE+AT -- not full DACH (Switzerland not mentioned)
        return "germany"

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

    Skips any element that looks like a gleam entry-method button (email
    subscribe, follow, etc.) to avoid accidentally triggering those
    actions during enrichment.

    Returns True if a T&C element was found and clicked.
    """
    clicked = False
    for selector in TERMS_SELECTORS:
        try:
            matches = page.locator(selector)
            count = matches.count()
            for i in range(count):
                el = matches.nth(i)
                # Guard: skip elements that are entry-method buttons
                if _is_entry_method_element(el):
                    continue
                # Scroll into view and click
                el.scroll_into_view_if_needed()
                el.click()
                clicked = True
                break
            if clicked:
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

    Dismisses any auto-expanded entry methods (e.g. email subscription)
    before attempting to open the T&C section.

    Returns:
        excluded_countries: list of excluded country codes
        detected_region: str or None -- region detected from inclusive
            phrases (e.g. "worldwide", "eu", "dach", "germany", "restricted")
    """
    # Step 0: Dismiss any auto-expanded entry methods (email subscribe, etc.)
    _dismiss_expanded_entry_methods(page)

    # Step 1: Click the T&C toggle to reveal content
    _click_terms_toggle(page)

    # Step 2: Extract T&C text (prefer gleam container, fallback to body)
    tc_text = _extract_tc_text(page)

    # Step 3: Analyse the text
    excluded, region = analyze_terms_text(tc_text)

    return excluded, region


def find_browser_profile():
    """Return ``(profile_path, channel)`` for the first usable browser profile.

    *channel* is the Playwright channel name (``"chrome"``, ``"msedge"``, or
    ``"chromium"``) that corresponds to the discovered profile so that
    ``launch_persistent_context`` uses the matching installed browser binary
    instead of the bundled Chromium (which is incompatible with Chrome/Edge
    profile formats).

    Returns ``(None, None)`` when no profile is found.
    """
    import platform
    # Each entry is (path, playwright_channel).
    candidates = []
    if os.name == "nt":
        appdata = os.environ.get("LOCALAPPDATA", "")
        candidates.extend([
            (os.path.join(appdata, "Google", "Chrome", "User Data"), "chrome"),
            (os.path.join(appdata, "Microsoft", "Edge", "User Data"), "msedge"),
        ])
    elif platform.system() == "Darwin":
        candidates.extend([
            (os.path.expanduser("~/Library/Application Support/Google/Chrome"), "chrome"),
            (os.path.expanduser("~/Library/Application Support/Microsoft Edge"), "msedge"),
            (os.path.expanduser("~/Library/Application Support/Chromium"), "chromium"),
        ])
    else:
        candidates.extend([
            (os.path.expanduser("~/.config/google-chrome"), "chrome"),
            (os.path.expanduser("~/.config/chromium"), "chromium"),
        ])

    for path, channel in candidates:
        if os.path.exists(path):
            return path, channel
    return None, None


def auto_enter_giveaway(url, callback=None):
    profile_path, browser_channel = find_browser_profile()
    log = []

    def emit(msg):
        log.append(msg)
        if callback:
            callback(msg)

    def _do_enter():
        emit(f"Opening giveaway: {url}")
        nonlocal profile_path

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
                try:
                    browser = p.chromium.launch_persistent_context(
                        user_data_dir=profile_path,
                        channel=browser_channel,
                        headless=False,
                        args=launch_args["args"],
                    )
                except Exception as profile_err:
                    err_msg = str(profile_err).lower()
                    if "lock" in err_msg or "already in use" in err_msg or "single instance" in err_msg:
                        emit("Browser profile locked (browser running). Using temporary profile.")
                    else:
                        emit(f"Could not use browser profile: {profile_err}. Using temporary profile.")
                    browser = p.chromium.launch(headless=False, args=launch_args["args"])
                    context = browser.new_context()
                    page = context.new_page()
                    profile_path = None
                if profile_path:
                    page = browser.pages[0] if browser.pages else browser.new_page()
            else:
                browser = p.chromium.launch(headless=False, args=launch_args["args"])
                context = browser.new_context()
                page = context.new_page()

            try:
                emit("Navigating to giveaway page...")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)

                if detect_region_restriction(page):
                    emit("Region restriction detected! This giveaway is not available in your country.")
                    return ("region_restricted", log)

                if detect_ended(page):
                    emit("This competition has ended!")
                    return ("ended", log)

                if detect_captcha(page):
                    emit("CAPTCHA detected! Please solve it manually in the opened browser...")
                    solved = wait_for_captcha_solve(page, timeout=120)
                    if solved:
                        emit("CAPTCHA solved, continuing...")
                    else:
                        emit("CAPTCHA timeout, skipping this giveaway")
                        return ("failed", log)

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
                        return ("failed", log)

                emit("Looking for simple entry methods...")
                simple_methods = page.locator(
                    'button:has-text("Follow"), button:has-text("Visit"), button:has-text("Click"), '
                    'a:has-text("Follow"), a:has-text("Visit"), a:has-text("Click")'
                )
                count = simple_methods.count()
                entered_count = 0
                for i in range(min(count, 5)):
                    try:
                        simple_methods.nth(i).click()
                        entered_count += 1
                        emit(f"Completed entry method {i + 1}")
                        time.sleep(2)

                        if detect_captcha(page):
                            emit("CAPTCHA detected during entries! Please solve it manually...")
                            wait_for_captcha_solve(page, timeout=120)

                    except Exception as e:
                        emit(f"Entry method {i + 1} failed: {str(e)}")

                if entered_count > 0:
                    emit("Entry completed successfully!")
                    return ("success", log)
                else:
                    emit("No entry methods were completed")
                    return ("failed", log)

            except Exception as e:
                emit(f"Error during auto-entry: {str(e)}")
                return ("failed", log)
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
    profile_path, browser_channel = find_browser_profile()
    log = []

    def emit(msg):
        log.append(msg)
        if callback:
            callback(msg)

    def _do_check():
        nonlocal profile_path
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
                try:
                    browser = p.chromium.launch_persistent_context(
                        user_data_dir=profile_path,
                        channel=browser_channel,
                        headless=False,
                        args=launch_args["args"],
                    )
                except Exception as profile_err:
                    err_msg = str(profile_err).lower()
                    if "lock" in err_msg or "already in use" in err_msg or "single instance" in err_msg:
                        emit("Browser profile locked (browser running). Using temporary profile.")
                    else:
                        emit(f"Could not use browser profile: {profile_err}. Using temporary profile.")
                    browser = p.chromium.launch(headless=False, args=launch_args["args"])
                    context = browser.new_context()
                    page = context.new_page()
                    profile_path = None
                if profile_path:
                    page = browser.pages[0] if browser.pages else browser.new_page()
            else:
                browser = p.chromium.launch(headless=False, args=launch_args["args"])
                context = browser.new_context()
                page = context.new_page()

            try:
                emit(f"Checking T&C: {url}")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
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


# ---------------------------------------------------------------------------
# Deadline extraction
# ---------------------------------------------------------------------------

# CSS selectors where Gleam typically renders countdown/end-date info
_DEADLINE_SELECTORS = [
    '.countdown',
    '.competition-countdown',
    '.incentive-timer',
    '.timer',
    '.ends-at',
    '.end-date',
    '.competition-ends',
    '.gleam-countdown',
    '.incentive-description',
    '[data-ends]',
    '[data-deadline]',
    '[class*="countdown"]',
    '[class*="timer"]',
    '[class*="deadline"]',
    '[class*="end-date"]',
    '[class*="expires"]',
]

# Regex patterns for dates near end-related keywords in page text
_DEADLINE_TEXT_RE = re.compile(
    r'(?:ends?|closing|closes?|deadline|expires?)[:\s]+'
    r'(\w+\s+\d{1,2}\s+\w+\s+\d{4}(?:\s+at\s+\d{2}:\d{2}(?::\d{2})?)?)',
    re.IGNORECASE,
)

_DEADLINE_DATE_NEAR_RE = re.compile(
    r'(?:ends?|closing|closes?|deadline|expires?).{0,50}?'
    r'(\d{1,2}\s+\w+\s+\d{4}(?:\s+at\s+\d{2}:\d{2}(?::\d{2})?)?)',
    re.IGNORECASE,
)

# US month-first format: "Ends: April 6, 2026" / "Ends April 17, 2026 11:59 PM"
_DEADLINE_US_DATE_RE = re.compile(
    r'(?:ends?|closing|closes?|deadline|expires?)[:\s]+'
    r'((?:January|February|March|April|May|June|July|August|September|October|November|December|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}'
    r'(?:\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?)?)',
    re.IGNORECASE,
)

# Numeric date formats: "Ends: 06/04/2026", "Closes: 2026-04-06"
_DEADLINE_NUMERIC_DATE_RE = re.compile(
    r'(?:ends?|closing|closes?|deadline|expires?).{0,30}?'
    r'(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
    re.IGNORECASE,
)

# Relative countdown: "Ends in 11 days", "2d 3h 15m"
_DEADLINE_RELATIVE_RE = re.compile(
    r'(?:ends?\s+in\s+)(\d+\s*(?:days?|d)\s*(?:\d+\s*(?:hours?|hrs?|h))?\s*(?:\d+\s*(?:minutes?|mins?|m))?)',
    re.IGNORECASE,
)


def _extract_deadline_from_page(page):
    """Extract a deadline string from the current Playwright page.

    Tries Gleam-specific CSS selectors first, then falls back to regex
    scanning of the page body text.
    """
    url = ""
    try:
        url = page.url
    except Exception:
        pass

    # 1) CSS selector scan
    for sel in _DEADLINE_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el:
                text = (el.text_content() or '').strip()
                if len(text) > 3 and re.search(r'\d', text):
                    logger.info("deadline_extract: FOUND via selector '%s' -> '%s' [%s]",
                                sel, text, url)
                    return text
                elif text:
                    logger.debug("deadline_extract: selector '%s' matched but text too short/no digits: '%s' [%s]",
                                 sel, text[:80], url)
        except Exception:
            continue

    logger.debug("deadline_extract: no CSS selectors matched, trying regex fallback [%s]", url)

    # 2) Regex fallback on body text
    try:
        body_text = page.evaluate('document.body ? document.body.textContent : ""')
    except Exception:
        body_text = ''

    if not body_text:
        logger.warning("deadline_extract: empty body text, cannot extract deadline [%s]", url)
        return ''

    # Try each regex pattern in order of specificity
    for label, pattern in [
        ("primary", _DEADLINE_TEXT_RE),
        ("date_near", _DEADLINE_DATE_NEAR_RE),
        ("us_date", _DEADLINE_US_DATE_RE),
        ("numeric", _DEADLINE_NUMERIC_DATE_RE),
        ("relative", _DEADLINE_RELATIVE_RE),
    ]:
        m = pattern.search(body_text)
        if m:
            result = m.group(1).strip()
            logger.info("deadline_extract: FOUND via regex '%s' -> '%s' [%s]",
                        label, result, url)
            return result

    # Log a snippet around any end-related keywords for post-mortem debugging
    end_kw_re = re.compile(r'(?:ends?|closing|closes?|deadline|expires?)', re.IGNORECASE)
    snippets = []
    for m in end_kw_re.finditer(body_text):
        start = max(0, m.start() - 20)
        end = min(len(body_text), m.end() + 80)
        snippets.append(body_text[start:end].replace('\n', ' ').strip())
    if snippets:
        logger.warning("deadline_extract: NO deadline found. Keyword context snippets: %s [%s]",
                       snippets[:3], url)
    else:
        logger.debug("deadline_extract: no end-related keywords found in body text [%s]", url)

    return ''


# ---------------------------------------------------------------------------
# Combined batch enrichment (parallel workers)
# ---------------------------------------------------------------------------

# Number of browser instances to run concurrently during enrichment.
ENRICHMENT_WORKERS = 4


def _enrich_single_url(page, url, emit):
    """Enrich one URL on an already-loaded *page*.  Returns a result dict."""
    try:
        logger.info("enrich: starting %s", url)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)  # let the Gleam widget render

        # -- Ended / region-blocked (fast text checks) --
        ended = detect_ended(page)
        region_blocked = detect_region_restriction(page)

        if ended:
            emit(f"  Ended")
            logger.info("enrich: ENDED %s", url)
        if region_blocked:
            emit(f"  Region blocked")
            logger.info("enrich: REGION_BLOCKED %s", url)

        # -- Deadline --
        deadline = ''
        if not ended and not region_blocked:
            deadline = _extract_deadline_from_page(page)
            if deadline:
                emit(f"  Deadline: {deadline}")
            else:
                logger.warning("enrich: no deadline extracted for %s", url)

        # -- T&C --
        excluded = []
        region = None
        email_blocked = False
        if not ended and not region_blocked:
            # Check for email subscription blocking before T&C extraction
            if _detect_email_entry_blocking(page):
                emit(f"  Email subscription entry detected, attempting to dismiss...")
                logger.debug("enrich: email entry blocking detected, dismissing... %s", url)
                _dismiss_expanded_entry_methods(page)
                time.sleep(1)
                # Re-check after dismissal attempt
                if _detect_email_entry_blocking(page):
                    emit(f"  Email entry still blocking -- skipping T&C, flagging for review")
                    email_blocked = True
                    logger.warning("enrich: email entry still blocking after dismiss %s", url)

            if not email_blocked:
                excluded, region = check_terms_conditions(page, url)
                if excluded:
                    emit(f"  Excluded: {', '.join(excluded)}")
                    logger.info("enrich: excluded countries=%s for %s", excluded, url)
                if region:
                    emit(f"  Region: {region}")
                    logger.info("enrich: detected region=%s for %s", region, url)

        if not ended and not region_blocked and not excluded and not region and not deadline and not email_blocked:
            emit(f"  No restrictions or deadline found")
            logger.info("enrich: no data extracted for %s", url)

        result = {
            "url": url,
            "deadline": deadline,
            "excluded": excluded,
            "region": region,
            "ended": ended,
            "region_blocked": region_blocked,
            "email_blocked": email_blocked,
        }
        logger.debug("enrich: result for %s -> %s", url, result)
        return result

    except Exception as e:
        emit(f"  Error: {str(e)}")
        logger.error("enrich: ERROR for %s: %s", url, e, exc_info=True)
        return {
            "url": url,
            "deadline": '',
            "excluded": [],
            "region": None,
            "ended": False,
            "region_blocked": False,
            "error": str(e),
        }


def _enrich_worker(worker_id, urls_chunk, total_urls, on_result, emit, counter, lock):
    """Worker function: launches its own browser and enriches its chunk.

    Runs in a dedicated thread with its own ``sync_playwright()`` context
    so that each worker has an isolated browser instance (Playwright sync
    API is not thread-safe across shared objects).

    If the page object becomes invalid (e.g. after a crash or accidental
    navigation), the worker recreates it from the existing browser context
    instead of losing all remaining URLs.

    Args:
        worker_id: integer identifier for log messages.
        urls_chunk: list of URLs this worker should process.
        total_urls: total number of URLs across all workers (for log messages).
        on_result: callback invoked per URL (may be None).
        emit: logging callback.
        counter: mutable list ``[n]`` tracking the global completed count.
        lock: ``threading.Lock`` protecting *counter* and *on_result*.
    """
    results = []
    logger.info("[W%d] starting with %d URLs (total across workers: %d)",
                worker_id, len(urls_chunk), total_urls)

    # Each worker needs its own event loop on Windows for Playwright
    _original_loop = None
    _new_loop = None
    try:
        _original_loop = asyncio.get_event_loop()
    except RuntimeError:
        _original_loop = None
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        _new_loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(_new_loop)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )
            context = browser.new_context()
            page = context.new_page()

            try:
                for url in urls_chunk:
                    with lock:
                        idx = counter[0] + 1
                    emit(f"[W{worker_id}] [{idx}/{total_urls}] Enriching: {url}")
                    logger.info("[W%d] [%d/%d] enriching: %s", worker_id, idx, total_urls, url)

                    # Check if the page is still usable; recreate if dead
                    try:
                        page.url  # quick health check
                    except Exception:
                        emit(f"[W{worker_id}] Page crashed, creating new tab...")
                        logger.warning("[W%d] page crashed, recreating...", worker_id)
                        try:
                            page = context.new_page()
                        except Exception:
                            emit(f"[W{worker_id}] Context dead, recreating browser context...")
                            logger.warning("[W%d] context dead, recreating browser context...", worker_id)
                            try:
                                context = browser.new_context()
                                page = context.new_page()
                            except Exception as ctx_err:
                                emit(f"[W{worker_id}] Browser dead, cannot recover: {ctx_err}")
                                logger.error("[W%d] browser dead, stopping worker: %s", worker_id, ctx_err)
                                break

                    entry = _enrich_single_url(page, url, emit)
                    results.append(entry)

                    with lock:
                        counter[0] += 1
                        if on_result:
                            on_result(entry)

                    # Post-enrichment: verify page is still alive for next URL
                    try:
                        page.url
                    except Exception:
                        emit(f"[W{worker_id}] Page died after enriching {url}, will recreate for next URL")
                        logger.warning("[W%d] page died after %s, recreating", worker_id, url)
                        try:
                            page = context.new_page()
                        except Exception:
                            try:
                                context = browser.new_context()
                                page = context.new_page()
                            except Exception:
                                emit(f"[W{worker_id}] Cannot recreate page, stopping worker")
                                logger.error("[W%d] cannot recreate page, stopping worker", worker_id)
                                break
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    finally:
        if sys.platform == "win32":
            if _new_loop is not None:
                _new_loop.close()
            if _original_loop is not None:
                asyncio.set_event_loop(_original_loop)

    logger.info("[W%d] finished, processed %d URLs", worker_id, len(results))
    return results


def enrich_giveaways_batch(urls, on_result=None, callback=None):
    """Enrich multiple giveaway URLs using parallel browser workers.

    Splits the URL list into ``ENRICHMENT_WORKERS`` chunks and launches
    one headless Chromium instance per chunk in separate threads.  Each
    worker processes its URLs sequentially, but the workers run
    concurrently for ~4x throughput.

    Args:
        urls: list of giveaway URLs to enrich.
        on_result: optional callable invoked after each URL with a dict::

                {"url", "deadline", "excluded", "region", "ended", "region_blocked"}

            so the caller can persist results incrementally.
            **Must not call Streamlit widgets** (runs in a background
            thread).
        callback: optional callable receiving log messages (str).

    Returns:
        list of dicts, one per URL::

            {
                "url": str,
                "deadline": str,           # empty string if not found
                "excluded": list[str],     # excluded country codes
                "region": str | None,      # detected region
                "ended": bool,
                "region_blocked": bool,
            }
    """
    if not urls:
        return []

    def emit(msg):
        if callback:
            callback(msg)

    n_workers = min(ENRICHMENT_WORKERS, len(urls))

    # Split URLs into roughly-equal chunks for each worker
    chunks = [[] for _ in range(n_workers)]
    for i, url in enumerate(urls):
        chunks[i % n_workers].append(url)

    # Shared mutable counter and lock for thread-safe progress tracking
    counter = [0]  # completed count
    lock = threading.Lock()
    total = len(urls)

    logger.info("enrich_batch: starting %d URLs across %d workers", total, n_workers)
    emit(f"Starting enrichment: {total} URLs across {n_workers} parallel workers")

    def _run_all_workers():
        all_results = []
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = []
            for wid, chunk in enumerate(chunks, 1):
                if not chunk:
                    continue
                futures.append(
                    pool.submit(
                        _enrich_worker,
                        wid, chunk, total, on_result, emit, counter, lock,
                    )
                )

            for future in futures:
                try:
                    worker_results = future.result()
                    all_results.extend(worker_results)
                except Exception as e:
                    emit(f"Worker error: {e}")
                    logger.error("enrich_batch: worker error: %s", e, exc_info=True)

        # Summarise results
        ended_count = sum(1 for r in all_results if r.get("ended"))
        deadline_count = sum(1 for r in all_results if r.get("deadline"))
        error_count = sum(1 for r in all_results if r.get("error"))
        logger.info("enrich_batch: finished %d URLs -- deadlines=%d, ended=%d, errors=%d",
                     len(all_results), deadline_count, ended_count, error_count)
        return all_results

    return _run_in_thread(_run_all_workers)
