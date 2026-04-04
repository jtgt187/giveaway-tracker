import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "giveaways.db")

# In-memory blacklist cache to avoid reading the file on every add_giveaway() call
_blacklist_cache = None


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()
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
    blacklist = _load_blacklist()
    blacklist.add(url)
    _save_blacklist(blacklist)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM giveaways WHERE url = ?", (url,))
    conn.commit()
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
        except Exception:
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
    update_data = {
        "status": status,
        "entered_at": datetime.now().isoformat() if status == "participated" else "",
        "notes": notes,
    }
    cursor.execute("""
        UPDATE giveaways SET status = :status, entered_at = :entered_at, notes = :notes WHERE id = :id
    """, {**update_data, "id": giveaway_id})
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


def get_giveaway_by_url(url):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM giveaways WHERE url = ?", (url,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_known_urls():
    """Return the set of all giveaway URLs already in the database.

    Useful for bulk dedup during crawl so we don't query one-by-one.
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
    if detected_region and detected_region != "restricted":
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


def parse_deadline(deadline_text):
    """Parse a deadline string into a datetime object.

    Handles the gleamfinder/bestofgleam format:
        "Friday 03 April 2026 at 22:59:59"

    Returns None for empty strings or unparseable text.
    """
    if not deadline_text or not deadline_text.strip():
        return None
    text = deadline_text.strip()
    # Primary format from gleamfinder/bestofgleam: "Friday 03 April 2026 at 22:59:59"
    try:
        return datetime.strptime(text, "%A %d %B %Y at %H:%M:%S")
    except ValueError:
        pass
    # Fallback: try without day name in case format varies
    try:
        return datetime.strptime(text, "%d %B %Y at %H:%M:%S")
    except ValueError:
        pass
    # Fallback: date only
    try:
        return datetime.strptime(text, "%d %B %Y")
    except ValueError:
        pass
    return None


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
