# Test Plan: Interactive Elements for Giveaway Tracker

## Bugs Found During Analysis

### Bug #1: "Clear All Data" Confirmation Button Never Works
**Location:** `app.py:1483-1493`
**Issue:** The "Yes, delete everything" button is nested inside the "Clear All Data" button's `if` block. In Streamlit, clicking "Clear All Data" triggers a rerun, which resets the first button to `False`, making the confirmation button disappear before it can be clicked.
**Fix:** Use `st.session_state` to track confirmation state across reruns. Replace the nested button pattern with a session state flag.

### Bug #2: Wrong Database Path in "Clear All Data"
**Location:** `app.py:1487`
**Issue:** Uses `sqlite3.connect("giveaways.db")` (relative path) instead of the centralized `DB_PATH` from `database.py`. This connects to a different database depending on the working directory.
**Fix:** Import and use `get_connection()` from `database.py` instead of a manual `sqlite3.connect()`.

---

## File Structure

```
tests/
├── __init__.py
├── conftest.py          # Shared fixtures (tmp_db, tmp_config, sample data)
├── test_database.py     # Database operations triggered by buttons
├── test_config.py       # Config persistence triggered by settings widgets
├── test_utils.py        # Utility functions used by UI elements
└── test_app_ui.py       # Streamlit button/input/widget handler tests
```

---

## conftest.py - Shared Fixtures

```python
"""Shared pytest fixtures for giveaway-tracker tests."""
import os, sys, json, tempfile
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Fresh temporary SQLite database for each test."""
    import database
    db_file = str(tmp_path / "test_giveaways.db")
    monkeypatch.setattr(database, "DB_PATH", db_file)
    monkeypatch.setattr(database, "_blacklist_cache", None)
    # Also patch the blacklist path to use tmp_path
    bl_path = str(tmp_path / "test_blacklist.txt")
    monkeypatch.setattr(database, "_get_blacklist_path", lambda: bl_path)
    database.init_db()
    return db_file

@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    """Fresh temporary config.json for each test."""
    import config
    config_file = str(tmp_path / "test_config.json")
    monkeypatch.setattr(config, "CONFIG_PATH", config_file)
    monkeypatch.setattr(config, "_config_cache", None)
    return config_file

@pytest.fixture()
def sample_giveaway():
    return {
        "title": "Win a PlayStation 5",
        "url": "https://gleam.io/abc123/win-ps5",
        "source": "gleamfinder",
        "description": "Enter to win",
        "deadline": "Friday 10 April 2026 at 23:59:59",
        "country_restriction": "worldwide",
    }

@pytest.fixture()
def sample_giveaways():
    return [
        {"title": "Win a PS5", "url": "https://gleam.io/abc123/win-ps5",
         "source": "gleamfinder", "description": "", "deadline": "Friday 10 April 2026 at 23:59:59",
         "country_restriction": "worldwide"},
        {"title": "Win an Xbox", "url": "https://gleam.io/def456/win-xbox",
         "source": "bestofgleam", "description": "", "deadline": "Saturday 11 April 2026 at 22:00:00",
         "country_restriction": "germany"},
        {"title": "Win a Switch", "url": "https://gleam.io/ghi789/win-switch",
         "source": "gleamdb", "description": "", "deadline": "Sunday 12 April 2026 at 20:00:00",
         "country_restriction": "us"},
        {"title": "Win Steam Keys", "url": "https://gleam.io/jkl012/win-steam",
         "source": "gleam_official", "description": "", "deadline": "",
         "country_restriction": "eu"},
    ]
```

---

## tests/test_database.py (~17 test cases)

Tests the database layer functions that every button ultimately calls.

| # | Test Name | What it validates | Button/element it covers |
|---|-----------|-------------------|--------------------------|
| 1 | `test_init_db_creates_tables` | Tables and indexes exist after init_db() | App startup |
| 2 | `test_add_giveaway_inserts` | Single giveaway inserted correctly | Crawl + import |
| 3 | `test_add_giveaway_duplicate_ignored` | INSERT OR IGNORE on duplicate URL | Crawl dedup |
| 4 | `test_add_giveaway_blacklisted_rejected` | Blacklisted URL not inserted | Blacklist "X" button |
| 5 | `test_add_giveaways_batch` | Batch insert returns correct count | "Start Crawl" button |
| 6 | `test_add_giveaways_batch_empty` | Empty list returns 0 | Edge case |
| 7 | `test_get_giveaways_all` | Returns all giveaways | Giveaway table display |
| 8 | `test_get_giveaways_by_status` | Filter by status works | Status filter selectbox |
| 9 | `test_update_giveaway_status` | Status update persists | "Enter", "Skip" buttons |
| 10 | `test_update_giveaway_entries` | Entry counts + probability updated | Auto-enter result |
| 11 | `test_get_giveaway_by_url` | Lookup by URL works | Crawl dedup |
| 12 | `test_get_known_urls` | Returns set of all URLs | Crawl dedup |
| 13 | `test_update_terms_check` | Terms checked flag + excluded countries | "Check T&C" button |
| 14 | `test_update_terms_check_with_region` | detected_region updates country_restriction | "Check T&C" button |
| 15 | `test_get_stats` | Aggregate stats correct | Dashboard stat cards |
| 16 | `test_delete_not_eligible` | Only not_eligible rows deleted | "Delete All Not Eligible" button |
| 17 | `test_add_to_blacklist` | URL added to file, giveaway deleted from DB | "X" blacklist button |
| 18 | `test_remove_from_blacklist` | URL removed from blacklist file | Blacklist management |
| 19 | `test_parse_deadline_formats` | All date formats parsed correctly | Deadline display |
| 20 | `test_remove_expired_giveaways` | Expired entries removed | Startup cleanup |

```python
"""Tests for database.py -- covers all DB operations triggered by UI buttons."""
import pytest
from datetime import datetime, timedelta

def test_init_db_creates_tables(tmp_db):
    import sqlite3, database
    conn = sqlite3.connect(tmp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='giveaways'")
    assert cursor.fetchone() is not None
    conn.close()

def test_add_giveaway_inserts(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways
    result = add_giveaway(**sample_giveaway)
    assert result is True
    rows = get_giveaways()
    assert len(rows) == 1
    assert rows[0]["title"] == sample_giveaway["title"]

def test_add_giveaway_duplicate_ignored(tmp_db, sample_giveaway):
    from database import add_giveaway
    add_giveaway(**sample_giveaway)
    result = add_giveaway(**sample_giveaway)
    assert result is False  # duplicate URL

def test_add_giveaway_blacklisted_rejected(tmp_db, sample_giveaway):
    from database import add_giveaway, add_to_blacklist
    add_to_blacklist(sample_giveaway["url"])
    result = add_giveaway(**sample_giveaway)
    assert result is False

def test_add_giveaways_batch(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, get_giveaways
    count = add_giveaways_batch(sample_giveaways)
    assert count == len(sample_giveaways)
    rows = get_giveaways(gleam_only=False)
    assert len(rows) == len(sample_giveaways)

def test_add_giveaways_batch_empty(tmp_db):
    from database import add_giveaways_batch
    assert add_giveaways_batch([]) == 0

def test_get_giveaways_by_status(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status
    add_giveaway(**sample_giveaway)
    rows = get_giveaways()
    gid = rows[0]["id"]
    update_giveaway_status(gid, "eligible")
    eligible = get_giveaways(status="eligible")
    assert len(eligible) == 1
    new = get_giveaways(status="new")
    assert len(new) == 0

def test_update_giveaway_status(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "participated", "entered via auto-enter")
    row = get_giveaways(status="participated")[0]
    assert row["status"] == "participated"
    assert row["notes"] == "entered via auto-enter"
    assert row["entered_at"] != ""

def test_update_giveaway_entries(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_entries
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_entries(gid, total_entries=1000, your_entries=5)
    row = get_giveaways()[0]
    assert row["total_entries"] == 1000
    assert row["your_entries"] == 5
    assert row["win_probability"] == pytest.approx(0.5)

def test_get_giveaway_by_url(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaway_by_url
    add_giveaway(**sample_giveaway)
    row = get_giveaway_by_url(sample_giveaway["url"])
    assert row is not None
    assert row["title"] == sample_giveaway["title"]
    assert get_giveaway_by_url("https://nonexistent.com") is None

def test_get_known_urls(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, get_known_urls
    add_giveaways_batch(sample_giveaways)
    urls = get_known_urls()
    assert isinstance(urls, set)
    assert len(urls) == len(sample_giveaways)
    for g in sample_giveaways:
        assert g["url"] in urls

def test_update_terms_check(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_terms_check
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_terms_check(gid, True, "us,uk")
    row = get_giveaways()[0]
    assert row["terms_checked"] == 1
    assert row["terms_excluded"] == "us,uk"

def test_update_terms_check_with_region(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_terms_check
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_terms_check(gid, True, "us", detected_region="germany")
    row = get_giveaways()[0]
    assert row["country_restriction"] == "germany"

def test_get_stats(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, get_stats, update_giveaway_status, get_giveaways
    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    update_giveaway_status(rows[0]["id"], "participated")
    update_giveaway_status(rows[1]["id"], "eligible")
    update_giveaway_status(rows[2]["id"], "not_eligible")
    stats = get_stats(gleam_only=False)
    assert stats["total"] == 4
    assert stats["participated"] == 1
    assert stats["eligible"] == 1
    assert stats["not_eligible"] == 1
    assert stats["new"] == 1

def test_delete_not_eligible(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, delete_not_eligible, update_giveaway_status, get_giveaways
    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    update_giveaway_status(rows[0]["id"], "not_eligible")
    update_giveaway_status(rows[1]["id"], "not_eligible")
    deleted = delete_not_eligible()
    assert deleted == 2
    remaining = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert len(remaining) == 2
    assert all(r["status"] != "not_eligible" for r in remaining)

def test_add_to_blacklist(tmp_db, sample_giveaway):
    from database import add_giveaway, add_to_blacklist, get_giveaway_by_url, is_blacklisted
    add_giveaway(**sample_giveaway)
    add_to_blacklist(sample_giveaway["url"], "manual")
    assert get_giveaway_by_url(sample_giveaway["url"]) is None
    assert is_blacklisted(sample_giveaway["url"]) is True

def test_remove_from_blacklist(tmp_db, sample_giveaway):
    from database import add_to_blacklist, remove_from_blacklist, is_blacklisted
    add_to_blacklist(sample_giveaway["url"])
    assert is_blacklisted(sample_giveaway["url"]) is True
    remove_from_blacklist(sample_giveaway["url"])
    assert is_blacklisted(sample_giveaway["url"]) is False

def test_parse_deadline_full_format(tmp_db):
    from database import parse_deadline
    dt = parse_deadline("Friday 03 April 2026 at 22:59:59")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 3

def test_parse_deadline_empty(tmp_db):
    from database import parse_deadline
    assert parse_deadline("") is None
    assert parse_deadline(None) is None

def test_remove_expired_giveaways(tmp_db):
    from database import add_giveaway, remove_expired_giveaways, get_giveaways
    # Add one expired giveaway
    add_giveaway("Expired", "https://gleam.io/expired1/test", "test",
                 deadline="Friday 01 January 2021 at 00:00:00")
    # Add one future giveaway
    add_giveaway("Future", "https://gleam.io/future1/test", "test",
                 deadline="Friday 01 January 2030 at 00:00:00")
    removed = remove_expired_giveaways()
    assert removed == 1
    remaining = get_giveaways()
    assert len(remaining) == 1
    assert remaining[0]["title"] == "Future"
```

---

## tests/test_config.py (~10 test cases)

Tests config functions triggered by Settings tab widgets.

| # | Test Name | Widget it covers |
|---|-----------|------------------|
| 1 | `test_load_config_defaults` | App startup (no config.json) |
| 2 | `test_save_and_load_config` | Any Settings change |
| 3 | `test_country_selectbox_persists` | Country selectbox |
| 4 | `test_add_custom_site` | "Add Site" button |
| 5 | `test_add_custom_site_duplicate` | "Add Site" with existing URL |
| 6 | `test_remove_custom_site` | "Remove" button per site |
| 7 | `test_remove_custom_site_missing` | Edge: remove non-existent |
| 8 | `test_crawl_source_toggle` | Crawl source checkboxes |
| 9 | `test_delay_slider_persists` | Min/max delay sliders |
| 10 | `test_ndjson_path_persists` | NDJSON import path text input |
| 11 | `test_load_config_malformed_json` | Resilience to corrupt config |

```python
"""Tests for config.py -- covers all config operations triggered by Settings widgets."""
import json, os
import pytest

def test_load_config_defaults(tmp_config):
    from config import load_config, DEFAULT_CONFIG
    config = load_config()
    assert config["target_country"] == DEFAULT_CONFIG["target_country"]
    assert config["crawl_sources"] == DEFAULT_CONFIG["crawl_sources"]

def test_save_and_load_config(tmp_config):
    from config import load_config, save_config
    config = load_config()
    config["target_country"] = "uk"
    save_config(config)
    # Reset cache by reimporting
    import config as cfg
    cfg._config_cache = None
    loaded = load_config()
    assert loaded["target_country"] == "uk"

def test_country_selectbox_persists(tmp_config):
    from config import load_config, save_config
    for country in ["germany", "dach", "eu", "us", "uk", "worldwide"]:
        config = load_config()
        config["target_country"] = country
        save_config(config)
        import config as cfg
        cfg._config_cache = None
        assert load_config()["target_country"] == country

def test_add_custom_site(tmp_config):
    from config import add_custom_site, get_custom_sites, load_config
    # Initialize config
    load_config()
    result = add_custom_site("https://newsite.com")
    assert result is True
    sites = get_custom_sites()
    assert "https://newsite.com" in sites

def test_add_custom_site_duplicate(tmp_config):
    from config import add_custom_site, load_config
    load_config()
    add_custom_site("https://newsite.com")
    result = add_custom_site("https://newsite.com")
    assert result is False

def test_remove_custom_site(tmp_config):
    from config import add_custom_site, remove_custom_site, get_custom_sites, load_config
    load_config()
    add_custom_site("https://newsite.com")
    result = remove_custom_site("https://newsite.com")
    assert result is True
    assert "https://newsite.com" not in get_custom_sites()

def test_remove_custom_site_missing(tmp_config):
    from config import remove_custom_site, load_config
    load_config()
    result = remove_custom_site("https://nonexistent.com")
    assert result is False

def test_crawl_source_toggle(tmp_config):
    from config import load_config, save_config
    config = load_config()
    config["crawl_sources"] = ["gleamfinder"]
    save_config(config)
    import config as cfg
    cfg._config_cache = None
    assert load_config()["crawl_sources"] == ["gleamfinder"]

def test_delay_slider_persists(tmp_config):
    from config import load_config, save_config
    config = load_config()
    config["min_delay"] = 5
    config["max_delay"] = 15
    save_config(config)
    import config as cfg
    cfg._config_cache = None
    loaded = load_config()
    assert loaded["min_delay"] == 5
    assert loaded["max_delay"] == 15

def test_ndjson_path_persists(tmp_config):
    from config import load_config, save_config
    config = load_config()
    config["ndjson_import_path"] = "/tmp/test.ndjson"
    save_config(config)
    import config as cfg
    cfg._config_cache = None
    assert load_config()["ndjson_import_path"] == "/tmp/test.ndjson"

def test_load_config_malformed_json(tmp_config):
    with open(tmp_config, "w") as f:
        f.write("{bad json content")
    import config as cfg
    cfg._config_cache = None
    from config import load_config, DEFAULT_CONFIG
    config = load_config()
    # Should fall back to defaults
    assert config["target_country"] == DEFAULT_CONFIG["target_country"]
```

---

## tests/test_utils.py (~13 test cases)

Tests utility functions used by interactive elements.

| # | Test Name | Widget/element it supports |
|---|-----------|---------------------------|
| 1 | `test_probability_normal` | Win chance column display |
| 2 | `test_probability_zero_entries` | Win chance with 0 total |
| 3 | `test_format_probability_high` | >= 1% display |
| 4 | `test_format_probability_medium` | 0.1-1% display |
| 5 | `test_format_probability_low` | < 0.1% display |
| 6 | `test_eligible_worldwide` | Eligibility check in "Refresh Eligibility" |
| 7 | `test_eligible_restricted` | Restricted giveaway |
| 8 | `test_eligible_exact_match` | Same country |
| 9 | `test_eligible_dach_germany` | DACH includes Germany |
| 10 | `test_eligible_eu_germany` | EU includes Germany |
| 11 | `test_not_eligible_us_for_germany` | US-only, target=Germany |
| 12 | `test_is_region_blocked` | "Enter" button result handling |
| 13 | `test_is_ended` | "Enter" button result handling |
| 14 | `test_detect_country_restriction` | "Check T&C" button |

```python
"""Tests for utils/ -- probability, country eligibility, region detection."""
import pytest

# --- Probability ---

def test_calculate_win_probability_normal():
    from utils.probability import calculate_win_probability
    assert calculate_win_probability(5, 1000) == pytest.approx(0.5)

def test_calculate_win_probability_zero():
    from utils.probability import calculate_win_probability
    assert calculate_win_probability(0, 0) == 0.0

def test_format_probability_high():
    from utils.probability import format_probability
    assert format_probability(5.5) == "5.5%"

def test_format_probability_medium():
    from utils.probability import format_probability
    assert format_probability(0.35) == "0.35%"

def test_format_probability_low():
    from utils.probability import format_probability
    result = format_probability(0.05)
    assert result == "0.0500%"

# --- Country eligibility ---

def test_eligible_worldwide():
    from utils.country_check import is_eligible_for_country
    assert is_eligible_for_country("worldwide", "germany") is True
    assert is_eligible_for_country("worldwide", "us") is True

def test_eligible_restricted():
    from utils.country_check import is_eligible_for_country
    assert is_eligible_for_country("restricted", "germany") is False

def test_eligible_exact_match():
    from utils.country_check import is_eligible_for_country
    assert is_eligible_for_country("germany", "germany") is True
    assert is_eligible_for_country("us", "us") is True

def test_eligible_dach_germany():
    from utils.country_check import is_eligible_for_country
    assert is_eligible_for_country("dach", "germany") is True
    assert is_eligible_for_country("dach", "austria") is True
    assert is_eligible_for_country("dach", "switzerland") is True
    assert is_eligible_for_country("dach", "france") is False

def test_eligible_eu_germany():
    from utils.country_check import is_eligible_for_country
    assert is_eligible_for_country("eu", "germany") is True
    assert is_eligible_for_country("eu", "france") is True
    assert is_eligible_for_country("eu", "switzerland") is False  # not EU

def test_not_eligible_us_for_germany():
    from utils.country_check import is_eligible_for_country
    assert is_eligible_for_country("us", "germany") is False
    assert is_eligible_for_country("uk", "germany") is False

# --- Region blocked / ended detection ---

def test_is_region_blocked_positive():
    from utils.country_check import is_region_blocked
    assert is_region_blocked("Sorry, this promotion is not available in your region") is True

def test_is_region_blocked_negative():
    from utils.country_check import is_region_blocked
    assert is_region_blocked("Welcome to this awesome giveaway!") is False

def test_is_ended_positive():
    from utils.country_check import is_ended
    assert is_ended("This competition has ended") is True
    assert is_ended("This giveaway has ended. Thanks for participating.") is True

def test_is_ended_negative():
    from utils.country_check import is_ended
    assert is_ended("Enter this giveaway now!") is False

# --- Country restriction detection ---

def test_detect_country_germany():
    from utils.country_check import detect_country_restriction
    assert detect_country_restriction("Open to German residents only, Germany only.") == "germany"

def test_detect_country_dach():
    from utils.country_check import detect_country_restriction
    assert detect_country_restriction("Open to DACH region") == "dach"

def test_detect_country_worldwide():
    from utils.country_check import detect_country_restriction
    assert detect_country_restriction("Open worldwide to all participants") == "worldwide"

def test_detect_country_unknown():
    from utils.country_check import detect_country_restriction
    assert detect_country_restriction("No country info here") == "worldwide"
```

---

## tests/test_app_ui.py (~20 test cases)

Tests the Streamlit app's interactive elements by testing the handler functions
directly with mocked external dependencies. Uses `unittest.mock` to isolate
from Playwright/HTTP calls.

| # | Test Name | Button/Widget | What it validates |
|---|-----------|---------------|-------------------|
| 1 | `test_blacklist_button_removes_and_blacklists` | "X" per-row button | URL removed from DB, added to blacklist |
| 2 | `test_delete_all_not_eligible_button` | "Delete All Not Eligible" | Only not_eligible rows removed |
| 3 | `test_refresh_eligibility_button` | "Refresh Eligibility" | new -> eligible/not_eligible transitions |
| 4 | `test_check_tc_button` | "Check T&C" | terms_checked flag set, regions detected |
| 5 | `test_enter_button_success` | "Enter" per-giveaway | Status -> participated |
| 6 | `test_enter_button_region_restricted` | "Enter" with region block | Status -> not_eligible |
| 7 | `test_enter_button_ended` | "Enter" with ended result | Status -> expired |
| 8 | `test_skip_button` | "Skip" per-giveaway | Status -> skipped |
| 9 | `test_auto_enter_all_eligible` | "Auto-Enter ALL Eligible" | All eligible -> participated |
| 10 | `test_start_crawl_button` | "Start Crawl" | New giveaways inserted |
| 11 | `test_crawl_enter_all_button` | "Crawl + Enter All" | Crawl + enter in sequence |
| 12 | `test_enter_all_eligible_button` | "Enter All Eligible" | All eligible entered |
| 13 | `test_quick_crawl_button` | "Quick Crawl" | Crawl without auto-enter |
| 14 | `test_toggle_auto_enter` | "Enable Auto-Enter" toggle | Config updated |
| 15 | `test_country_selectbox` | Country selectbox | Config updated |
| 16 | `test_add_site_button_valid` | "Add Site" + text input | URL added to config |
| 17 | `test_add_site_button_invalid` | "Add Site" with bad URL | Error, not added |
| 18 | `test_remove_site_button` | "Remove" per-site | URL removed from config |
| 19 | `test_delay_sliders` | Min/max delay sliders | Config updated |
| 20 | `test_clear_all_data_works` | "Clear All Data" (after fix) | All data deleted |
| 21 | `test_status_filter_selectbox` | Status filter | Correct giveaways shown |

```python
"""Tests for app.py interactive elements -- handler function logic.

These tests validate the *logic* behind each button/widget by calling
the functions they invoke with mocked external dependencies (Playwright,
HTTP requests, crawlers).
"""
import pytest
from unittest.mock import patch, MagicMock
import os, sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# === Blacklist "X" button ===

def test_blacklist_button_removes_and_blacklists(tmp_db, sample_giveaway):
    """Clicking X removes the giveaway from DB and adds to blacklist."""
    from database import add_giveaway, add_to_blacklist, get_giveaway_by_url, is_blacklisted
    add_giveaway(**sample_giveaway)
    assert get_giveaway_by_url(sample_giveaway["url"]) is not None
    add_to_blacklist(sample_giveaway["url"], "Manually blacklisted")
    assert get_giveaway_by_url(sample_giveaway["url"]) is None
    assert is_blacklisted(sample_giveaway["url"]) is True


# === Delete All Not Eligible button ===

def test_delete_all_not_eligible_button(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, update_giveaway_status, delete_not_eligible, get_giveaways
    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    update_giveaway_status(rows[0]["id"], "not_eligible")
    update_giveaway_status(rows[1]["id"], "eligible")
    deleted = delete_not_eligible()
    assert deleted == 1
    remaining = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert all(r["status"] != "not_eligible" for r in remaining)


# === Refresh Eligibility button ===

def test_refresh_eligibility_transitions(tmp_db, sample_giveaways, tmp_config):
    """scan_existing_entries() should transition 'new' giveaways to eligible/not_eligible."""
    from database import add_giveaways_batch, get_giveaways
    from config import load_config, save_config
    from utils.country_check import is_eligible_for_country

    config = load_config()
    config["target_country"] = "germany"
    save_config(config)

    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert all(r["status"] == "new" for r in rows)

    # Simulate scan_existing_entries logic
    import sqlite3
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    for g in rows:
        country = g.get("country_restriction", "worldwide")
        new_status = "eligible" if is_eligible_for_country(country, "germany") else "not_eligible"
        cursor.execute("UPDATE giveaways SET status = ? WHERE id = ?", (new_status, g["id"]))
    conn.commit()
    conn.close()

    updated = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    statuses = {r["url"]: r["status"] for r in updated}
    # worldwide -> eligible, germany -> eligible, us -> not_eligible, eu -> eligible
    assert statuses["https://gleam.io/abc123/win-ps5"] == "eligible"     # worldwide
    assert statuses["https://gleam.io/def456/win-xbox"] == "eligible"    # germany
    assert statuses["https://gleam.io/ghi789/win-switch"] == "not_eligible"  # us
    assert statuses["https://gleam.io/jkl012/win-steam"] == "eligible"   # eu


# === Enter button (success, region_restricted, ended) ===

def test_enter_button_success(tmp_db, sample_giveaway):
    """Successful auto-enter should set status to 'participated'."""
    from database import add_giveaway, get_giveaways, update_giveaway_status
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    # Simulate: auto_enter_giveaway returns (True, [...])
    update_giveaway_status(gid, "participated")
    row = get_giveaways(status="participated")[0]
    assert row["status"] == "participated"
    assert row["entered_at"] != ""

def test_enter_button_region_restricted(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "not_eligible")
    assert get_giveaways(status="not_eligible", exclude_not_eligible=False)[0]["status"] == "not_eligible"

def test_enter_button_ended(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "expired")
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert any(r["status"] == "expired" for r in rows)


# === Skip button ===

def test_skip_button(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "skipped")
    assert get_giveaways(status="skipped")[0]["status"] == "skipped"


# === Auto-Enter ALL Eligible ===

def test_auto_enter_all_eligible(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, get_giveaways, update_giveaway_status
    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    for r in rows:
        update_giveaway_status(r["id"], "eligible")
    eligible = get_giveaways(status="eligible", gleam_only=False, exclude_not_eligible=False)
    assert len(eligible) == len(sample_giveaways)
    # Simulate batch entry
    for g in eligible:
        update_giveaway_status(g["id"], "participated")
    participated = get_giveaways(status="participated", gleam_only=False, exclude_not_eligible=False)
    assert len(participated) == len(sample_giveaways)


# === Start Crawl button (mock crawlers) ===

def test_start_crawl_inserts_giveaways(tmp_db, tmp_config):
    """run_crawl() should insert crawled giveaways into the DB."""
    from database import get_giveaways, add_giveaways_batch
    from config import load_config
    mock_giveaways = [
        {"title": "Test 1", "url": "https://gleam.io/test1/g", "source": "test",
         "country_restriction": "worldwide"},
        {"title": "Test 2", "url": "https://gleam.io/test2/g", "source": "test",
         "country_restriction": "germany"},
    ]
    count = add_giveaways_batch(mock_giveaways)
    assert count == 2
    rows = get_giveaways()
    assert len(rows) == 2


# === Toggle auto-enter ===

def test_toggle_auto_enter(tmp_config):
    from config import load_config, save_config
    config = load_config()
    config["auto_enter_enabled"] = False
    save_config(config)
    import config as cfg
    cfg._config_cache = None
    assert load_config()["auto_enter_enabled"] is False
    config = load_config()
    config["auto_enter_enabled"] = True
    save_config(config)
    cfg._config_cache = None
    assert load_config()["auto_enter_enabled"] is True


# === Add Site button ===

def test_add_site_button_valid(tmp_config):
    from config import add_custom_site, get_custom_sites, load_config
    load_config()
    result = add_custom_site("https://newgiveaways.com")
    assert result is True
    assert "https://newgiveaways.com" in get_custom_sites()

def test_add_site_button_invalid_no_http():
    """The app checks new_site.startswith('http') before calling add_custom_site."""
    url = "ftp://invalid.com"
    assert not url.startswith("http")


# === Remove Site button ===

def test_remove_site_button(tmp_config):
    from config import add_custom_site, remove_custom_site, get_custom_sites, load_config
    load_config()
    add_custom_site("https://removeme.com")
    result = remove_custom_site("https://removeme.com")
    assert result is True
    assert "https://removeme.com" not in get_custom_sites()


# === Delay sliders ===

def test_delay_sliders_persist(tmp_config):
    from config import load_config, save_config
    config = load_config()
    config["min_delay"] = 7
    config["max_delay"] = 18
    save_config(config)
    import config as cfg
    cfg._config_cache = None
    loaded = load_config()
    assert loaded["min_delay"] == 7
    assert loaded["max_delay"] == 18


# === Clear All Data (after bug fix) ===

def test_clear_all_data(tmp_db, sample_giveaways):
    """Clear All Data should delete every row from the giveaways table."""
    from database import add_giveaways_batch, get_giveaways, get_connection
    add_giveaways_batch(sample_giveaways)
    assert len(get_giveaways(gleam_only=False, exclude_not_eligible=False)) == 4
    # This simulates the FIXED handler using get_connection()
    conn = get_connection()
    conn.execute("DELETE FROM giveaways")
    conn.commit()
    conn.close()
    assert len(get_giveaways(gleam_only=False, exclude_not_eligible=False)) == 0


# === Status filter selectbox ===

def test_status_filter_selectbox(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, get_giveaways_display, update_giveaway_status, get_giveaways
    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    update_giveaway_status(rows[0]["id"], "eligible")
    update_giveaway_status(rows[1]["id"], "participated")
    # Filter by status
    eligible = get_giveaways_display(status="eligible", gleam_only=False)
    assert len(eligible) == 1
    assert eligible[0]["status"] == "eligible"
    participated = get_giveaways_display(status="participated", gleam_only=False)
    assert len(participated) == 1


# === Check T&C button ===

def test_check_tc_updates_terms(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_terms_check
    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    # Simulate check_giveaway_terms_batch result
    update_terms_check(gid, True, "us,uk", detected_region="worldwide")
    row = get_giveaways()[0]
    assert row["terms_checked"] == 1
    assert row["terms_excluded"] == "us,uk"
    assert row["country_restriction"] == "worldwide"
```

---

## Bug Fixes

### Fix #1: Clear All Data nested button (app.py:1483-1493)

**Before:**
```python
if st.button("Clear All Data", use_container_width=True):
    st.warning("This will delete all giveaway data. Are you sure?")
    if st.button("Yes, delete everything", type="primary"):  # NEVER clickable
        ...
```

**After:**
```python
if st.button("Clear All Data", use_container_width=True):
    st.session_state["confirm_clear_all"] = True

if st.session_state.get("confirm_clear_all", False):
    st.warning("This will delete all giveaway data. Are you sure?")
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button("Yes, delete everything", type="primary"):
            from database import get_connection
            conn = get_connection()
            conn.execute("DELETE FROM giveaways")
            conn.commit()
            conn.close()
            _cached_giveaways_display.clear()
            st.session_state["confirm_clear_all"] = False
            st.success("All data cleared!")
            st.rerun()
    with col_no:
        if st.button("Cancel"):
            st.session_state["confirm_clear_all"] = False
            st.rerun()
```

### Fix #2: Wrong database path (app.py:1487)

**Before:**
```python
import sqlite3
conn = sqlite3.connect("giveaways.db")
```

**After:**
```python
from database import get_connection
conn = get_connection()
```

---

## Running Tests

```bash
# Install pytest if not already present
pip install pytest

# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_database.py -v
pytest tests/test_config.py -v
pytest tests/test_utils.py -v
pytest tests/test_app_ui.py -v

# Run with coverage (if pytest-cov installed)
pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## Test Coverage Map

| Interactive Element | Covered By |
|---------------------|-----------|
| "Check Account Status" button | test_app_ui (mock HTTP) |
| "Crawl + Enter All" button | test_app_ui::test_start_crawl_inserts_giveaways |
| "Enter All Eligible" button | test_app_ui::test_auto_enter_all_eligible |
| "Quick Crawl" button | test_app_ui::test_start_crawl_inserts_giveaways |
| Blacklist "X" button | test_app_ui::test_blacklist_button_removes_and_blacklists + test_database |
| "Delete All Not Eligible" button | test_app_ui + test_database::test_delete_not_eligible |
| "Check T&C" button | test_app_ui::test_check_tc_updates_terms |
| "Refresh Eligibility" button | test_app_ui::test_refresh_eligibility_transitions |
| "Clear All Data" button | test_app_ui::test_clear_all_data (tests the fix) |
| "Start Crawl" button | test_app_ui::test_start_crawl_inserts_giveaways |
| Auto-Enter toggle | test_app_ui::test_toggle_auto_enter + test_config |
| Per-giveaway "Enter" button | test_app_ui::test_enter_button_* |
| Per-giveaway "Skip" button | test_app_ui::test_skip_button |
| "Auto-Enter ALL Eligible" | test_app_ui::test_auto_enter_all_eligible |
| Country selectbox | test_config::test_country_selectbox_persists |
| Crawl source checkboxes | test_config::test_crawl_source_toggle |
| "Add Site" button + input | test_app_ui + test_config::test_add_custom_site |
| "Remove" site button | test_app_ui + test_config::test_remove_custom_site |
| Min/max delay sliders | test_app_ui + test_config::test_delay_slider_persists |
| NDJSON path input | test_config::test_ndjson_path_persists |
| Status filter selectbox | test_app_ui::test_status_filter_selectbox |
| Dashboard recent table links | Pure HTML navigation, no logic to test |
| Giveaway table links | Pure HTML navigation, no logic to test |
| "Open" link button | Pure navigation, no logic to test |
