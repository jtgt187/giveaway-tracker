import sqlite3
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

DB_PATH = os.path.join(os.path.dirname(__file__), "giveaways.db")

# In-memory blacklist cache to avoid reading the file on every add_giveaway() call
_blacklist_cache = None


# ---------------------------------------------------------------------------
# Title extraction & cleanup
# ---------------------------------------------------------------------------

def title_from_url_slug(url):
    """Extract a clean, human-readable title from a Gleam URL slug.

    Examples:
        "https://gleam.io/jyldJ/aoc-easter-hunt-giveaway"
            -> "AOC Easter Hunt Giveaway"
        "https://gleam.io/abc/win-stuff"
            -> "Win Stuff"

    Returns an empty string if no slug can be extracted.
    """
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        # Gleam URLs: /<id>/<slug>  or /giveaways/<id>
        if len(parts) >= 2:
            slug = parts[-1]
        else:
            return ""
        # Skip if the slug looks like an ID (all alphanumeric, short)
        if re.fullmatch(r"[A-Za-z0-9]{3,7}", slug):
            return ""
        # Convert slug to title: replace hyphens with spaces, title-case
        title = slug.replace("-", " ").strip()
        if not title:
            return ""
        return title.title()
    except Exception:
        return ""


def clean_title(title, url=""):
    """Clean up a giveaway title, removing noise from scraped link text.

    Fixes:
        - Trailing "New" badge from listing sites (e.g. "Giveaway XNew" -> "Giveaway X")
        - Leading/trailing whitespace
        - Titles that are just a raw URL -> extract slug title instead
        - Excessively long snippet text (> 120 chars) -> use slug title

    Returns the cleaned title, or a slug-derived title as fallback.
    """
    if not title:
        return title_from_url_slug(url) if url else ""

    title = title.strip()

    # If title is a raw URL, use slug instead
    if title.startswith("http://") or title.startswith("https://"):
        return title_from_url_slug(title) or title_from_url_slug(url) or title

    # Strip trailing "New" badge (case-sensitive: listing sites add literal "New")
    if title.endswith("New") and len(title) > 4:
        title = title[:-3].rstrip()

    # If title is excessively long (likely a scraped snippet), prefer slug
    if len(title) > 120 and url:
        slug_title = title_from_url_slug(url)
        if slug_title:
            return slug_title

    return title


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    # Enable WAL mode for concurrent read/write from multiple threads
    # (API server thread + Streamlit main thread)
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            source TEXT NOT NULL,
            description TEXT DEFAULT '',
            deadline TEXT DEFAULT '',
            country_restriction TEXT DEFAULT 'worldwide',
            terms_checked BOOLEAN DEFAULT 0,
            terms_excluded TEXT DEFAULT '',
            status TEXT DEFAULT 'new',
            total_entries INTEGER DEFAULT 0,
            your_entries INTEGER DEFAULT 0,
            win_probability REAL DEFAULT 0.0,
            entered_at TEXT DEFAULT '',
            discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,
            notes TEXT DEFAULT ''
        )
    """)
    try:
        cursor.execute("ALTER TABLE giveaways ADD COLUMN terms_checked BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE giveaways ADD COLUMN terms_excluded TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    # Indexes for common query patterns
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_giveaways_status ON giveaways(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_giveaways_discovered ON giveaways(discovered_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_giveaways_deadline ON giveaways(deadline)")
    conn.commit()
    conn.close()
    _init_blacklist_file()
    # Warm the blacklist cache at startup
    _load_blacklist()


def _get_blacklist_path():
    return os.path.join(os.path.dirname(__file__), "blacklist.txt")


def _init_blacklist_file():
    path = _get_blacklist_path()
    if not os.path.exists(path):
        with open(path, "w") as f:
            pass


def _load_blacklist():
    global _blacklist_cache
    path = _get_blacklist_path()
    if not os.path.exists(path):
        _blacklist_cache = set()
        return _blacklist_cache
    with open(path, "r") as f:
        _blacklist_cache = set(line.strip() for line in f if line.strip())
    return _blacklist_cache


def _save_blacklist(urls):
    global _blacklist_cache
    path = _get_blacklist_path()
    with open(path, "w") as f:
        for url in urls:
            f.write(url + "\n")
    _blacklist_cache = set(urls)


def add_to_blacklist(url, reason=""):
    global _blacklist_cache
    # Use in-memory cache if available, avoid full file re-read
    if _blacklist_cache is None:
        _load_blacklist()
    if url not in _blacklist_cache:
        _blacklist_cache.add(url)
        # Append-only write: O(1) instead of rewriting the entire file
        path = _get_blacklist_path()
        with open(path, "a") as f:
            f.write(url + "\n")
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM giveaways WHERE url = ?", (url,))
        conn.commit()
    finally:
        conn.close()


def get_blacklist():
    return list(_load_blacklist())


def remove_from_blacklist(url):
    blacklist = _load_blacklist()
    blacklist.discard(url)
    _save_blacklist(blacklist)


def is_blacklisted(url):
    global _blacklist_cache
    if _blacklist_cache is None:
        _load_blacklist()
    return url in _blacklist_cache


def add_giveaway(title, url, source, description="", deadline="", country_restriction="worldwide", terms_checked=False, terms_excluded=""):
    if is_blacklisted(url):
        return False
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO giveaways (title, url, source, description, deadline, country_restriction, terms_checked, terms_excluded, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, url, source, description, deadline, country_restriction, terms_checked, terms_excluded, datetime.now().isoformat()))
        conn.commit()
        return cursor.rowcount > 0
    except Exception:
        return False
    finally:
        conn.close()


def add_giveaways_batch(giveaway_list):
    """Insert multiple giveaways in a single transaction.

    Each item in *giveaway_list* should be a dict with keys matching the
    ``add_giveaway`` parameters.  Returns the number of newly inserted rows.
    """
    if not giveaway_list:
        return 0
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    new_count = 0
    for g in giveaway_list:
        url = g.get("url", "")
        if not url or is_blacklisted(url):
            continue
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO giveaways
                    (title, url, source, description, deadline, country_restriction,
                     terms_checked, terms_excluded, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                g.get("title", ""),
                url,
                g.get("source", ""),
                g.get("description", ""),
                g.get("deadline", ""),
                g.get("country_restriction", "worldwide"),
                g.get("terms_checked", False),
                g.get("terms_excluded", ""),
                now,
            ))
            new_count += cursor.rowcount
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return new_count


def get_giveaways(status=None, gleam_only=True, exclude_not_eligible=True):
    conn = get_connection()
    cursor = conn.cursor()
    base_query = "SELECT * FROM giveaways"
    conditions = []
    params = []
    
    if gleam_only:
        conditions.append("url LIKE 'https://gleam.io/%'")
    
    if exclude_not_eligible and not status:
        conditions.append("status != 'not_eligible'")
    
    if status:
        conditions.append("status = ?")
        params.append(status)
    
    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)
    
    base_query += " ORDER BY discovered_at DESC"
    
    cursor.execute(base_query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_giveaway_status(giveaway_id, status, notes=""):
    conn = get_connection()
    cursor = conn.cursor()
    if status == "participated":
        cursor.execute("""
            UPDATE giveaways SET status = :status, entered_at = :entered_at, notes = :notes WHERE id = :id
        """, {"status": status, "entered_at": datetime.now().isoformat(), "notes": notes, "id": giveaway_id})
    elif notes:
        cursor.execute("""
            UPDATE giveaways SET status = :status, notes = :notes WHERE id = :id
        """, {"status": status, "notes": notes, "id": giveaway_id})
    else:
        cursor.execute("""
            UPDATE giveaways SET status = :status WHERE id = :id
        """, {"status": status, "id": giveaway_id})
    conn.commit()
    conn.close()


def update_giveaway_entries(giveaway_id, total_entries, your_entries):
    from utils.probability import calculate_win_probability
    conn = get_connection()
    cursor = conn.cursor()
    prob = calculate_win_probability(your_entries, total_entries)
    cursor.execute("""
        UPDATE giveaways SET total_entries = ?, your_entries = ?, win_probability = ? WHERE id = ?
    """, (total_entries, your_entries, prob, giveaway_id))
    conn.commit()
    conn.close()


def update_giveaway_deadline(giveaway_id, deadline):
    """Update the deadline field for a giveaway."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE giveaways SET deadline = ? WHERE id = ?", (deadline, giveaway_id))
    conn.commit()
    conn.close()


def get_giveaway_by_url(url):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM giveaways WHERE url = ?", (url,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_known_urls():
    """Return the set of all giveaway URLs already in the database.

    Useful for bulk dedup during import so we don't query one-by-one.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM giveaways")
    urls = {row["url"] for row in cursor.fetchall()}
    conn.close()
    return urls


def update_terms_check(giveaway_id, checked, excluded_countries="", detected_region=None):
    conn = get_connection()
    cursor = conn.cursor()
    if detected_region:
        # Always update country_restriction when a region was detected from
        # T&C analysis -- including "restricted" (e.g. state-level US
        # restrictions like "residents of California only").
        cursor.execute("""
            UPDATE giveaways SET terms_checked = ?, terms_excluded = ?, country_restriction = ? WHERE id = ?
        """, (checked, excluded_countries, detected_region, giveaway_id))
    else:
        cursor.execute("""
            UPDATE giveaways SET terms_checked = ?, terms_excluded = ? WHERE id = ?
        """, (checked, excluded_countries, giveaway_id))
    conn.commit()
    conn.close()


def get_giveaways_display(status=None, gleam_only=True, exclude_not_eligible=True):
    """Optimized query that selects only the columns needed for table display."""
    conn = get_connection()
    cursor = conn.cursor()
    cols = "id, title, url, status, win_probability, total_entries, deadline, country_restriction, terms_checked, terms_excluded, discovered_at"
    base_query = f"SELECT {cols} FROM giveaways"
    conditions = []
    params = []

    if gleam_only:
        conditions.append("url LIKE 'https://gleam.io/%'")

    if exclude_not_eligible and not status:
        conditions.append("status != 'not_eligible'")

    if status:
        conditions.append("status = ?")
        params.append(status)

    if conditions:
        base_query += " WHERE " + " AND ".join(conditions)

    base_query += " ORDER BY discovered_at DESC"

    cursor.execute(base_query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats(gleam_only=True):
    conn = get_connection()
    cursor = conn.cursor()
    gleam_condition = "url LIKE 'https://gleam.io/%'" if gleam_only else "1=1"

    cursor.execute(f"""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'participated' THEN 1 ELSE 0 END) as participated,
            SUM(CASE WHEN status = 'eligible' THEN 1 ELSE 0 END) as eligible,
            SUM(CASE WHEN status = 'not_eligible' THEN 1 ELSE 0 END) as not_eligible,
            SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) as new_count,
            AVG(CASE WHEN total_entries > 0 AND status != 'not_eligible'
                THEN win_probability END) as avg_prob
        FROM giveaways WHERE {gleam_condition}
    """)
    row = cursor.fetchone()
    conn.close()
    return {
        "total": row["total"] or 0,
        "participated": row["participated"] or 0,
        "eligible": row["eligible"] or 0,
        "not_eligible": row["not_eligible"] or 0,
        "new": row["new_count"] or 0,
        "avg_win_probability": round(row["avg_prob"], 4) if row["avg_prob"] else 0,
    }


def mark_duplicate_or_skip(giveaway_id, reason=""):
    update_giveaway_status(giveaway_id, "skipped", reason)


def delete_not_eligible():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM giveaways WHERE status = 'not_eligible'")
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted


def get_unenriched_giveaways():
    """Return giveaways that still need enrichment (missing deadline or unchecked T&C).

    Returns a dict with two lists:
      - 'missing_deadline': dicts with id/url for entries with empty deadline
      - 'unchecked_terms':  dicts with id/url for entries with terms_checked = 0
    Only includes giveaways that haven't been marked as not_eligible or expired.
    """
    conn = get_connection()
    cursor = conn.cursor()
    active_filter = "status NOT IN ('not_eligible', 'expired', 'skipped')"

    cursor.execute(
        f"SELECT id, url FROM giveaways WHERE (deadline = '' OR deadline IS NULL) AND {active_filter}"
    )
    missing_deadline = [dict(r) for r in cursor.fetchall()]

    cursor.execute(
        f"SELECT id, url FROM giveaways WHERE terms_checked = 0 AND {active_filter}"
    )
    unchecked_terms = [dict(r) for r in cursor.fetchall()]

    conn.close()
    return {
        "missing_deadline": missing_deadline,
        "unchecked_terms": unchecked_terms,
    }


def parse_deadline(deadline_text):
    """Parse a deadline string into a datetime object.

    Handles many common deadline formats:
        "Friday 03 April 2026 at 22:59:59"    (Gleam primary)
        "03 April 2026 at 22:59:59"            (without day name)
        "03 April 2026"                         (date only)
        "April 17, 2026"                        (US full month)
        "Apr 17, 2026"                          (US abbreviated month)
        "April 17, 2026 11:59 PM"               (US with 12-hour time)
        "Apr 17, 2026 11:59 PM"                 (US abbreviated with 12-hour)
        "April 17, 2026 at 23:59:59"            (US with 24-hour time)
        "2026-04-17T23:59:59"                   (ISO 8601)
        "2026-04-17"                             (ISO 8601 date only)
        "17/04/2026"                             (DD/MM/YYYY)
        "04/17/2026"                             (MM/DD/YYYY via heuristic)
        "11 days"                                (relative countdown)
        "11d 5h" / "2d 3h 15m"                   (compact countdown)

    Returns None for empty strings or unparseable text.
    """
    if not deadline_text or not deadline_text.strip():
        return None
    text = deadline_text.strip()

    # ---- Exact strptime formats (most specific first) ----

    # Primary format: "Friday 03 April 2026 at 22:59:59"
    for fmt in (
        "%A %d %B %Y at %H:%M:%S",   # Friday 03 April 2026 at 22:59:59
        "%d %B %Y at %H:%M:%S",       # 03 April 2026 at 22:59:59
        "%d %B %Y at %H:%M",          # 03 April 2026 at 22:59
        "%d %B %Y",                    # 03 April 2026
        "%B %d, %Y at %H:%M:%S",      # April 17, 2026 at 23:59:59
        "%B %d, %Y at %H:%M",         # April 17, 2026 at 23:59
        "%B %d, %Y %I:%M %p",         # April 17, 2026 11:59 PM
        "%B %d, %Y %I:%M:%S %p",      # April 17, 2026 11:59:59 PM
        "%B %d, %Y",                   # April 17, 2026
        "%b %d, %Y at %H:%M:%S",      # Apr 17, 2026 at 23:59:59
        "%b %d, %Y at %H:%M",         # Apr 17, 2026 at 23:59
        "%b %d, %Y %I:%M %p",         # Apr 17, 2026 11:59 PM
        "%b %d, %Y %I:%M:%S %p",      # Apr 17, 2026 11:59:59 PM
        "%b %d, %Y",                   # Apr 17, 2026
        "%Y-%m-%dT%H:%M:%S",          # 2026-04-17T23:59:59
        "%Y-%m-%d %H:%M:%S",          # 2026-04-17 23:59:59
        "%Y-%m-%d",                    # 2026-04-17
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    # ---- DD/MM/YYYY or MM/DD/YYYY with slashes ----
    slash_match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
    if slash_match:
        a, b, year = int(slash_match.group(1)), int(slash_match.group(2)), int(slash_match.group(3))
        # If first number > 12, it must be DD/MM/YYYY
        if a > 12 and 1 <= b <= 12:
            try:
                return datetime(year, b, a)
            except ValueError:
                pass
        # If second number > 12, it must be MM/DD/YYYY
        elif b > 12 and 1 <= a <= 12:
            try:
                return datetime(year, a, b)
            except ValueError:
                pass
        # Ambiguous (both <= 12): assume DD/MM/YYYY (more common in Gleam's EU audience)
        elif 1 <= a <= 31 and 1 <= b <= 12:
            try:
                return datetime(year, b, a)
            except ValueError:
                pass

    # ---- Relative countdown text: "11 days", "2d 3h", "5h 30m" ----
    countdown = _parse_countdown(text)
    if countdown is not None:
        return countdown

    return None


# Pre-compiled patterns for countdown parsing
_COUNTDOWN_FULL_RE = re.compile(
    r"(\d+)\s*(?:days?|d)\b", re.IGNORECASE
)
_COUNTDOWN_HOURS_RE = re.compile(
    r"(\d+)\s*(?:hours?|hrs?|h)\b", re.IGNORECASE
)
_COUNTDOWN_MINS_RE = re.compile(
    r"(\d+)\s*(?:minutes?|mins?|m)\b", re.IGNORECASE
)
_COUNTDOWN_SECS_RE = re.compile(
    r"(\d+)\s*(?:seconds?|secs?|s)\b", re.IGNORECASE
)


def _parse_countdown(text):
    """Parse relative countdown text like '11 days', '2d 3h 15m' into an
    absolute datetime (now + delta).

    Only matches if the text contains at least one time-unit keyword
    and looks like a countdown (not a random sentence containing 'days').
    Returns a datetime or None.
    """
    # Must contain at least one digit followed by a time unit
    if not re.search(r"\d+\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", text, re.IGNORECASE):
        return None

    # Reject strings that are clearly not countdowns (contain non-countdown words)
    # Allow simple patterns like "11 days", "2d 3h 15m", "Ends in 5 days"
    stripped = re.sub(r"(?:ends?\s+in|remaining|left|only)\s*", "", text, flags=re.IGNORECASE).strip()

    days = 0
    hours = 0
    minutes = 0
    seconds = 0

    m = _COUNTDOWN_FULL_RE.search(stripped)
    if m:
        days = int(m.group(1))
    m = _COUNTDOWN_HOURS_RE.search(stripped)
    if m:
        hours = int(m.group(1))
    m = _COUNTDOWN_MINS_RE.search(stripped)
    if m:
        minutes = int(m.group(1))
    m = _COUNTDOWN_SECS_RE.search(stripped)
    if m:
        seconds = int(m.group(1))

    total = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if total.total_seconds() == 0:
        return None

    return datetime.now() + total


def remove_expired_giveaways():
    """Delete giveaways whose deadline has passed. Returns the count of removed rows."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, deadline FROM giveaways WHERE deadline != ''")
    rows = cursor.fetchall()
    now = datetime.now()
    expired_ids = []
    for row in rows:
        dt = parse_deadline(row["deadline"])
        if dt and dt < now:
            expired_ids.append(row["id"])
    if expired_ids:
        placeholders = ",".join("?" for _ in expired_ids)
        cursor.execute(f"DELETE FROM giveaways WHERE id IN ({placeholders})", expired_ids)
    conn.commit()
    conn.close()
    return len(expired_ids)


def cleanup_titles():
    """One-time cleanup of existing giveaway titles in the database.

    Applies clean_title() to every row, fixing:
        - Trailing "New" badges
        - Raw URLs used as titles
        - Excessively long snippet text

    Returns the count of updated rows.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, url FROM giveaways")
    rows = cursor.fetchall()
    updated = 0
    for row in rows:
        old_title = row["title"]
        new_title = clean_title(old_title, row["url"])
        if new_title != old_title:
            cursor.execute("UPDATE giveaways SET title = ? WHERE id = ?", (new_title, row["id"]))
            updated += 1
    conn.commit()
    conn.close()
    return updated


def remove_non_gleam_giveaways():
    """Delete giveaways whose URL is not on gleam.io.

    These entries can never have deadlines fetched or ended status checked,
    so they linger forever.  Returns the count of removed rows.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM giveaways WHERE url NOT LIKE 'https://gleam.io/%'")
    removed = cursor.rowcount
    conn.commit()
    conn.close()
    return removed


def remove_truncated_giveaways():
    """Delete giveaways whose URL was truncated by a search engine.

    These contain the Unicode ellipsis character (U+2026 ``…``) or end with
    three ASCII dots (``...``).  Such URLs point nowhere useful and produce
    broken links in the UI.  Returns the count of removed rows.
    """
    conn = get_connection()
    cursor = conn.cursor()
    # U+2026 is stored as the literal character in SQLite text
    cursor.execute(
        "DELETE FROM giveaways WHERE url LIKE '%\u2026%' OR url LIKE '%...'"
    )
    removed = cursor.rowcount
    conn.commit()
    conn.close()
    return removed
