import subprocess
import time
import os
import re
from playwright.sync_api import sync_playwright


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
]

EXCLUDED_COUNTRIES = {
    "us": ["usa", "united states", "us only", "usa only", "united states of america"],
    "uk": ["united kingdom", "uk only", "great britain", "britain", "england", "scotland", "wales"],
    "canada": ["canada", "canadian", "can only"],
    "australia": ["australia", "australian", "aus only"],
    "france": ["france", "french", "france only"],
    "spain": ["spain", "spanish", "spain only"],
    "italy": ["italy", "italian", "italy only"],
    "netherlands": ["netherlands", "dutch", "holland"],
    "belgium": ["belgium", "belgian"],
    "austria": ["austria", "austrian"],
    "switzerland": ["switzerland", "swiss"],
    "ireland": ["ireland", "irish"],
    "sweden": ["sweden", "swedish"],
    "norway": ["norway", "norwegian"],
    "denmark": ["denmark", "danish"],
    "finland": ["finland", "finnish"],
    "poland": ["poland", "polish"],
    "japan": ["japan", "japanese"],
    "china": ["china", "chinese"],
    "brazil": ["brazil", "brazilian"],
    "india": ["india", "indian"],
}

EXCLUSION_KEYWORDS = [
    "not eligible in",
    "not available in",
    "excluded countries",
    "countries not eligible",
    "restricted to",
    "open to residents of",
    "residents of",
    "must be located in",
    "excluding",
    "void in",
]


def detect_region_restriction(page):
    page_text = page.inner_text("body")
    for keyword in REGION_RESTRICTED_KEYWORDS:
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


def check_terms_conditions(page, url):
    """Check Terms & Conditions for country exclusions. Returns tuple (excluded_countries, original_page_url)."""
    excluded = []
    original_url = page.url
    
    terms_selectors = [
        "a:has-text('Terms')",
        "a:has-text('Terms & Conditions')",
        "a:has-text('T&C')",
        "a:has-text('Terms and Conditions')",
        "a[href*='terms']",
        "a:has-text('Official Rules')",
        "a:has-text('Rules')",
        "details:has-text('Terms')",
        "summary:has-text('Terms')",
    ]
    
    for selector in terms_selectors:
        try:
            terms_link = page.locator(selector).first
            if terms_link.count() > 0:
                terms_link.click()
                time.sleep(2)
                break
        except Exception:
            continue
    
    page_text = page.inner_text("body").lower()
    found_exclusion = False
    
    for keyword in EXCLUSION_KEYWORDS:
        if keyword in page_text:
            found_exclusion = True
            break
    
    if found_exclusion:
        for country, keywords in EXCLUDED_COUNTRIES.items():
            for keyword in keywords:
                if keyword in page_text:
                    if country not in excluded:
                        excluded.append(country)
    
    return excluded, original_url


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


def check_giveaway_terms(url, callback=None):
    """Check T&C of a giveaway URL for country exclusions."""
    profile_path = find_browser_profile()
    log = []

    def emit(msg):
        log.append(msg)
        if callback:
            callback(msg)

    excluded_countries = []
    
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
            
            excluded_countries, _ = check_terms_conditions(page, url)
            
            if excluded_countries:
                emit(f"Excluded countries found: {', '.join(excluded_countries)}")
            else:
                emit("No country exclusions found in T&C")
            
            return excluded_countries, log

        except Exception as e:
            emit(f"Error checking T&C: {str(e)}")
            return [], log
        finally:
            try:
                if hasattr(browser, 'close'):
                    browser.close()
            except Exception:
                pass
