import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "giveaways.db")


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
    conn.commit()
    conn.close()
    _init_blacklist_file()


def _get_blacklist_path():
    return os.path.join(os.path.dirname(__file__), "blacklist.txt")


def _init_blacklist_file():
    path = _get_blacklist_path()
    if not os.path.exists(path):
        with open(path, "w") as f:
            pass


def _load_blacklist():
    path = _get_blacklist_path()
    if not os.path.exists(path):
        return set()
    with open(path, "r") as f:
        return set(line.strip() for line in f if line.strip())


def _save_blacklist(urls):
    path = _get_blacklist_path()
    with open(path, "w") as f:
        for url in urls:
            f.write(url + "\n")


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
    return url in _load_blacklist()


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


def update_terms_check(giveaway_id, checked, excluded_countries=""):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE giveaways SET terms_checked = ?, terms_excluded = ? WHERE id = ?
    """, (checked, excluded_countries, giveaway_id))
    conn.commit()
    conn.close()


def get_stats(gleam_only=True):
    conn = get_connection()
    cursor = conn.cursor()
    gleam_condition = "url LIKE 'https://gleam.io/%'" if gleam_only else "1=1"

    def _where(*conditions):
        return "WHERE " + " AND ".join(conditions)

    status_participated = "status = 'participated'"
    status_eligible = "status = 'eligible'"
    status_not_eligible = "status = 'not_eligible'"
    status_new = "status = 'new'"
    entries_filter = "total_entries > 0"
    exclude_not_eligible = "status != 'not_eligible'"

    cursor.execute(f"SELECT COUNT(*) as total FROM giveaways {_where(gleam_condition)}")
    total = cursor.fetchone()["total"]
    cursor.execute(f"SELECT COUNT(*) as count FROM giveaways {_where(gleam_condition, status_participated)}")
    participated = cursor.fetchone()["count"]
    cursor.execute(f"SELECT COUNT(*) as count FROM giveaways {_where(gleam_condition, status_eligible)}")
    eligible = cursor.fetchone()["count"]
    cursor.execute(f"SELECT COUNT(*) as count FROM giveaways {_where(gleam_condition, status_not_eligible)}")
    not_eligible = cursor.fetchone()["count"]
    cursor.execute(f"SELECT COUNT(*) as count FROM giveaways {_where(gleam_condition, status_new)}")
    new_count = cursor.fetchone()["count"]
    cursor.execute(f"SELECT AVG(win_probability) as avg_prob FROM giveaways {_where(gleam_condition, entries_filter, exclude_not_eligible)}")
    row = cursor.fetchone()
    avg_prob = row["avg_prob"] if row and row["avg_prob"] else 0
    conn.close()
    return {
        "total": total,
        "participated": participated,
        "eligible": eligible,
        "not_eligible": not_eligible,
        "new": new_count,
        "avg_win_probability": round(avg_prob, 4) if avg_prob else 0,
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
