import logging
import sqlite3
import os
import re
import threading
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse


def _sanitize(value):
    """Replace lone UTF-16 surrogates in *value* with U+FFFD.

    Browser extensions occasionally emit broken surrogate pairs when
    serialising emoji.  SQLite's Python driver raises
    ``UnicodeEncodeError`` if these slip through, so we scrub them here.
    """
    if not isinstance(value, str):
        return value
    try:
        value.encode("utf-8")          # fast path: already valid
        return value
    except UnicodeEncodeError:
        return value.encode("utf-8", errors="surrogatepass") \
                     .decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Logging setup (shared by all modules)
# ---------------------------------------------------------------------------

_LOG_DIR = os.path.dirname(__file__)
_LOG_FILE = os.path.join(_LOG_DIR, "giveaway-tracker.log")

def setup_logging():
    """Configure root logger with file (rotating) + stderr handlers.

    Safe to call multiple times -- will not add duplicate handlers.
    """
    root = logging.getLogger()
    if root.handlers:
        return  # already configured
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler: 5 MB max, keep 3 backups
    fh = RotatingFileHandler(_LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console (stderr) handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)


# Initialise logging as early as possible
setup_logging()

logger = logging.getLogger("database")

DB_PATH = os.path.join(os.path.dirname(__file__), "giveaways.db")

# In-memory blacklist cache to avoid reading the file on every add_giveaway() call
_blacklist_cache = None
_blacklist_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Gleam URL validation
# ---------------------------------------------------------------------------

# Path patterns for actual giveaway/competition pages on gleam.io.
# Mirrors the validation in extension/background.js and extension/content.js.
# The key structural requirement is two path segments (/ID/slug), which
# distinguishes giveaway pages from non-giveaway pages (/terms, /login, etc.)
_GLEAM_GIVEAWAY_PATH_RE = re.compile(
    r'^/(?:giveaways|competitions)/[A-Za-z0-9]+$'
    r'|'
    r'^/[A-Za-z0-9]+/[^/]+$'
)

# Non-giveaway paths that should always be rejected even though they're on gleam.io.
_GLEAM_SKIP_PATHS = {
    '/giveaways', '/login', '/signup', '/account', '/settings',
    '/privacy', '/terms', '/about', '/contact', '/faq', '/help',
    '/docs', '/api', '/embed',
}


def is_gleam_giveaway_url(url):
    """Return True if *url* is a valid gleam.io giveaway/competition URL.

    Validates both the hostname (must be gleam.io) and the path pattern
    (must match ``/XXXXX/slug`` or ``/giveaways/XXXXX`` etc.).
    Rejects non-giveaway paths like ``/terms``, ``/login``, ``/privacy``.
    """
    if not url or not isinstance(url, str):
        return False
    if not url.startswith('https://gleam.io/'):
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.hostname != 'gleam.io':
        return False
    path = parsed.path.rstrip('/')
    if not path or path == '/':
        return False
    # Check against known non-giveaway paths (exact match or prefix)
    path_lower = path.lower()
    for skip in _GLEAM_SKIP_PATHS:
        if path_lower == skip or path_lower.startswith(skip + '/'):
            return False
    # Validate path matches giveaway pattern
    if not _GLEAM_GIVEAWAY_PATH_RE.match(path):
        return False
    return True


# ---------------------------------------------------------------------------
# Title extraction & cleanup
# ---------------------------------------------------------------------------

# Status messages that gleam.io displays instead of a real title when the
# competition is paused, ended, or otherwise unavailable.  Matched
# case-insensitively against extracted titles.
BAD_TITLES = {
    "competition paused",
    "competition ended",
    "competition has ended",
    "this competition has ended",
    "this giveaway has ended",
    "this promotion has ended",
    "giveaway ended",
    "giveaway has ended",
    "entries are now closed",
    "gleam giveaway",
}


def _is_bad_title(title):
    """Return True if *title* is a known status/placeholder message."""
    return title.strip().lower() in BAD_TITLES


def _extract_gleam_id(url):
    """Return the short alphanumeric giveaway ID from a Gleam URL, or ''."""
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        for part in parts:
            if re.fullmatch(r"[A-Za-z0-9]{3,7}", part):
                return part
    except Exception:
        pass
    return ""


def title_from_url_slug(url, id_fallback=False):
    """Extract a clean, human-readable title from a Gleam URL slug.

    Examples:
        "https://gleam.io/jyldJ/aoc-easter-hunt-giveaway"
            -> "AOC Easter Hunt Giveaway"
        "https://gleam.io/abc/win-stuff"
            -> "Win Stuff"

    When *id_fallback* is True and no human-readable slug is found, return
    the short giveaway ID (e.g. ``"VPItO"``) instead of an empty string.
    This is useful as a last-resort title so the entry isn't completely blank.

    Returns an empty string if no slug can be extracted (unless *id_fallback*).
    """
    try:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        # Gleam URLs: /<id>/<slug>  or /giveaways/<id>
        if len(parts) >= 2:
            slug = parts[-1]
        elif len(parts) == 1 and parsed.netloc:
            # Single-segment path (e.g. "https://gleam.io/VPItO")
            slug = parts[0]
        else:
            return ""
        # Skip if the slug looks like an ID (all alphanumeric, short)
        if re.fullmatch(r"[A-Za-z0-9]{3,7}", slug):
            if id_fallback:
                return slug
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
        - Breadcrumb-style search-engine titles (e.g. "https://gleam.io > giveaways > VPItO")
        - Known status-message titles (e.g. "Competition paused")
        - Excessively long snippet text (> 120 chars) -> use slug title

    Returns the cleaned title, or a slug-derived title as fallback.
    """
    if not title:
        return title_from_url_slug(url, id_fallback=True) if url else ""

    title = title.strip()

    # If title is a raw URL, use slug instead
    if title.startswith("http://") or title.startswith("https://"):
        return title_from_url_slug(title) or title_from_url_slug(url, id_fallback=True) or title

    # Breadcrumb-style title from search engines (e.g. "gleam.io > giveaways > VPItO")
    if "\u203a" in title:
        slug_title = title_from_url_slug(url, id_fallback=True)
        if slug_title:
            return slug_title
        # Can't salvage — fall through to return the breadcrumb as-is

    # Reject known status-message titles in favour of the URL slug
    if _is_bad_title(title):
        return title_from_url_slug(url, id_fallback=True) or ""

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
    try:
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
    finally:
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
    with _blacklist_lock:
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
    with _blacklist_lock:
        return list(_load_blacklist())


def remove_from_blacklist(url):
    with _blacklist_lock:
        blacklist = _load_blacklist()
        blacklist.discard(url)
        _save_blacklist(blacklist)


def is_blacklisted(url):
    global _blacklist_cache
    with _blacklist_lock:
        if _blacklist_cache is None:
            _load_blacklist()
        return url in _blacklist_cache


def add_giveaway(title, url, source, description="", deadline="", country_restriction="worldwide", terms_checked=False, terms_excluded=""):
    if is_blacklisted(url):
        return False
    if not is_gleam_giveaway_url(url):
        return False
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO giveaways (title, url, source, description, deadline, country_restriction, terms_checked, terms_excluded, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (_sanitize(title), _sanitize(url), _sanitize(source), _sanitize(description),
              _sanitize(deadline), _sanitize(country_restriction), terms_checked,
              _sanitize(terms_excluded), datetime.now().isoformat()))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error("add_giveaway failed for url=%s: %s", url, e, exc_info=True)
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
    skipped = 0
    try:
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        new_count = 0
        for g in giveaway_list:
            url = g.get("url", "")
            if not url or is_blacklisted(url) or not is_gleam_giveaway_url(url):
                skipped += 1
                continue
            try:
                cursor.execute("""
                    INSERT OR IGNORE INTO giveaways
                        (title, url, source, description, deadline, country_restriction,
                         terms_checked, terms_excluded, discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    _sanitize(g.get("title", "")),
                    _sanitize(url),
                    _sanitize(g.get("source", "")),
                    _sanitize(g.get("description", "")),
                    _sanitize(g.get("deadline", "")),
                    _sanitize(g.get("country_restriction", "worldwide")),
                    g.get("terms_checked", False),
                    _sanitize(g.get("terms_excluded", "")),
                    now,
                ))
                new_count += cursor.rowcount
            except sqlite3.IntegrityError:
                pass
        conn.commit()
    finally:
        conn.close()
    logger.info("add_giveaways_batch: inserted=%d, skipped=%d, total=%d",
                new_count, skipped, len(giveaway_list))
    return new_count


def get_giveaways(status=None, gleam_only=True, exclude_not_eligible=True):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        base_query = "SELECT * FROM giveaways"
        conditions = []
        params = []
        
        if gleam_only:
            conditions.append("url LIKE 'https://gleam.io/%'")
        
        if exclude_not_eligible and not status:
            conditions.append("status NOT IN ('not_eligible', 'expired')")
        
        if status:
            conditions.append("status = ?")
            params.append(status)
        
        if conditions:
            base_query += " WHERE " + " AND ".join(conditions)
        
        base_query += " ORDER BY discovered_at DESC"
        
        cursor.execute(base_query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_giveaway_status(giveaway_id, status, notes=""):
    conn = get_connection()
    try:
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
    finally:
        conn.close()


def update_giveaway_entries(giveaway_id, total_entries, your_entries):
    from utils.probability import calculate_win_probability
    conn = get_connection()
    try:
        cursor = conn.cursor()
        prob = calculate_win_probability(your_entries, total_entries)
        cursor.execute("""
            UPDATE giveaways SET total_entries = ?, your_entries = ?, win_probability = ? WHERE id = ?
        """, (total_entries, your_entries, prob, giveaway_id))
        conn.commit()
    finally:
        conn.close()


def update_giveaway_deadline(giveaway_id, deadline):
    """Update the deadline field for a giveaway.

    If the deadline is a relative countdown (e.g. '11 days'), convert it to an
    absolute ISO datetime before storing so it doesn't become stale.
    """
    stored = deadline
    if deadline and re.search(
        r'\d+\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|m)\b', deadline, re.IGNORECASE
    ):
        dt = _parse_countdown(deadline)
        if dt:
            stored = dt.strftime("%d %B %Y at %H:%M:%S")
            logger.debug("update_giveaway_deadline: converted relative '%s' -> '%s' (id=%s)",
                         deadline, stored, giveaway_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE giveaways SET deadline = ? WHERE id = ?", (stored, giveaway_id))
        conn.commit()
    finally:
        conn.close()
    logger.info("update_giveaway_deadline: id=%s, deadline='%s'", giveaway_id, stored)


def get_giveaway_by_url(url):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM giveaways WHERE url = ?", (url,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_known_urls():
    """Return the set of all giveaway URLs already in the database.

    Useful for bulk dedup during import so we don't query one-by-one.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT url FROM giveaways")
        urls = {row["url"] for row in cursor.fetchall()}
        return urls
    finally:
        conn.close()


def update_terms_check(giveaway_id, checked, excluded_countries="", detected_region=None):
    conn = get_connection()
    try:
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
    finally:
        conn.close()


def get_giveaways_display(status=None, gleam_only=True, exclude_not_eligible=True):
    """Optimized query that selects only the columns needed for table display.

    When *exclude_not_eligible* is True (the default) and no explicit *status*
    filter is given, rows with status ``not_eligible`` or ``expired`` are
    excluded.  Users can still view them via the explicit status filter.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cols = "id, title, url, status, win_probability, total_entries, deadline, country_restriction, terms_checked, terms_excluded, discovered_at"
        base_query = f"SELECT {cols} FROM giveaways"
        conditions = []
        params = []

        if gleam_only:
            conditions.append("url LIKE 'https://gleam.io/%'")

        if exclude_not_eligible and not status:
            conditions.append("status NOT IN ('not_eligible', 'expired')")

        if status:
            conditions.append("status = ?")
            params.append(status)

        if conditions:
            base_query += " WHERE " + " AND ".join(conditions)

        base_query += " ORDER BY discovered_at DESC"

        cursor.execute(base_query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_stats(gleam_only=True):
    conn = get_connection()
    try:
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
        return {
            "total": row["total"] or 0,
            "participated": row["participated"] or 0,
            "eligible": row["eligible"] or 0,
            "not_eligible": row["not_eligible"] or 0,
            "new": row["new_count"] or 0,
            "avg_win_probability": round(row["avg_prob"], 4) if row["avg_prob"] else 0,
        }
    finally:
        conn.close()


def mark_duplicate_or_skip(giveaway_id, reason=""):
    update_giveaway_status(giveaway_id, "skipped", reason)


def delete_not_eligible():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM giveaways WHERE status = 'not_eligible'")
        deleted = cursor.rowcount
        conn.commit()
        return deleted
    finally:
        conn.close()


def get_unenriched_giveaways():
    """Return giveaways that still need enrichment (missing deadline or unchecked T&C).

    Returns a list of dicts with ``id`` and ``url`` for every active giveaway
    that is missing a deadline OR has unchecked T&C.  The combined function
    ``enrich_giveaways_batch`` visits each URL once and extracts everything.

    Only includes giveaways that haven't been marked as not_eligible or expired.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        active_filter = "status NOT IN ('not_eligible', 'expired', 'skipped')"

        cursor.execute(
            f"SELECT id, url FROM giveaways "
            f"WHERE ((deadline = '' OR deadline IS NULL) OR terms_checked = 0) "
            f"AND {active_filter}"
        )
        rows = [dict(r) for r in cursor.fetchall()]
        return rows
    finally:
        conn.close()


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
    r"(\d+)\s*(?:seconds?|secs?)\b", re.IGNORECASE
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
    """Delete giveaways whose deadline has passed. Returns the count of removed rows.

    Skips relative countdown deadlines (e.g. '11 days') since re-parsing them
    would produce incorrect results -- they should have been converted to
    absolute dates at import/enrichment time.
    """
    expired_ids = []
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, url, deadline FROM giveaways WHERE deadline != ''")
        rows = cursor.fetchall()
        now = datetime.now()
        expired_ids = []
        # Pre-compiled pattern to detect relative countdowns that shouldn't be re-parsed
        relative_re = re.compile(
            r'^\s*(?:ends?\s+in\s+)?\d+\s*(?:days?|d|hours?|hrs?|h|minutes?|mins?|m)\b',
            re.IGNORECASE,
        )
        for row in rows:
            dl = row["deadline"]
            # Skip relative countdowns -- they can't be meaningfully re-evaluated
            if relative_re.search(dl):
                continue
            dt = parse_deadline(dl)
            if dt and dt < now:
                expired_ids.append(row["id"])
                logger.debug("remove_expired_giveaways: expired id=%s, url=%s, deadline='%s'",
                             row["id"], row["url"], dl)
        if expired_ids:
            placeholders = ",".join("?" for _ in expired_ids)
            cursor.execute(f"DELETE FROM giveaways WHERE id IN ({placeholders})", expired_ids)
        conn.commit()
    finally:
        conn.close()
    if expired_ids:
        logger.info("remove_expired_giveaways: deleted %d expired giveaways", len(expired_ids))
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
    try:
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
        return updated
    finally:
        conn.close()


def remove_non_gleam_giveaways():
    """Delete giveaways whose URL is not on gleam.io.

    These entries can never have deadlines fetched or ended status checked,
    so they linger forever.  Returns the count of removed rows.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM giveaways WHERE url NOT LIKE 'https://gleam.io/%'")
        removed = cursor.rowcount
        conn.commit()
        return removed
    finally:
        conn.close()


def remove_truncated_giveaways():
    """Delete giveaways whose URL was truncated by a search engine.

    These contain the Unicode ellipsis character (U+2026 ``…``) or end with
    three ASCII dots (``...``).  Such URLs point nowhere useful and produce
    broken links in the UI.  Returns the count of removed rows.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # U+2026 is stored as the literal character in SQLite text
        cursor.execute(
            "DELETE FROM giveaways WHERE url LIKE '%\u2026%' OR url LIKE '%...'"
        )
        removed = cursor.rowcount
        conn.commit()
        return removed
    finally:
        conn.close()


def remove_non_giveaway_gleam_paths():
    """Delete gleam.io URLs that are not actual giveaway/competition pages.

    Removes entries whose URL path matches non-giveaway pages like
    ``/terms``, ``/privacy``, ``/login``, etc.  Returns the count of
    removed rows.
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, url FROM giveaways WHERE url LIKE 'https://gleam.io/%'")
        rows = cursor.fetchall()
        bad_ids = []
        for row in rows:
            if not is_gleam_giveaway_url(row["url"]):
                bad_ids.append(row["id"])
        if bad_ids:
            placeholders = ",".join("?" for _ in bad_ids)
            cursor.execute(f"DELETE FROM giveaways WHERE id IN ({placeholders})", bad_ids)
        conn.commit()
        return len(bad_ids)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Title-based expiry detection
# ---------------------------------------------------------------------------

# Patterns to extract dates from titles like "Ends April 5th", "Ends April 5, 2026",
# "Ends 04/05/2026", etc.
_TITLE_DATE_PATTERNS = [
    # "Ends April 5th" / "Ends April 5Th" / "Ends April 5, 2026"
    re.compile(
        r'ends?\s+'
        r'((?:january|february|march|april|may|june|july|august|september|october|november|december)'
        r'\s+\d{1,2}(?:st|nd|rd|th)?'
        r'(?:[,\s]+\d{4})?)',
        re.IGNORECASE,
    ),
    # "Ends 04/05/2026" or "Ends 04-05-2026"
    re.compile(
        r'ends?\s+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})',
        re.IGNORECASE,
    ),
    # "Ends 5 April 2026" / "Ends 5 April"
    re.compile(
        r'ends?\s+'
        r'(\d{1,2}\s+'
        r'(?:january|february|march|april|may|june|july|august|september|october|november|december)'
        r'(?:\s+\d{4})?)',
        re.IGNORECASE,
    ),
]

# Month name -> number mapping for manual parsing
_MONTH_NAMES = {
    'january': 1, 'february': 2, 'march': 3, 'april': 4,
    'may': 5, 'june': 6, 'july': 7, 'august': 8,
    'september': 9, 'october': 10, 'november': 11, 'december': 12,
}


def _parse_title_date(date_str):
    """Try to parse a date string extracted from a giveaway title.

    Handles formats like "April 5th", "April 5, 2026", "5 April 2026",
    "04/05/2026".  If no year is specified, assumes the current year
    (or next year if the date would be in the past by more than 30 days
    with current year -- handles December->January rollover).
    """
    date_str = re.sub(r'(?:st|nd|rd|th)\b', '', date_str, flags=re.IGNORECASE).strip()

    now = datetime.now()

    # Try "Month Day [Year]" format
    m = re.match(
        r'(january|february|march|april|may|june|july|august|september|october|november|december)'
        r'\s+(\d{1,2})(?:[,\s]+(\d{4}))?',
        date_str, re.IGNORECASE,
    )
    if m:
        month = _MONTH_NAMES[m.group(1).lower()]
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        try:
            dt = datetime(year, month, day, 23, 59, 59)
            return dt
        except ValueError:
            return None

    # Try "Day Month [Year]" format
    m = re.match(
        r'(\d{1,2})\s+'
        r'(january|february|march|april|may|june|july|august|september|october|november|december)'
        r'(?:\s+(\d{4}))?',
        date_str, re.IGNORECASE,
    )
    if m:
        day = int(m.group(1))
        month = _MONTH_NAMES[m.group(2).lower()]
        year = int(m.group(3)) if m.group(3) else now.year
        try:
            dt = datetime(year, month, day, 23, 59, 59)
            return dt
        except ValueError:
            return None

    # Try numeric formats (MM/DD/YYYY or DD/MM/YYYY -- assume US format for titles)
    m = re.match(r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})', date_str)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        # Assume MM/DD/YYYY
        month, day = a, b
        if month > 12:
            month, day = b, a
        try:
            return datetime(year, month, day, 23, 59, 59)
        except ValueError:
            return None

    return None


def expire_by_title_date():
    """Scan giveaway titles for embedded end dates and mark expired ones.

    Looks for patterns like "Ends April 5th" in the title text.  If the
    parsed date is in the past, the giveaway status is set to ``expired``.

    Returns the count of newly expired rows.
    """
    expired_ids = []
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title FROM giveaways WHERE status NOT IN ('expired', 'skipped')"
        )
        rows = cursor.fetchall()
        now = datetime.now()
        expired_ids = []
        for row in rows:
            title = row["title"]
            for pattern in _TITLE_DATE_PATTERNS:
                m = pattern.search(title)
                if m:
                    dt = _parse_title_date(m.group(1))
                    if dt and dt < now:
                        expired_ids.append(row["id"])
                        logger.debug("expire_by_title_date: id=%s title='%s' parsed_date=%s",
                                     row["id"], title, dt.isoformat())
                    break  # only use the first matching pattern per title
        if expired_ids:
            placeholders = ",".join("?" for _ in expired_ids)
            cursor.execute(
                f"UPDATE giveaways SET status = 'expired' WHERE id IN ({placeholders})",
                expired_ids,
            )
        conn.commit()
    finally:
        conn.close()
    if expired_ids:
        logger.info("expire_by_title_date: marked %d giveaways as expired", len(expired_ids))
    return len(expired_ids)
