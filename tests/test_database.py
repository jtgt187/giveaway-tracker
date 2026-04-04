"""Tests for database.py -- covers all DB operations triggered by UI buttons.

Covers:
  - init_db (app startup)
  - add_giveaway / add_giveaways_batch (Crawl, Import)
  - get_giveaways / get_giveaways_display (Giveaway table, Status filter selectbox)
  - update_giveaway_status (Enter, Skip buttons)
  - update_giveaway_entries (Auto-enter result)
  - get_giveaway_by_url / get_known_urls (Crawl dedup)
  - update_terms_check (Check T&C button)
  - get_stats (Dashboard stat cards)
  - delete_not_eligible (Delete All Not Eligible button)
  - add_to_blacklist / remove_from_blacklist (Blacklist X button)
  - parse_deadline (Deadline display, countdown)
  - remove_expired_giveaways (Startup cleanup)
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
# get_giveaway_by_url / get_known_urls  (Crawl dedup)
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
