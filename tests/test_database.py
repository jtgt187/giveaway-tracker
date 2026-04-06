"""Tests for database.py -- covers all DB operations triggered by UI buttons.

Covers:
  - init_db (app startup)
  - add_giveaway / add_giveaways_batch (Import)
  - get_giveaways / get_giveaways_display (Giveaway table, Status filter selectbox)
  - update_giveaway_status (Enter, Skip buttons)
  - update_giveaway_entries (Auto-enter result)
  - get_giveaway_by_url / get_known_urls (Import dedup)
  - update_terms_check (Check T&C button)
  - get_stats (Dashboard stat cards)
  - delete_not_eligible (Delete All Not Eligible button)
  - add_to_blacklist / remove_from_blacklist / get_blacklist (Blacklist X button)
  - parse_deadline (Deadline display, countdown)
  - remove_expired_giveaways (Startup cleanup)
  - get_connection (row_factory verification)
  - mark_duplicate_or_skip (wrapper)
  - gleam_only / exclude_not_eligible filter edge cases
"""

import sqlite3

import pytest


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_db_creates_tables(tmp_db):
    conn = sqlite3.connect(tmp_db)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='giveaways'"
    )
    assert cursor.fetchone() is not None
    conn.close()


def test_init_db_creates_indexes(tmp_db):
    conn = sqlite3.connect(tmp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
    index_names = {row[0] for row in cursor.fetchall()}
    conn.close()
    assert "idx_giveaways_status" in index_names
    assert "idx_giveaways_discovered" in index_names
    assert "idx_giveaways_deadline" in index_names


# ---------------------------------------------------------------------------
# add_giveaway
# ---------------------------------------------------------------------------

def test_add_giveaway_inserts(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways

    result = add_giveaway(**sample_giveaway)
    assert result is True
    rows = get_giveaways()
    assert len(rows) == 1
    assert rows[0]["title"] == sample_giveaway["title"]
    assert rows[0]["url"] == sample_giveaway["url"]
    assert rows[0]["status"] == "new"


def test_add_giveaway_duplicate_ignored(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways

    add_giveaway(**sample_giveaway)
    result = add_giveaway(**sample_giveaway)
    assert result is False
    assert len(get_giveaways()) == 1


def test_add_giveaway_blacklisted_rejected(tmp_db, sample_giveaway):
    from database import add_giveaway, add_to_blacklist

    add_to_blacklist(sample_giveaway["url"])
    result = add_giveaway(**sample_giveaway)
    assert result is False


# ---------------------------------------------------------------------------
# add_giveaways_batch
# ---------------------------------------------------------------------------

def test_add_giveaways_batch(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, get_giveaways

    count = add_giveaways_batch(sample_giveaways)
    assert count == len(sample_giveaways)
    rows = get_giveaways(gleam_only=False)
    assert len(rows) == len(sample_giveaways)


def test_add_giveaways_batch_empty(tmp_db):
    from database import add_giveaways_batch

    assert add_giveaways_batch([]) == 0


def test_add_giveaways_batch_skips_blacklisted(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, add_to_blacklist, get_giveaways

    add_to_blacklist(sample_giveaways[0]["url"])
    count = add_giveaways_batch(sample_giveaways)
    assert count == len(sample_giveaways) - 1
    urls = {r["url"] for r in get_giveaways(gleam_only=False)}
    assert sample_giveaways[0]["url"] not in urls


# ---------------------------------------------------------------------------
# get_giveaways / get_giveaways_display  (Status filter selectbox)
# ---------------------------------------------------------------------------

def test_get_giveaways_by_status(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "eligible")

    assert len(get_giveaways(status="eligible")) == 1
    assert len(get_giveaways(status="new")) == 0


def test_get_giveaways_display_returns_expected_columns(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways_display

    add_giveaway(**sample_giveaway)
    rows = get_giveaways_display()
    assert len(rows) == 1
    expected_cols = {
        "id", "title", "url", "status", "win_probability",
        "total_entries", "deadline", "country_restriction",
        "terms_checked", "terms_excluded", "discovered_at",
    }
    assert set(rows[0].keys()) == expected_cols


def test_get_giveaways_display_status_filter(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, update_giveaway_status, get_giveaways, get_giveaways_display

    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    update_giveaway_status(rows[0]["id"], "eligible")
    update_giveaway_status(rows[1]["id"], "participated")

    eligible = get_giveaways_display(status="eligible", gleam_only=False)
    assert len(eligible) == 1
    assert eligible[0]["status"] == "eligible"

    participated = get_giveaways_display(status="participated", gleam_only=False)
    assert len(participated) == 1
    assert participated[0]["status"] == "participated"


# ---------------------------------------------------------------------------
# update_giveaway_status  (Enter, Skip buttons)
# ---------------------------------------------------------------------------

def test_update_giveaway_status_participated(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "participated", "entered via auto-enter")

    row = get_giveaways(status="participated")[0]
    assert row["status"] == "participated"
    assert row["notes"] == "entered via auto-enter"
    assert row["entered_at"] != ""


def test_update_giveaway_status_skipped(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "skipped")

    row = get_giveaways(status="skipped")[0]
    assert row["status"] == "skipped"


def test_update_giveaway_status_expired(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "expired")

    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert any(r["status"] == "expired" for r in rows)


def test_update_giveaway_status_not_eligible(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "not_eligible")

    rows = get_giveaways(exclude_not_eligible=False)
    assert rows[0]["status"] == "not_eligible"


# ---------------------------------------------------------------------------
# update_giveaway_entries  (Auto-enter result)
# ---------------------------------------------------------------------------

def test_update_giveaway_entries(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, update_giveaway_entries

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_entries(gid, total_entries=1000, your_entries=5)

    row = get_giveaways()[0]
    assert row["total_entries"] == 1000
    assert row["your_entries"] == 5
    assert row["win_probability"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# get_giveaway_by_url / get_known_urls  (Import dedup)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# update_terms_check  (Check T&C button)
# ---------------------------------------------------------------------------

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
    assert row["terms_checked"] == 1


# ---------------------------------------------------------------------------
# get_stats  (Dashboard stat cards)
# ---------------------------------------------------------------------------

def test_get_stats(tmp_db, sample_giveaways):
    from database import add_giveaways_batch, get_stats, update_giveaway_status, get_giveaways

    add_giveaways_batch(sample_giveaways)
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    update_giveaway_status(rows[0]["id"], "participated")
    update_giveaway_status(rows[1]["id"], "eligible")
    update_giveaway_status(rows[2]["id"], "not_eligible")
    # rows[3] stays "new"

    stats = get_stats(gleam_only=False)
    assert stats["total"] == 4
    assert stats["participated"] == 1
    assert stats["eligible"] == 1
    assert stats["not_eligible"] == 1
    assert stats["new"] == 1


def test_get_stats_empty_db(tmp_db):
    from database import get_stats

    stats = get_stats()
    assert stats["total"] == 0
    assert stats["participated"] == 0
    assert stats["avg_win_probability"] == 0


# ---------------------------------------------------------------------------
# delete_not_eligible  (Delete All Not Eligible button)
# ---------------------------------------------------------------------------

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


def test_delete_not_eligible_no_rows(tmp_db, sample_giveaway):
    from database import add_giveaway, delete_not_eligible

    add_giveaway(**sample_giveaway)
    deleted = delete_not_eligible()
    assert deleted == 0


# ---------------------------------------------------------------------------
# Blacklist  (Blacklist X button)
# ---------------------------------------------------------------------------

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


def test_blacklist_prevents_future_inserts(tmp_db, sample_giveaway):
    from database import add_to_blacklist, add_giveaway

    add_to_blacklist(sample_giveaway["url"])
    result = add_giveaway(**sample_giveaway)
    assert result is False


# ---------------------------------------------------------------------------
# parse_deadline  (Deadline display / countdown)
# ---------------------------------------------------------------------------

def test_parse_deadline_full_format():
    from database import parse_deadline

    dt = parse_deadline("Friday 03 April 2026 at 22:59:59")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 3
    assert dt.hour == 22
    assert dt.minute == 59


def test_parse_deadline_no_day_name():
    from database import parse_deadline

    dt = parse_deadline("03 April 2026 at 22:59:59")
    assert dt is not None
    assert dt.year == 2026


def test_parse_deadline_date_only():
    from database import parse_deadline

    dt = parse_deadline("03 April 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 3


def test_parse_deadline_empty():
    from database import parse_deadline

    assert parse_deadline("") is None
    assert parse_deadline(None) is None
    assert parse_deadline("   ") is None


def test_parse_deadline_garbage():
    from database import parse_deadline

    assert parse_deadline("not a date at all") is None


# ---------------------------------------------------------------------------
# remove_expired_giveaways  (Startup cleanup)
# ---------------------------------------------------------------------------

def test_remove_expired_giveaways(tmp_db):
    from database import add_giveaway, remove_expired_giveaways, get_giveaways

    add_giveaway(
        "Expired", "https://gleam.io/expired1/test", "test",
        deadline="Friday 01 January 2021 at 00:00:00",
    )
    add_giveaway(
        "Future", "https://gleam.io/future1/test", "test",
        deadline="Friday 01 January 2030 at 00:00:00",
    )

    removed = remove_expired_giveaways()
    assert removed == 1

    remaining = get_giveaways()
    assert len(remaining) == 1
    assert remaining[0]["title"] == "Future"


def test_remove_expired_giveaways_none_expired(tmp_db, sample_giveaway):
    from database import add_giveaway, remove_expired_giveaways

    add_giveaway(**sample_giveaway)
    removed = remove_expired_giveaways()
    assert removed == 0


def test_remove_expired_giveaways_no_deadline_kept(tmp_db):
    """Giveaways with empty deadline should never be removed."""
    from database import add_giveaway, remove_expired_giveaways, get_giveaways

    add_giveaway("No Deadline", "https://gleam.io/nd/test", "test", deadline="")
    removed = remove_expired_giveaways()
    assert removed == 0
    assert len(get_giveaways()) == 1


# ---------------------------------------------------------------------------
# get_connection  (row_factory verification)
# ---------------------------------------------------------------------------

def test_get_connection_row_factory(tmp_db):
    import sqlite3
    from database import get_connection

    conn = get_connection()
    assert conn.row_factory is sqlite3.Row
    conn.close()


# ---------------------------------------------------------------------------
# get_blacklist
# ---------------------------------------------------------------------------

def test_get_blacklist(tmp_db):
    from database import add_to_blacklist, get_blacklist

    add_to_blacklist("https://gleam.io/bl1/test")
    add_to_blacklist("https://gleam.io/bl2/test")

    bl = get_blacklist()
    assert isinstance(bl, list)
    assert len(bl) == 2
    assert "https://gleam.io/bl1/test" in bl
    assert "https://gleam.io/bl2/test" in bl


def test_get_blacklist_empty(tmp_db):
    from database import get_blacklist

    bl = get_blacklist()
    assert bl == []


# ---------------------------------------------------------------------------
# mark_duplicate_or_skip
# ---------------------------------------------------------------------------

def test_mark_duplicate_or_skip(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, mark_duplicate_or_skip

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    mark_duplicate_or_skip(gid, "duplicate found")

    row = get_giveaways(status="skipped")[0]
    assert row["status"] == "skipped"
    assert row["notes"] == "duplicate found"


def test_mark_duplicate_or_skip_no_reason(tmp_db, sample_giveaway):
    from database import add_giveaway, get_giveaways, mark_duplicate_or_skip

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    mark_duplicate_or_skip(gid)

    row = get_giveaways(status="skipped")[0]
    assert row["status"] == "skipped"
    assert row["notes"] == ""


# ---------------------------------------------------------------------------
# add_giveaways_batch -- edge cases
# ---------------------------------------------------------------------------

def test_add_giveaways_batch_empty_url_skipped(tmp_db):
    """A giveaway dict with url='' should be silently skipped."""
    from database import add_giveaways_batch, get_giveaways

    batch = [
        {"title": "No URL", "url": "", "source": "test"},
        {"title": "Has URL", "url": "https://gleam.io/has/url", "source": "test"},
    ]
    count = add_giveaways_batch(batch)
    assert count == 1
    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert len(rows) == 1
    assert rows[0]["title"] == "Has URL"


def test_add_giveaways_batch_missing_url_key_skipped(tmp_db):
    """A giveaway dict without a 'url' key should be skipped."""
    from database import add_giveaways_batch, get_giveaways

    batch = [
        {"title": "Missing URL key", "source": "test"},
    ]
    count = add_giveaways_batch(batch)
    assert count == 0


def test_add_giveaways_batch_defaults(tmp_db):
    """Batch insert should apply defaults for missing optional fields."""
    from database import add_giveaways_batch, get_giveaways

    batch = [{"url": "https://gleam.io/min/test"}]  # minimal dict
    count = add_giveaways_batch(batch)
    assert count == 1
    row = get_giveaways(gleam_only=False, exclude_not_eligible=False)[0]
    assert row["title"] == ""
    assert row["source"] == ""
    assert row["country_restriction"] == "worldwide"


# ---------------------------------------------------------------------------
# add_giveaway -- optional params at insert time
# ---------------------------------------------------------------------------

def test_add_giveaway_with_terms_fields(tmp_db):
    """terms_checked and terms_excluded should be settable at insert time."""
    from database import add_giveaway, get_giveaways

    add_giveaway(
        "Terms Test", "https://gleam.io/terms/test", "test",
        terms_checked=True, terms_excluded="us,uk",
    )
    row = get_giveaways()[0]
    assert row["terms_checked"] == 1
    assert row["terms_excluded"] == "us,uk"


# ---------------------------------------------------------------------------
# get_giveaways -- gleam_only and exclude_not_eligible edge cases
# ---------------------------------------------------------------------------

def test_get_giveaways_gleam_only_default(tmp_db):
    """Default gleam_only=True should filter out non-gleam URLs."""
    from database import add_giveaway, get_giveaways

    add_giveaway("Gleam", "https://gleam.io/g1/test", "test")
    add_giveaway("Other", "https://example.com/giveaway", "test")

    gleam_rows = get_giveaways(gleam_only=True)
    assert len(gleam_rows) == 1
    assert "gleam.io" in gleam_rows[0]["url"]

    all_rows = get_giveaways(gleam_only=False)
    assert len(all_rows) == 2


def test_get_giveaways_exclude_not_eligible_bypassed_with_status(tmp_db, sample_giveaway):
    """When status= is set, exclude_not_eligible should be bypassed."""
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "not_eligible")

    # With status='not_eligible', exclude_not_eligible is bypassed
    rows = get_giveaways(status="not_eligible")
    assert len(rows) == 1
    assert rows[0]["status"] == "not_eligible"


def test_get_giveaways_exclude_not_eligible_default(tmp_db, sample_giveaway):
    """Default exclude_not_eligible=True should hide not_eligible rows."""
    from database import add_giveaway, get_giveaways, update_giveaway_status

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_status(gid, "not_eligible")

    # Default: not_eligible excluded
    rows = get_giveaways()
    assert len(rows) == 0

    # Explicit: not_eligible included
    rows = get_giveaways(exclude_not_eligible=False)
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# update_giveaway_entries -- edge cases
# ---------------------------------------------------------------------------

def test_update_giveaway_entries_zero_total(tmp_db, sample_giveaway):
    """Zero total_entries should result in 0.0 probability."""
    from database import add_giveaway, get_giveaways, update_giveaway_entries

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_entries(gid, total_entries=0, your_entries=0)

    row = get_giveaways()[0]
    assert row["win_probability"] == 0.0


def test_update_giveaway_entries_zero_your_entries(tmp_db, sample_giveaway):
    """Zero your_entries should result in 0.0 probability."""
    from database import add_giveaway, get_giveaways, update_giveaway_entries

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    update_giveaway_entries(gid, total_entries=1000, your_entries=0)

    row = get_giveaways()[0]
    assert row["win_probability"] == 0.0


# ---------------------------------------------------------------------------
# update_terms_check -- edge cases
# ---------------------------------------------------------------------------

def test_update_terms_check_no_region(tmp_db, sample_giveaway):
    """When detected_region is None, country_restriction should not change."""
    from database import add_giveaway, get_giveaways, update_terms_check

    add_giveaway(**sample_giveaway)
    gid = get_giveaways()[0]["id"]
    original_country = get_giveaways()[0]["country_restriction"]

    update_terms_check(gid, True, "us", detected_region=None)

    row = get_giveaways()[0]
    assert row["terms_checked"] == 1
    assert row["terms_excluded"] == "us"
    assert row["country_restriction"] == original_country


# ---------------------------------------------------------------------------
# get_stats -- gleam_only parameter
# ---------------------------------------------------------------------------

def test_get_stats_gleam_only_filters(tmp_db):
    """get_stats with gleam_only should only count gleam URLs."""
    from database import add_giveaway, get_stats

    add_giveaway("Gleam", "https://gleam.io/s1/test", "test")
    add_giveaway("Other", "https://example.com/giveaway", "test")

    gleam_stats = get_stats(gleam_only=True)
    assert gleam_stats["total"] == 1

    all_stats = get_stats(gleam_only=False)
    assert all_stats["total"] == 2


# ---------------------------------------------------------------------------
# title_from_url_slug  (Title extraction from URL)
# ---------------------------------------------------------------------------

def test_title_from_url_slug_basic():
    from database import title_from_url_slug

    result = title_from_url_slug("https://gleam.io/jyldJ/aoc-easter-hunt-giveaway")
    assert result == "Aoc Easter Hunt Giveaway"


def test_title_from_url_slug_simple():
    from database import title_from_url_slug

    result = title_from_url_slug("https://gleam.io/abc/win-stuff")
    assert result == "Win Stuff"


def test_title_from_url_slug_single_word():
    from database import title_from_url_slug

    result = title_from_url_slug("https://gleam.io/abc/giveaway")
    assert result == "Giveaway"


def test_title_from_url_slug_no_slug():
    """URL with only an ID (no slug) should return empty string."""
    from database import title_from_url_slug

    result = title_from_url_slug("https://gleam.io/abc123")
    assert result == ""


def test_title_from_url_slug_giveaways_path():
    """URLs like /giveaways/<id> should extract from last path segment."""
    from database import title_from_url_slug

    result = title_from_url_slug("https://gleam.io/giveaways/wyzeg")
    # "wyzeg" is a short alphanumeric ID, should return empty
    assert result == ""


def test_title_from_url_slug_empty():
    from database import title_from_url_slug

    assert title_from_url_slug("") == ""
    assert title_from_url_slug("not-a-url") == ""


def test_title_from_url_slug_real_examples():
    """Test with real gleam.io URLs from the database."""
    from database import title_from_url_slug

    assert title_from_url_slug("https://gleam.io/qzO90/cubot-easters-day-giveaway") == "Cubot Easters Day Giveaway"
    assert title_from_url_slug("https://gleam.io/lFR5N/logitech-g-laystation-giveaway") == "Logitech G Laystation Giveaway"
    assert title_from_url_slug("https://gleam.io/oAibF/the-ballin-backyard-giveaway-presented-by-solo-stove") == "The Ballin Backyard Giveaway Presented By Solo Stove"


# ---------------------------------------------------------------------------
# clean_title  (Title cleanup)
# ---------------------------------------------------------------------------

def test_clean_title_strips_trailing_new():
    from database import clean_title

    assert clean_title("Logitech G LAYSTATION GiveawayNew") == "Logitech G LAYSTATION Giveaway"
    assert clean_title("Milwaukee Film FestivalNew") == "Milwaukee Film Festival"


def test_clean_title_preserves_normal_title():
    from database import clean_title

    assert clean_title("Win a PlayStation 5") == "Win a PlayStation 5"
    assert clean_title("AMD x Echo Guild: RWF Sweepstakes") == "AMD x Echo Guild: RWF Sweepstakes"


def test_clean_title_raw_url_becomes_slug():
    from database import clean_title

    result = clean_title("https://gleam.io/abc/win-cool-stuff")
    assert result == "Win Cool Stuff"


def test_clean_title_empty_uses_url_slug():
    from database import clean_title

    result = clean_title("", "https://gleam.io/abc/aoc-easter-hunt-giveaway")
    assert result == "Aoc Easter Hunt Giveaway"


def test_clean_title_long_snippet_uses_slug():
    from database import clean_title

    long_text = "This is a very long snippet of text from a search engine result that describes the giveaway in detail but is not actually the title of the giveaway itself lorem ipsum"
    result = clean_title(long_text, "https://gleam.io/abc/cool-giveaway")
    assert result == "Cool Giveaway"


def test_clean_title_none_with_url():
    from database import clean_title

    result = clean_title(None, "https://gleam.io/abc/some-giveaway")
    assert result == "Some Giveaway"


def test_clean_title_none_without_url():
    from database import clean_title

    result = clean_title(None)
    assert result == ""


def test_clean_title_new_only_short():
    """Title 'New' alone (4 chars) should not be stripped (guard against over-stripping)."""
    from database import clean_title

    assert clean_title("New") == "New"


# ---------------------------------------------------------------------------
# parse_deadline  -- expanded formats
# ---------------------------------------------------------------------------

def test_parse_deadline_us_full_month():
    from database import parse_deadline

    dt = parse_deadline("April 17, 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 17


def test_parse_deadline_us_abbreviated_month():
    from database import parse_deadline

    dt = parse_deadline("Apr 17, 2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 17


def test_parse_deadline_us_12_hour():
    from database import parse_deadline

    dt = parse_deadline("April 17, 2026 11:59 PM")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 17
    assert dt.hour == 23
    assert dt.minute == 59


def test_parse_deadline_us_with_at():
    from database import parse_deadline

    dt = parse_deadline("April 17, 2026 at 23:59:59")
    assert dt is not None
    assert dt.year == 2026
    assert dt.hour == 23
    assert dt.minute == 59
    assert dt.second == 59


def test_parse_deadline_iso8601():
    from database import parse_deadline

    dt = parse_deadline("2026-04-17T23:59:59")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 17
    assert dt.hour == 23


def test_parse_deadline_iso8601_date_only():
    from database import parse_deadline

    dt = parse_deadline("2026-04-17")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 17


def test_parse_deadline_iso8601_space():
    from database import parse_deadline

    dt = parse_deadline("2026-04-17 23:59:59")
    assert dt is not None
    assert dt.year == 2026
    assert dt.hour == 23


def test_parse_deadline_slash_dd_mm_yyyy():
    from database import parse_deadline

    dt = parse_deadline("17/04/2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 17


def test_parse_deadline_slash_mm_dd_yyyy():
    """When first number <= 12 and second > 12, treat as MM/DD/YYYY."""
    from database import parse_deadline

    dt = parse_deadline("04/17/2026")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 4
    assert dt.day == 17


def test_parse_deadline_countdown_days():
    """Relative countdown like '11 days' should produce a future datetime."""
    from database import parse_deadline
    from datetime import datetime, timedelta

    dt = parse_deadline("11 days")
    assert dt is not None
    # Should be roughly 11 days from now
    expected = datetime.now() + timedelta(days=11)
    diff = abs((dt - expected).total_seconds())
    assert diff < 5  # within 5 seconds tolerance


def test_parse_deadline_countdown_compact():
    """Compact countdown like '2d 3h' should produce a future datetime."""
    from database import parse_deadline
    from datetime import datetime, timedelta

    dt = parse_deadline("2d 3h")
    assert dt is not None
    expected = datetime.now() + timedelta(days=2, hours=3)
    diff = abs((dt - expected).total_seconds())
    assert diff < 5


def test_parse_deadline_countdown_full():
    """Full countdown like '5 days 12 hours 30 minutes' should work."""
    from database import parse_deadline
    from datetime import datetime, timedelta

    dt = parse_deadline("5 days 12 hours 30 minutes")
    assert dt is not None
    expected = datetime.now() + timedelta(days=5, hours=12, minutes=30)
    diff = abs((dt - expected).total_seconds())
    assert diff < 5


def test_parse_deadline_countdown_ends_in():
    """Countdown with 'Ends in' prefix should work."""
    from database import parse_deadline
    from datetime import datetime, timedelta

    dt = parse_deadline("Ends in 3 days")
    assert dt is not None
    expected = datetime.now() + timedelta(days=3)
    diff = abs((dt - expected).total_seconds())
    assert diff < 5


def test_parse_deadline_countdown_zero_returns_none():
    """A countdown with no recognized time units should return None."""
    from database import parse_deadline

    assert parse_deadline("0d 0h 0m") is None


def test_parse_deadline_abbrev_month_12_hour():
    from database import parse_deadline

    dt = parse_deadline("Apr 17, 2026 11:59 PM")
    assert dt is not None
    assert dt.hour == 23
    assert dt.minute == 59


def test_parse_deadline_with_at_no_seconds():
    from database import parse_deadline

    dt = parse_deadline("03 April 2026 at 22:59")
    assert dt is not None
    assert dt.hour == 22
    assert dt.minute == 59


# ---------------------------------------------------------------------------
# cleanup_titles  (One-time title fix)
# ---------------------------------------------------------------------------

def test_cleanup_titles_fixes_trailing_new(tmp_db):
    from database import add_giveaway, get_giveaways, cleanup_titles

    add_giveaway("Awesome GiveawayNew", "https://gleam.io/abc/awesome-giveaway", "test")
    updated = cleanup_titles()
    assert updated == 1

    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert rows[0]["title"] == "Awesome Giveaway"


def test_cleanup_titles_preserves_good_titles(tmp_db):
    from database import add_giveaway, cleanup_titles

    add_giveaway("Win a PS5", "https://gleam.io/abc/win-ps5", "test")
    updated = cleanup_titles()
    assert updated == 0


def test_cleanup_titles_fixes_url_titles(tmp_db):
    from database import add_giveaway, get_giveaways, cleanup_titles

    add_giveaway("https://gleam.io/abc/cool-giveaway", "https://gleam.io/abc/cool-giveaway", "test")
    updated = cleanup_titles()
    assert updated == 1

    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert rows[0]["title"] == "Cool Giveaway"


# ---------------------------------------------------------------------------
# remove_non_gleam_giveaways  (Cleanup non-gleam URLs)
# ---------------------------------------------------------------------------

def test_remove_non_gleam_giveaways(tmp_db):
    from database import add_giveaway, get_giveaways, remove_non_gleam_giveaways

    add_giveaway("Gleam", "https://gleam.io/abc/test", "test")
    add_giveaway("Other", "https://giveawaydrop.com/test", "test")
    add_giveaway("Another", "https://example.com/giveaway", "test")

    removed = remove_non_gleam_giveaways()
    assert removed == 2

    rows = get_giveaways(gleam_only=False, exclude_not_eligible=False)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://gleam.io/abc/test"


def test_remove_non_gleam_giveaways_none_to_remove(tmp_db):
    from database import add_giveaway, remove_non_gleam_giveaways

    add_giveaway("Gleam", "https://gleam.io/abc/test", "test")
    removed = remove_non_gleam_giveaways()
    assert removed == 0
