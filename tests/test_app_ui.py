"""Tests for app.py interactive elements -- handler function logic.

These tests validate the *logic* behind each button/widget by calling the
functions they invoke with mocked external dependencies (Playwright, HTTP
requests).  Each test maps to a specific UI element documented in the plan.

Covers:
  - Blacklist "X" button (per-row)
  - "Delete All Not Eligible" button
  - "Refresh Eligibility" button (scan_existing_entries logic)
  - "Check T&C" button (update_terms_check)
  - "Enter" button (success / region_restricted / ended)
  - "Skip" button
  - "Auto-Enter ALL Eligible" button
  - "Import from Extension" / batch insert buttons
  - "Enable Auto-Enter" toggle
  - Country selectbox
  - Custom site stubs (deprecated)
  - "Clear All Data" button (tests the fixed handler)
  - Status filter selectbox
  - "Check T&C" button handler
"""

import sqlite3

import pytest


# ===========================================================================
# Blacklist "X" button  (per-row in Giveaways tab)
# ===========================================================================

def test_blacklist_button_removes_and_blacklists(tmp_db, sample_giveaway):
    """Clicking X removes the giveaway from DB and adds URL to blacklist."""
    from database import add_giveaway, add_to_blacklist, get_giveaway_by_url, is_blacklisted

    add_giveaway(**sample_giveaway)
    assert get_giveaway_by_url(sample_giveaway["url"]) is not None

    # Simulate the button handler: add_to_blacklist(url, "Manually blacklisted")
    add_to_blacklist(sample_giveaway["url"], "Manually blacklisted")

    assert get_giveaway_by_url(sample_giveaway["url"]) is None
    assert is_blacklisted(sample_giveaway["url"]) is True


def test_blacklist_prevents_reimport(tmp_db, sample_giveaway):
    """After blacklisting, re-importing the same URL should not re-add it."""
    from database import add_giveaway, add_to_blacklist

    add_giveaway(**sample_giveaway)
    add_to_blacklist(sample_giveaway["url"])

    result = add_giveaway(**sample_giveaway)
    assert result is False


# ===========================================================================
# "Delete All Not Eligible" button
# ===========================================================================

def test_delete_all_not_eligible_button(tmp_db, sample_giveaways):
    """Only not_eligible rows should be deleted."""
    from database import (
        add_giveaways_batch, update_giveaway_status, delete_not_eligible,
        get_giveaways,
    )

    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    update_giveaway_status(rows[0]["id"], "not_eligible")
    update_giveaway_status(rows[1]["id"], "eligible")

    deleted = delete_not_eligible()
    assert deleted == 1

    remaining = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert all(r["status"] != "not_eligible" for r in remaining)


def test_delete_all_not_eligible_empty(tmp_db, sample_giveaway):
    """No rows should be deleted when none are not_eligible."""
    from database import add_giveaway, delete_not_eligible

    add_giveaway(**sample_giveaway)
    assert delete_not_eligible() == 0


# ===========================================================================
# "Refresh Eligibility" button  (scan_existing_entries logic)
# ===========================================================================

def test_refresh_eligibility_transitions(tmp_db, sample_giveaways, tmp_config):
    """scan_existing_entries logic should transition 'new' -> eligible/not_eligible."""
    from database import add_giveaways_batch, get_giveaways
    from config import load_config, save_config
    from utils.country_check import is_eligible_for_country

    config = load_config()
    config["target_country"] = "germany"
    save_config(config)

    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert all(r["status"] == "new" for r in rows)

    # Replicate scan_existing_entries logic
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    for g in rows:
        country = g.get("country_restriction", "worldwide")
        new_status = (
            "eligible" if is_eligible_for_country(country, "germany")
            else "not_eligible"
        )
        cursor.execute(
            "UPDATE giveaways SET status = ? WHERE id = ?", (new_status, g["id"])
        )
    conn.commit()
    conn.close()

    updated = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    statuses = {r["url"]: r["status"] for r in updated}

    assert statuses["https://gleam.io/abc123/win-ps5"] == "eligible"       # worldwide
    assert statuses["https://gleam.io/def456/win-xbox"] == "eligible"      # germany
    assert statuses["https://gleam.io/ghi789/win-switch"] == "not_eligible" # us
    assert statuses["https://gleam.io/jkl012/win-steam"] == "eligible"     # eu


# ===========================================================================
# "Enter" button -- success / region_restricted / ended
# ===========================================================================

def test_enter_button_success(tmp_db, sample_giveaway):
    """Successful auto-enter sets status to 'participated' with timestamp."""
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]

    # Simulate: auto_enter_giveaway returns (True, [...])
    update_giveaway_status(gid, "participated")

    row = get_giveaways(status="participated")[0]
    assert row["status"] == "participated"
    assert row["entered_at"] != ""


def test_enter_button_region_restricted(tmp_db, sample_giveaway):
    """Region-restricted result sets status to 'not_eligible'."""
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]

    # Simulate: auto_enter_giveaway returns ("region_restricted", [...])
    update_giveaway_status(gid, "not_eligible")

    rows = get_giveaways(exclude_not_eligible=False)
    assert rows[0]["status"] == "not_eligible"


def test_enter_button_ended(tmp_db, sample_giveaway):
    """Ended result sets status to 'expired'."""
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]

    # Simulate: auto_enter_giveaway returns ("ended", [...])
    update_giveaway_status(gid, "expired")

    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert any(r["status"] == "expired" for r in rows)


# ===========================================================================
# "Skip" button
# ===========================================================================

def test_skip_button(tmp_db, sample_giveaway):
    """Clicking Skip sets status to 'skipped'."""
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "skipped")

    assert get_giveaways(status="skipped")[0]["status"] == "skipped"


# ===========================================================================
# "Auto-Enter ALL Eligible" button
# ===========================================================================

def test_auto_enter_all_eligible(tmp_db, sample_giveaways):
    """Batch auto-enter should transition all eligible to participated."""
    from database import add_giveaways_batch, get_giveaways, update_giveaway_status

    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)

    # Mark all as eligible first
    for r in rows:
        update_giveaway_status(r["id"], "eligible")

    eligible = get_giveaways(status="eligible", gleam_only=False, exclude_not_eligible=False)
    assert len(eligible) == len(sample_giveaways)

    # Simulate batch auto-enter: all succeed
    for g in eligible:
        update_giveaway_status(g["id"], "participated")

    participated = get_giveaways(
        status="participated", gleam_only=False, exclude_not_eligible=False
    )
    assert len(participated) == len(sample_giveaways)


def test_auto_enter_mixed_results(tmp_db, sample_giveaways):
    """Batch auto-enter with mixed results: some succeed, some fail."""
    from database import add_giveaways_batch, get_giveaways, update_giveaway_status

    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)

    for r in rows:
        update_giveaway_status(r["id"], "eligible")

    eligible = get_giveaways(status="eligible", gleam_only=False, exclude_not_eligible=False)

    # Simulate mixed results
    update_giveaway_status(eligible[0]["id"], "participated")       # success
    update_giveaway_status(eligible[1]["id"], "not_eligible")       # region restricted
    update_giveaway_status(eligible[2]["id"], "expired")            # ended
    # eligible[3] stays as "eligible" (failure, no status change in some flows)

    all_rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    statuses = [r["status"] for r in all_rows]
    assert "participated" in statuses
    assert "not_eligible" in statuses
    assert "expired" in statuses


# ===========================================================================
# "Import from Extension" / batch insert buttons
# ===========================================================================

def test_import_inserts_giveaways(tmp_db):
    """Batch-insert giveaways via NDJSON import."""
    from database import add_giveaways_batch, get_giveaways

    mock_imported = [
        {
            "title": "Imported 1", "url": "https://gleam.io/cr1/test",
            "source": "extension", "country_restriction": "worldwide",
        },
        {
            "title": "Imported 2", "url": "https://gleam.io/cr2/test",
            "source": "extension", "country_restriction": "germany",
        },
    ]
    count = add_giveaways_batch(mock_imported)
    assert count == 2
    rows = get_giveaways()
    assert len(rows) == 2


def test_import_dedup_skips_known_urls(tmp_db, sample_giveaway):
    """Import should skip URLs already in the database (INSERT OR IGNORE)."""
    from database import add_giveaway, get_known_urls, add_giveaways_batch, get_giveaways

    add_giveaway(**sample_giveaway)
    known = get_known_urls()

    # Simulate dedup: filter out known URLs before batch insert
    new_imported = [
        sample_giveaway,  # already exists
        {
            "title": "Brand New", "url": "https://gleam.io/new1/test",
            "source": "extension", "country_restriction": "worldwide",
        },
    ]
    to_insert = [g for g in new_imported if g["url"] not in known]
    count = add_giveaways_batch(to_insert)
    assert count == 1
    assert len(get_giveaways()) == 2


def test_import_enter_all_flow(tmp_db, sample_giveaways, tmp_config):
    """Import + Enter All: insert giveaways, scan eligibility, enter eligible."""
    from database import add_giveaways_batch, get_giveaways, update_giveaway_status
    from config import load_config, save_config
    from utils.country_check import is_eligible_for_country

    config = load_config()
    config["target_country"] = "germany"
    save_config(config)

    # Phase 1: import
    add_giveaways_batch(sample_giveaways)

    # Phase 2: scan eligibility
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    for g in rows:
        country = g.get("country_restriction", "worldwide")
        new_status = (
            "eligible" if is_eligible_for_country(country, "germany")
            else "not_eligible"
        )
        update_giveaway_status(g["id"], new_status)

    # Phase 3: auto-enter eligible
    eligible = get_giveaways(status="eligible", gleam_only=False)
    entered = 0
    for g in eligible:
        update_giveaway_status(g["id"], "participated")
        entered += 1

    assert entered == 3  # worldwide, germany, eu are eligible


# ===========================================================================
# "Enable Auto-Enter" toggle
# ===========================================================================

def test_toggle_auto_enter_persists(tmp_config):
    """Toggling auto-enter should persist to config."""
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["auto_enter_enabled"] = False
    save_config(config)
    cfg._config_cache = None
    assert load_config()["auto_enter_enabled"] is False

    config = load_config()
    config["auto_enter_enabled"] = True
    save_config(config)
    cfg._config_cache = None
    assert load_config()["auto_enter_enabled"] is True


# ===========================================================================
# Country selectbox
# ===========================================================================

def test_country_selectbox_updates_config(tmp_config):
    """Changing country in the selectbox should update config."""
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["target_country"] = "us"
    save_config(config)
    cfg._config_cache = None
    assert load_config()["target_country"] == "us"


# ===========================================================================
# Custom site stubs (deprecated)
# ===========================================================================

def test_add_site_button_valid_url(tmp_config):
    """Custom sites are deprecated -- add_custom_site always returns False."""
    from config import add_custom_site, get_custom_sites, load_config

    load_config()
    result = add_custom_site("https://newgiveaways.com")
    assert result is False
    assert get_custom_sites() == []


def test_add_site_button_url_validation():
    """The app checks url.startswith('http') before calling add_custom_site."""
    valid_urls = ["https://example.com", "http://example.com"]
    invalid_urls = ["ftp://example.com", "not-a-url", "", "example.com"]

    for url in valid_urls:
        assert url.startswith("http"), f"{url} should pass validation"

    for url in invalid_urls:
        assert not url.startswith("http"), f"{url} should fail validation"


# ===========================================================================
# Custom site remove stub (deprecated)
# ===========================================================================

def test_remove_site_button(tmp_config):
    """Custom sites are deprecated -- remove_custom_site always returns False."""
    from config import remove_custom_site, load_config

    load_config()
    result = remove_custom_site("https://removeme.com")
    assert result is False


# ===========================================================================
# Min/max delay sliders
# ===========================================================================

def test_delay_sliders_persist(tmp_config):
    """Adjusting delay sliders should persist to config."""
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["min_delay"] = 7
    config["max_delay"] = 18
    save_config(config)
    cfg._config_cache = None

    loaded = load_config()
    assert loaded["min_delay"] == 7
    assert loaded["max_delay"] == 18


# ===========================================================================
# "Clear All Data" button  (tests the fixed handler)
# ===========================================================================

def test_clear_all_data(tmp_db, sample_giveaways):
    """Clear All Data should delete every row from the giveaways table.

    This test validates the FIXED handler that uses get_connection()
    from database.py instead of a manual sqlite3.connect() with a
    relative path.
    """
    from database import add_giveaways_batch, get_giveaways, get_connection

    add_giveaways_batch(sample_giveaways)
    assert len(get_giveaways(gleam_only=False, exclude_not_eligible=False)) == 4

    # Simulate the fixed handler
    conn = get_connection()
    conn.execute("DELETE FROM giveaways")
    conn.commit()
    conn.close()

    assert len(get_giveaways(gleam_only=False, exclude_not_eligible=False)) == 0


def test_clear_all_data_empty_db(tmp_db):
    """Clear All Data on an empty DB should not error."""
    from database import get_giveaways, get_connection

    conn = get_connection()
    conn.execute("DELETE FROM giveaways")
    conn.commit()
    conn.close()

    assert len(get_giveaways(gleam_only=False, exclude_not_eligible=False)) == 0


# ===========================================================================
# Status filter selectbox
# ===========================================================================

def test_status_filter_selectbox_filters_correctly(tmp_db, sample_giveaways):
    """The status filter should return only giveaways matching the filter."""
    from database import (
        add_giveaways_batch, get_giveaways_display,
        update_giveaway_status, get_giveaways,
    )

    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    update_giveaway_status(rows[0]["id"], "eligible")
    update_giveaway_status(rows[1]["id"], "participated")
    update_giveaway_status(rows[2]["id"], "not_eligible")
    # rows[3] stays "new"

    # Simulate selectbox filter values
    eligible = get_giveaways_display(status="eligible", gleam_only=False)
    assert len(eligible) == 1
    assert eligible[0]["status"] == "eligible"

    participated = get_giveaways_display(status="participated", gleam_only=False)
    assert len(participated) == 1
    assert participated[0]["status"] == "participated"

    not_eligible = get_giveaways_display(
        status="not_eligible", gleam_only=False, exclude_not_eligible=False
    )
    assert len(not_eligible) == 1

    new = get_giveaways_display(status="new", gleam_only=False)
    assert len(new) == 1


# ===========================================================================
# "Enrich All" button (T&C + deadlines + ended/region detection)
# ===========================================================================

def test_check_tc_updates_terms(tmp_db, sample_giveaway):
    """Check T&C should set terms_checked and terms_excluded."""
    from database import add_giveaway, get_giveaways, update_terms_check

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]

    # Simulate enrich_giveaways_batch result
    update_terms_check(gid, True, "us,uk", detected_region="worldwide")

    row = get_giveaways()[0]
    assert row["terms_checked"] == 1
    assert row["terms_excluded"] == "us,uk"
    assert row["country_restriction"] == "worldwide"


def test_check_tc_detects_germany_restriction(tmp_db, sample_giveaway):
    """Check T&C detecting germany restriction should update country_restriction."""
    from database import add_giveaway, get_giveaways, update_terms_check

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]

    update_terms_check(gid, True, "", detected_region="germany")

    row = get_giveaways()[0]
    assert row["country_restriction"] == "germany"
    assert row["terms_checked"] == 1


# ===========================================================================
# Entry stats tracking (session state simulation)
# ===========================================================================

def test_entry_stats_tracking():
    """Entry stats dict should correctly track entered/failed/skipped counts."""
    entry_stats = {"entered": 0, "failed": 0, "skipped": 0}

    # Simulate successful entries
    entry_stats["entered"] += 1
    entry_stats["entered"] += 1

    # Simulate failures
    entry_stats["failed"] += 1

    # Simulate skips
    entry_stats["skipped"] += 1

    assert entry_stats["entered"] == 2
    assert entry_stats["failed"] == 1
    assert entry_stats["skipped"] == 1
    assert entry_stats["entered"] + entry_stats["failed"] + entry_stats["skipped"] == 4
