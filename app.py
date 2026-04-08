import logging
import streamlit as st
import pandas as pd
from datetime import datetime
from html import escape as html_escape
import glob as _glob
import time
import os
import sys
import json
import threading

sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, add_giveaway, add_giveaways_batch, get_giveaways, get_giveaways_display, update_giveaway_status, get_stats, update_giveaway_entries, get_giveaway_by_url, delete_not_eligible, update_terms_check, add_to_blacklist, get_blacklist, remove_from_blacklist, remove_expired_giveaways, get_connection, update_giveaway_deadline, get_unenriched_giveaways, clean_title, cleanup_titles, remove_non_gleam_giveaways, remove_truncated_giveaways, is_gleam_giveaway_url, remove_non_giveaway_gleam_paths, expire_by_title_date
from config import load_config, save_config
from entry.auto_enter import auto_enter_giveaway, check_giveaway_terms, enrich_giveaways_batch
from utils.country_check import is_eligible_for_country, is_region_blocked, is_ended
from utils.probability import format_probability

logger = logging.getLogger("app")

try:
    init_db()
    logger.info("Database initialized successfully")
except Exception as _init_err:
    import traceback
    logger.critical("Database initialization failed: %s", _init_err, exc_info=True)
    st.error(f"Database initialization failed: {_init_err}")
    st.stop()

# Start the local API server for live Chrome extension sync (port 7778)
from api_server import start_api_server as _start_api_server
if "api_server_started" not in st.session_state:
    try:
        _start_api_server(port=7778)
        st.session_state.api_server_started = True
    except Exception:
        # Port already in use or other startup error — not critical
        st.session_state.api_server_started = True

# Expired giveaway cleanup runs on every page load in main() — it's a fast
# indexed SQL DELETE so the overhead is negligible.


# ---------------------------------------------------------------------------
# Background enrichment worker
# ---------------------------------------------------------------------------
# Module-level singleton so the enrichment runs once across all Streamlit
# sessions/reruns.  The UI polls the worker's state to show progress without
# blocking the page.

class EnrichmentWorker:
    """Thread-safe enrichment state that can be polled by the Streamlit UI."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._done = False
        self._step = ""          # e.g. "Fetching deadlines..."
        self._progress = 0       # 0-100
        self._detail = ""        # e.g. "[3/12] https://gleam.io/..."
        self._error = ""
        self._thread = None

    # -- Public read API (thread-safe) --

    @property
    def running(self):
        with self._lock:
            return self._running

    @property
    def done(self):
        with self._lock:
            return self._done

    def snapshot(self):
        """Return a dict snapshot of the current state for UI rendering."""
        with self._lock:
            return {
                "running": self._running,
                "done": self._done,
                "step": self._step,
                "progress": self._progress,
                "detail": self._detail,
                "error": self._error,
            }

    # -- Internal write API (called from background thread) --

    def _set_step(self, step, progress=None):
        with self._lock:
            self._step = step
            if progress is not None:
                self._progress = progress

    def _set_detail(self, detail):
        with self._lock:
            self._detail = detail

    def _set_progress(self, progress):
        with self._lock:
            self._progress = progress

    def _set_error(self, error):
        with self._lock:
            self._error = error

    # -- Start / run --

    def reset(self):
        """Reset the worker so it can be started again.

        No-op if currently running.  Safe to call from any thread.
        """
        with self._lock:
            if self._running:
                return
            self._done = False
            self._step = ""
            self._progress = 0
            self._detail = ""
            self._error = ""
            self._thread = None

    def start(self):
        """Start the enrichment pipeline in a background thread.

        Returns immediately.  No-op if already running or already done.
        """
        with self._lock:
            if self._running or self._done:
                return
            self._running = True

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="enrichment-worker"
        )
        self._thread.start()

    def _run(self):
        try:
            self._do_enrichment()
        except Exception as e:
            self._set_error(str(e))
        finally:
            with self._lock:
                self._running = False
                self._done = True
            # Signal that cached display data should be invalidated on the
            # next Streamlit rerun.  We do NOT call _cached_giveaways_display.clear()
            # here because st.cache_data is not thread-safe.
            self._cache_dirty = True

    @property
    def cache_dirty(self):
        with self._lock:
            return getattr(self, '_cache_dirty', False)

    def clear_cache_dirty(self):
        with self._lock:
            self._cache_dirty = False

    def _do_enrichment(self):
        unenriched = get_unenriched_giveaways()

        if not unenriched:
            self._set_step("Nothing to enrich", 100)
            logger.info("enrichment: nothing to enrich")
            return

        total = len(unenriched)
        total_work = total + 1  # +1 for eligibility scan
        completed = [0]  # mutable counter for callback (thread-safe via worker lock)

        logger.info("enrichment: starting pipeline with %d unenriched giveaways", total)
        self._set_step(f"Enriching (0/{total})...", 0)
        urls = [g["url"] for g in unenriched]
        url_to_id = {g["url"]: g["id"] for g in unenriched}

        def _on_result(entry):
            gid = url_to_id.get(entry["url"])
            if not gid:
                logger.warning("enrichment: no giveaway ID found for URL %s", entry["url"])
                completed[0] += 1
                return

            # Persist deadline
            if entry.get("deadline"):
                update_giveaway_deadline(gid, entry["deadline"])
                logger.info("enrichment: saved deadline='%s' for id=%s (%s)",
                            entry["deadline"], gid, entry["url"])
            else:
                logger.debug("enrichment: no deadline returned for id=%s (%s)", gid, entry["url"])

            # Persist T&C results (only if we actually checked T&C)
            if not entry.get("email_blocked") and not entry.get("error"):
                excluded_str = ",".join(entry["excluded"]) if entry.get("excluded") else ""
                update_terms_check(gid, True, excluded_str, entry.get("region"))

            # Auto-mark ended / region-blocked / needs_review
            if entry.get("ended"):
                update_giveaway_status(gid, "expired")
                logger.info("enrichment: marked EXPIRED id=%s (%s)", gid, entry["url"])
            elif entry.get("region_blocked"):
                update_giveaway_status(gid, "not_eligible")
                logger.info("enrichment: marked NOT_ELIGIBLE (region blocked) id=%s (%s)", gid, entry["url"])
            elif entry.get("email_blocked"):
                update_giveaway_status(gid, "needs_review", notes="enrichment_blocked:email_subscribe")
                logger.info("enrichment: marked NEEDS_REVIEW (email blocked) id=%s (%s)", gid, entry["url"])
            elif entry.get("error"):
                update_giveaway_status(gid, "needs_review", notes=f"enrichment_error:{entry['error'][:200]}")
                logger.warning("enrichment: marked NEEDS_REVIEW (error) id=%s (%s): %s",
                               gid, entry["url"], entry["error"][:200])

            completed[0] += 1
            pct = int(completed[0] / total_work * 100)
            self._set_step(f"Enriching ({completed[0]}/{total})...", pct)
            self._set_detail(entry["url"])

        try:
            enrich_giveaways_batch(urls, on_result=_on_result)
        except Exception as e:
            self._set_error(f"Enrichment error: {e}")
            logger.error("enrichment: batch enrichment failed: %s", e, exc_info=True)

        # Step 2: Scan eligibility (fast, pure DB)
        self._set_step("Scanning eligibility...", 95)
        logger.info("enrichment: scanning eligibility...")
        scan_existing_entries()

        # Step 3: Remove expired and clean up invalid entries
        self._set_step("Removing expired giveaways...", 97)
        removed = remove_expired_giveaways()
        title_expired = expire_by_title_date()
        non_giveaway = remove_non_giveaway_gleam_paths()
        logger.info("enrichment: cleanup done -- removed=%d, title_expired=%d, non_giveaway=%d",
                     removed, title_expired, non_giveaway)

        self._set_step("Enrichment complete", 100)
        logger.info("enrichment: pipeline complete")


# Module-level singleton -- survives Streamlit reruns
_enrichment_worker = EnrichmentWorker()


@st.cache_data(ttl=5)
def _cached_giveaways_display(status=None, exclude_not_eligible=True):
    """Cached wrapper for get_giveaways_display to avoid re-querying SQLite on every Streamlit rerun."""
    return get_giveaways_display(status=status, exclude_not_eligible=exclude_not_eligible)


st.set_page_config(
    page_title="Giveaway Tracker",
    page_icon="🎁",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<link rel="preload" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" as="style" onload="this.onload=null;this.rel='stylesheet'">
<noscript><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap"></noscript>
<style>

    :root {
        --bg-primary: #0a0a0f;
        --bg-secondary: #12121a;
        --bg-tertiary: #1a1a28;
        --bg-elevated: rgba(26, 26, 40, 0.6);
        --bg-glass: rgba(255, 255, 255, 0.03);
        --bg-glass-hover: rgba(255, 255, 255, 0.06);

        --border-subtle: rgba(255, 255, 255, 0.06);
        --border-default: rgba(255, 255, 255, 0.1);
        --border-hover: rgba(255, 255, 255, 0.15);
        --border-focus: rgba(124, 92, 255, 0.5);

        --text-primary: #f0f0f5;
        --text-secondary: #9090a8;
        --text-tertiary: #606078;
        --text-inverse: #ffffff;

        --accent-primary: #7c3aed;
        --accent-secondary: #a78bfa;
        --accent-hover: #6d28d9;
        --accent-glow: rgba(124, 58, 237, 0.25);

        --success: #10b981;
        --success-bg: rgba(16, 185, 129, 0.1);
        --warning: #f59e0b;
        --warning-bg: rgba(245, 158, 11, 0.1);
        --error: #ef4444;
        --error-bg: rgba(239, 68, 68, 0.1);
        --info: #3b82f6;
        --info-bg: rgba(59, 130, 246, 0.1);

        --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
        --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.4);
        --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.5);

        --radius-sm: 8px;
        --radius-md: 12px;
        --radius-lg: 16px;
        --radius-xl: 20px;
        --radius-full: 9999px;

        --transition-fast: 150ms cubic-bezier(0.4, 0, 0.2, 1);
        --transition-base: 200ms cubic-bezier(0.4, 0, 0.2, 1);
        --transition-slow: 300ms cubic-bezier(0.4, 0, 0.2, 1);
    }

    * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }

    body {
        background: var(--bg-primary);
        background-image:
            radial-gradient(ellipse 80% 50% at 50% -20%, rgba(124, 58, 237, 0.08), transparent),
            radial-gradient(ellipse 60% 40% at 80% 60%, rgba(59, 130, 246, 0.04), transparent);
        background-attachment: fixed;
    }

    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1400px;
    }

    h1, h2, h3, h4, h5, h6 {
        color: var(--text-primary) !important;
        letter-spacing: -0.02em;
    }

    .main-header {
        margin-bottom: 2rem;
    }
    .main-header h1 {
        font-size: 2rem;
        font-weight: 800;
        background: linear-gradient(135deg, var(--text-primary) 0%, var(--accent-secondary) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 4px;
    }
    .main-header .subtitle {
        font-size: 0.95rem;
        color: var(--text-tertiary);
        font-weight: 400;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: var(--bg-secondary);
        border-radius: var(--radius-lg);
        padding: 4px;
        border: 1px solid var(--border-subtle);
    }
    .stTabs [data-baseweb="tab"] {
        height: 42px;
        padding: 0 16px;
        border-radius: var(--radius-md);
        background: transparent;
        border: none;
        transition: all var(--transition-base);
        color: var(--text-secondary) !important;
        font-weight: 500;
        font-size: 0.875rem;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: var(--bg-glass-hover);
        color: var(--text-primary) !important;
    }
    .stTabs [aria-selected="true"] {
        background: var(--accent-primary) !important;
        color: var(--text-inverse) !important;
        box-shadow: 0 2px 8px var(--accent-glow);
    }

    .stat-card {
        background: var(--bg-elevated);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-radius: var(--radius-lg);
        padding: 24px;
        border: 1px solid var(--border-subtle);
        box-shadow: var(--shadow-md);
        transition: all var(--transition-base);
        position: relative;
        overflow: hidden;
    }
    .stat-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
    }
    .stat-card:hover {
        border-color: var(--border-hover);
        box-shadow: var(--shadow-lg);
        transform: translateY(-2px);
    }
    .stat-card .stat-icon {
        width: 40px;
        height: 40px;
        border-radius: var(--radius-md);
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 16px;
    }
    .stat-card h3 {
        color: var(--text-tertiary);
        font-size: 0.75rem;
        font-weight: 600;
        margin: 0 0 8px 0;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .stat-card .value {
        color: var(--text-primary);
        font-size: 2rem;
        font-weight: 800;
        margin: 0;
        line-height: 1;
        font-variant-numeric: tabular-nums;
    }
    .stat-card .sub {
        color: var(--text-tertiary);
        font-size: 0.8rem;
        margin: 8px 0 0 0;
    }

    .stat-card.purple .stat-icon { background: rgba(124, 58, 237, 0.15); color: var(--accent-primary); }
    .stat-card.purple .value { color: var(--accent-secondary); }
    .stat-card.purple:hover { border-color: rgba(124, 58, 237, 0.3); }

    .stat-card.green .stat-icon { background: var(--success-bg); color: var(--success); }
    .stat-card.green .value { color: var(--success); }
    .stat-card.green:hover { border-color: rgba(16, 185, 129, 0.3); }

    .stat-card.blue .stat-icon { background: var(--info-bg); color: var(--info); }
    .stat-card.blue .value { color: var(--info); }
    .stat-card.blue:hover { border-color: rgba(59, 130, 246, 0.3); }

    .stat-card.orange .stat-icon { background: var(--warning-bg); color: var(--warning); }
    .stat-card.orange .value { color: var(--warning); }
    .stat-card.orange:hover { border-color: rgba(245, 158, 11, 0.3); }

    .stat-card.red .stat-icon { background: var(--error-bg); color: var(--error); }
    .stat-card.red .value { color: var(--error); }
    .stat-card.red:hover { border-color: rgba(239, 68, 68, 0.3); }

    .section-divider {
        border: none;
        height: 1px;
        background: var(--border-subtle);
        margin: 2rem 0;
    }

    .section-title {
        color: var(--text-primary);
        font-size: 1.1rem;
        font-weight: 700;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .source-card {
        background: var(--bg-glass);
        border-radius: var(--radius-md);
        padding: 16px;
        border: 1px solid var(--border-subtle);
        display: flex;
        align-items: center;
        gap: 16px;
        transition: all var(--transition-base);
        margin-bottom: 8px;
    }
    .source-card:hover {
        background: var(--bg-glass-hover);
        border-color: var(--border-default);
    }
    .source-card .source-icon {
        width: 36px;
        height: 36px;
        border-radius: var(--radius-sm);
        background: var(--info-bg);
        color: var(--info);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
    }
    .source-card .source-name {
        color: var(--text-primary);
        font-weight: 600;
        font-size: 0.9rem;
    }
    .source-card .source-status {
        color: var(--text-tertiary);
        font-size: 0.8rem;
    }

    .results-summary {
        background: var(--bg-glass);
        border-radius: var(--radius-lg);
        padding: 24px;
        border: 1px solid var(--success-bg);
    }
    .results-summary .results-title {
        color: var(--success);
        font-size: 1rem;
        font-weight: 700;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .results-summary .results-detail {
        color: var(--text-secondary);
        font-size: 0.875rem;
    }
    .results-summary .results-detail strong {
        color: var(--text-primary);
        font-weight: 600;
    }

    .giveaway-card {
        background: var(--bg-elevated);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-radius: var(--radius-lg);
        padding: 24px;
        border: 1px solid var(--border-subtle);
        box-shadow: var(--shadow-sm);
        transition: all var(--transition-base);
        margin-bottom: 16px;
    }
    .giveaway-card:hover {
        border-color: var(--border-hover);
        box-shadow: var(--shadow-md);
        transform: translateY(-1px);
    }
    .giveaway-card .giveaway-title {
        color: var(--text-primary);
        font-weight: 600;
        font-size: 0.95rem;
        margin-bottom: 4px;
        line-height: 1.4;
    }
    .giveaway-card .giveaway-meta {
        color: var(--text-tertiary);
        font-size: 0.8rem;
        display: flex;
        align-items: center;
        gap: 16px;
    }

    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 12px;
        border-radius: var(--radius-full);
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .status-new { background: var(--info-bg); color: var(--info); }
    .status-eligible { background: var(--success-bg); color: var(--success); }
    .status-participated { background: rgba(124, 58, 237, 0.1); color: var(--accent-secondary); }
    .status-not_eligible { background: var(--error-bg); color: var(--error); }
    .status-expired { background: rgba(107, 114, 128, 0.1); color: #6b7280; }
    .status-skipped { background: var(--warning-bg); color: var(--warning); }
    .status-needs_review { background: rgba(251, 146, 60, 0.1); color: #fb923c; }

    .log-entry {
        background: var(--bg-secondary);
        border-radius: var(--radius-sm);
        padding: 8px 16px;
        margin: 4px 0;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 0.75rem;
        color: var(--text-secondary);
        border-left: 3px solid var(--accent-primary);
        transition: all var(--transition-fast);
    }
    .log-entry:hover {
        background: var(--bg-tertiary);
    }
    .log-success { border-left-color: var(--success); color: var(--success); }
    .log-error { border-left-color: var(--error); color: var(--error); }
    .log-warning { border-left-color: var(--warning); color: var(--warning); }

    .probability-high { color: var(--success); font-weight: 700; }
    .probability-medium { color: var(--warning); font-weight: 700; }
    .probability-low { color: var(--error); font-weight: 700; }

    .settings-section {
        background: var(--bg-elevated);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border-radius: var(--radius-lg);
        padding: 24px;
        border: 1px solid var(--border-subtle);
        margin-bottom: 16px;
    }
    .settings-section h3 {
        color: var(--text-primary);
        font-size: 0.95rem;
        font-weight: 700;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    .site-item {
        background: var(--bg-glass);
        border-radius: var(--radius-md);
        padding: 16px;
        border: 1px solid var(--border-subtle);
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;
        transition: all var(--transition-base);
    }
    .site-item:hover {
        background: var(--bg-glass-hover);
        border-color: var(--border-default);
    }
    .site-item code {
        color: var(--text-secondary);
        font-size: 0.85rem;
        background: var(--bg-secondary);
        padding: 4px 8px;
        border-radius: var(--radius-sm);
    }

    .db-info {
        background: var(--bg-glass);
        border-radius: var(--radius-md);
        padding: 16px;
        border: 1px solid var(--border-subtle);
    }
    .db-info p {
        color: var(--text-secondary);
        font-size: 0.875rem;
        margin: 4px 0;
    }
    .db-info code {
        color: var(--accent-secondary);
        background: rgba(124, 58, 237, 0.1);
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 0.8rem;
    }

    .empty-state {
        background: var(--bg-glass);
        border-radius: var(--radius-lg);
        padding: 48px;
        border: 1px dashed var(--border-default);
        text-align: center;
    }
    .empty-state p {
        color: var(--text-tertiary);
        font-size: 0.9rem;
    }

    [data-testid="stSidebar"] {
        background-color: var(--bg-secondary);
        border-right: 1px solid var(--border-subtle);
    }

    .stDataFrame { border-radius: var(--radius-lg); overflow: hidden; }

    .stButton > button {
        border-radius: var(--radius-md) !important;
        font-weight: 600 !important;
        transition: all var(--transition-base) !important;
        border: 1px solid var(--border-subtle) !important;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: var(--shadow-md);
    }
    .stButton > button[kind="primary"] {
        background: var(--accent-primary) !important;
        border-color: var(--accent-primary) !important;
        box-shadow: 0 2px 8px var(--accent-glow);
    }
    .stButton > button[kind="primary"]:hover {
        background: var(--accent-hover) !important;
        box-shadow: 0 4px 16px var(--accent-glow);
    }

    .stSelectbox > div > div {
        background: var(--bg-secondary) !important;
        border-color: var(--border-default) !important;
        border-radius: var(--radius-md) !important;
    }

    .stTextInput > div > div {
        background: var(--bg-secondary) !important;
        border-color: var(--border-default) !important;
        border-radius: var(--radius-md) !important;
    }
    .stTextInput > div > div:focus-within {
        border-color: var(--border-focus) !important;
        box-shadow: 0 0 0 3px var(--accent-glow) !important;
    }

    .stSlider > div > div > div {
        background: var(--accent-primary) !important;
    }

    .stCheckbox > label > div {
        background: var(--accent-primary) !important;
    }

    @keyframes shimmer {
        0% { background-position: -200% 0; }
        100% { background-position: 200% 0; }
    }
    .skeleton {
        background: linear-gradient(90deg, var(--bg-tertiary) 25%, var(--bg-glass-hover) 50%, var(--bg-tertiary) 75%);
        background-size: 200% 100%;
        animation: shimmer 1.5s infinite;
        border-radius: var(--radius-sm);
    }

    /* Custom giveaway table */
    .ga-table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        border-radius: var(--radius-lg);
        overflow: hidden;
        border: 1px solid var(--border-subtle);
    }
    .ga-table th {
        background: var(--bg-tertiary);
        color: var(--text-secondary);
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        padding: 10px 14px;
        text-align: left;
        border-bottom: 1px solid var(--border-default);
    }
    .ga-table td {
        padding: 10px 14px;
        border-bottom: 1px solid var(--border-subtle);
        font-size: 0.875rem;
        color: var(--text-primary);
        vertical-align: middle;
    }
    .ga-table tr:last-child td {
        border-bottom: none;
    }
    .ga-table tr:hover td {
        background: var(--bg-glass-hover);
    }
    .ga-table a.ga-title {
        color: var(--accent-primary);
        text-decoration: none;
        font-weight: 500;
        transition: color var(--transition-base);
    }
    .ga-table a.ga-title:hover {
        color: var(--accent-hover);
        text-decoration: underline;
    }
    .ga-table .ga-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: var(--radius-sm);
        font-size: 0.75rem;
        font-weight: 600;
    }
    .ga-badge-new { background: rgba(99,102,241,0.15); color: #818cf8; }
    .ga-badge-eligible { background: rgba(34,197,94,0.15); color: #4ade80; }
    .ga-badge-participated { background: rgba(14,165,233,0.15); color: #38bdf8; }
    .ga-badge-expired { background: rgba(107,114,128,0.15); color: #9ca3af; }
    .ga-badge-skipped { background: rgba(234,179,8,0.15); color: #facc15; }
    .ga-badge-not_eligible { background: rgba(239,68,68,0.15); color: #f87171; }
    .ga-badge-needs_review { background: rgba(251,146,60,0.15); color: #fb923c; }
    .ga-table .ga-muted { color: var(--text-tertiary); }

    /* Highlighted row (last-clicked giveaway) */
    .ga-row-clicked {
        background: rgba(99,102,241,0.08) !important;
        border-left: 3px solid var(--accent-primary) !important;
    }

    /* Vertically center columns in st.columns rows (fixes X button / link alignment) */
    [data-testid="stHorizontalBlock"] {
        align-items: center;
    }

    /* Account status cards */
    .account-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
        gap: 12px;
        margin-top: 8px;
    }
    .account-card {
        background: var(--bg-glass);
        border-radius: var(--radius-md);
        padding: 16px;
        border: 1px solid var(--border-subtle);
        display: flex;
        align-items: center;
        gap: 12px;
        transition: all var(--transition-base);
    }
    .account-card:hover {
        background: var(--bg-glass-hover);
        border-color: var(--border-default);
    }
    .account-card .acc-icon {
        width: 36px;
        height: 36px;
        border-radius: var(--radius-sm);
        display: flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        font-size: 1.2rem;
    }
    .account-card .acc-name {
        color: var(--text-primary);
        font-weight: 600;
        font-size: 0.85rem;
    }
    .account-card .acc-status {
        font-size: 0.75rem;
        font-weight: 600;
    }
    .acc-status-ok { color: var(--success); }
    .acc-status-warning { color: var(--warning); }
    .acc-status-error { color: var(--error); }
    .acc-status-unknown { color: var(--text-tertiary); }

    /* Urgency badges for deadlines */
    .urgency-critical { color: var(--error); font-weight: 700; }
    .urgency-soon { color: var(--warning); font-weight: 600; }
    .urgency-normal { color: var(--text-tertiary); }

    /* Entry stats bar */
    .entry-stats {
        display: flex;
        gap: 24px;
        background: var(--bg-glass);
        border-radius: var(--radius-md);
        padding: 16px 24px;
        border: 1px solid var(--border-subtle);
        margin-bottom: 16px;
    }
    .entry-stat {
        text-align: center;
    }
    .entry-stat .es-value {
        font-size: 1.5rem;
        font-weight: 800;
        color: var(--text-primary);
        line-height: 1;
    }
    .entry-stat .es-label {
        font-size: 0.7rem;
        color: var(--text-tertiary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 4px;
    }
    .es-success .es-value { color: var(--success); }
    .es-failed .es-value { color: var(--error); }
    .es-skipped .es-value { color: var(--warning); }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# JavaScript for highlighting last-clicked giveaway row
st.markdown("""
<script>
document.addEventListener('click', function(e) {
    var link = e.target.closest('a.ga-clickable');
    if (!link) return;
    // Remove highlight from all rows
    document.querySelectorAll('.ga-row-clicked').forEach(function(el) {
        el.classList.remove('ga-row-clicked');
    });
    // Highlight the clicked row (the parent stHorizontalBlock)
    var row = link.closest('[data-testid="stHorizontalBlock"]');
    if (row) {
        row.classList.add('ga-row-clicked');
    }
});
</script>
""", unsafe_allow_html=True)

SVG_ICONS = {
    "dashboard": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    "list": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>',
    "search": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    "bot": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="10" rx="2"/><circle cx="12" cy="5" r="2"/><path d="M12 7v4"/><line x1="8" y1="16" x2="8" y2="16"/><line x1="16" y1="16" x2="16" y2="16"/></svg>',
    "settings": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>',
    "gift": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 12 20 22 4 22 4 12"/><rect x="2" y="7" width="20" height="5"/><line x1="12" y1="22" x2="12" y2="7"/><path d="M12 7H7.5a2.5 2.5 0 0 1 0-5C11 2 12 7 12 7z"/><path d="M12 7h4.5a2.5 2.5 0 0 0 0-5C13 2 12 7 12 7z"/></svg>',
    "layers": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
    "check": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    "clock": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    "trending": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>',
    "external": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    "play": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
    "skip": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" y1="5" x2="19" y2="19"/></svg>',
    "refresh": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>',
    "trash": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    "globe": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>',
    "link": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
    "database": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
    "zap": '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
}



def scan_existing_entries():
    """Re-evaluate eligibility for giveaways with status 'new'.

    Uses an atomic UPDATE ... WHERE status = 'new' to avoid overwriting
    statuses that were already changed by the enrichment worker (e.g. to
    'expired' or 'not_eligible').
    """
    giveaways = get_giveaways(status="new")
    if not giveaways:
        return
    target_country = load_config().get("target_country", "germany")
    from database import get_connection
    conn = get_connection()
    try:
        cursor = conn.cursor()
        for g in giveaways:
            country = g.get("country_restriction", "worldwide")
            new_status = "eligible" if is_eligible_for_country(country, target_country) else "not_eligible"
            # Only update if status is still 'new' (atomic check to prevent race)
            cursor.execute(
                "UPDATE giveaways SET status = ? WHERE id = ? AND status = 'new'",
                (new_status, g["id"]),
            )
        conn.commit()
    finally:
        conn.close()


def rescan_all_eligibility():
    """Re-evaluate eligibility for ALL giveaways when the target country changes.

    Rechecks giveaways with status 'new', 'eligible', or 'not_eligible'.
    Does NOT touch 'participated', 'expired', or 'skipped' statuses.
    """
    target_country = load_config().get("target_country", "germany")
    from database import get_connection
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, country_restriction FROM giveaways WHERE status IN ('new', 'eligible', 'not_eligible')"
        )
        rows = cursor.fetchall()
        for row in rows:
            gid = row[0]
            country = row[1] or "worldwide"
            new_status = "eligible" if is_eligible_for_country(country, target_country) else "not_eligible"
            cursor.execute(
                "UPDATE giveaways SET status = ? WHERE id = ?",
                (new_status, gid),
            )
        conn.commit()
    finally:
        conn.close()


def run_enrichment_pipeline():
    """Dispatch the enrichment pipeline to the background worker.

    Returns immediately -- the UI polls the worker's progress via
    ``_enrichment_worker.snapshot()`` and shows a non-blocking indicator.
    If a previous run already completed, the worker is reset first so
    new imports get enriched.
    """
    _enrichment_worker.reset()
    _enrichment_worker.start()
    # Clear the notification flag so the UI shows a toast when this run finishes
    if hasattr(st, "session_state"):
        st.session_state["_enrich_notified"] = False


def run_enrichment_pipeline_blocking():
    """Run the full enrichment pipeline synchronously (blocks the UI).

    Kept for the manual "Fetch Deadlines" / "Check T&C" buttons on the
    Giveaways tab where the user expects to wait and see inline results.
    """
    unenriched = get_unenriched_giveaways()

    if not unenriched:
        return

    with st.status("Enriching giveaway data...", expanded=True) as status:
        total = len(unenriched)
        st.write(f"Enriching {total} giveaways (deadlines, T&C, status)...")
        urls = [g["url"] for g in unenriched]
        url_to_id = {g["url"]: g["id"] for g in unenriched}
        enriched = [0]
        ended_count = [0]
        blocked_count = [0]

        def _save_result(entry):
            gid = url_to_id.get(entry["url"])
            if not gid:
                return
            if entry.get("deadline"):
                update_giveaway_deadline(gid, entry["deadline"])
            # Only persist T&C if we actually checked (skip errors and email-blocked)
            if not entry.get("email_blocked") and not entry.get("error"):
                excluded_str = ",".join(entry["excluded"]) if entry.get("excluded") else ""
                update_terms_check(gid, True, excluded_str, entry.get("region"))
            if entry.get("ended"):
                update_giveaway_status(gid, "expired")
                ended_count[0] += 1
            elif entry.get("region_blocked"):
                update_giveaway_status(gid, "not_eligible")
                blocked_count[0] += 1
            elif entry.get("email_blocked"):
                update_giveaway_status(gid, "needs_review", notes="enrichment_blocked:email_subscribe")
            elif entry.get("error"):
                update_giveaway_status(gid, "needs_review", notes=f"enrichment_error:{entry['error'][:200]}")
            enriched[0] += 1

        try:
            enrich_giveaways_batch(urls, on_result=_save_result)
            parts = [f"Enriched {enriched[0]}/{total} giveaways."]
            if ended_count[0]:
                parts.append(f"{ended_count[0]} ended.")
            if blocked_count[0]:
                parts.append(f"{blocked_count[0]} region-blocked.")
            st.write(" ".join(parts))
        except Exception as e:
            st.write(f"Enrichment error: {e}")
            if enriched[0]:
                st.write(f"({enriched[0]} giveaway(s) were saved before the error.)")

        # Re-scan eligibility with updated data
        st.write("Scanning eligibility...")
        scan_existing_entries()

        # Remove any newly expired entries
        removed = remove_expired_giveaways()
        if removed:
            st.write(f"Removed {removed} expired giveaway(s).")

        status.update(label="Enrichment complete", state="complete", expanded=False)

    _cached_giveaways_display.clear()


def _check_accounts_status():
    """Check login status for social platforms by probing known URLs.

    Checks all 8 platforms in parallel using a thread pool to avoid
    up to 64 seconds of sequential HTTP waits.
    Results are stored in st.session_state.account_status.
    """
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    checks = {
        "gleam_io": {
            "url": "https://gleam.io/giveaways",
            "ok_hint": "gleam",
        },
        "x_twitter": {
            "url": "https://x.com",
            "ok_hint": "x.com",
        },
        "instagram": {
            "url": "https://www.instagram.com/",
            "ok_hint": "instagram",
        },
        "youtube": {
            "url": "https://www.youtube.com/",
            "ok_hint": "youtube",
        },
        "facebook": {
            "url": "https://www.facebook.com/",
            "ok_hint": "facebook",
        },
        "discord": {
            "url": "https://discord.com/channels/@me",
            "ok_hint": "discord",
        },
        "twitch": {
            "url": "https://www.twitch.tv/",
            "ok_hint": "twitch",
        },
        "tiktok": {
            "url": "https://www.tiktok.com/",
            "ok_hint": "tiktok",
        },
    }

    from utils.network import get_random_headers

    def _probe(key, info):
        try:
            resp = requests.get(info["url"], headers=get_random_headers(), timeout=8, allow_redirects=True)
            return key, resp.status_code
        except Exception:
            return key, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_probe, k, v): k for k, v in checks.items()}
        for future in as_completed(futures):
            key, status_code = future.result()
            name = st.session_state.account_status[key]["name"]
            if status_code == 200:
                st.session_state.account_status[key] = {
                    "name": name,
                    "status": "ok",
                    "detail": f"Reachable ({status_code})",
                }
            elif status_code is not None:
                st.session_state.account_status[key] = {
                    "name": name,
                    "status": "warning",
                    "detail": f"HTTP {status_code}",
                }
            else:
                st.session_state.account_status[key] = {
                    "name": name,
                    "status": "error",
                    "detail": "Unreachable",
                }


def import_ndjson_links():
    """Import gleam links from all gleam-links*.ndjson files in a directory.

    Scans the configured ndjson_import_dir (defaults to the project directory)
    for files matching ``gleam-links*.ndjson``, reads them all, adds any new
    gleam.io URLs to the database, then truncates each file so links are not
    re-imported.

    Backwards compatibility: if the old ``ndjson_import_path`` config key
    points to a file, its parent directory is used instead.

    Returns (imported_count, message) tuple.
    """
    config = load_config()

    # Resolve the import directory
    import_dir = config.get("ndjson_import_dir", "")

    # Backwards compat: honour old ndjson_import_path if ndjson_import_dir is empty
    if not import_dir:
        old_path = config.get("ndjson_import_path", "")
        if old_path:
            old_path = os.path.expanduser(old_path)
            if os.path.isfile(old_path):
                import_dir = os.path.dirname(old_path)
            elif os.path.isdir(old_path):
                import_dir = old_path
            else:
                # Treat as dir even if it doesn't exist yet
                import_dir = old_path

    if not import_dir:
        import_dir = os.path.dirname(__file__)
    else:
        import_dir = os.path.expanduser(import_dir)

    if not os.path.isdir(import_dir):
        return 0, f"Import directory not found: {import_dir}"

    # Find all matching NDJSON files
    pattern = os.path.join(import_dir, "gleam-links*.ndjson")
    files = sorted(_glob.glob(pattern))

    if not files:
        return 0, f"No gleam-links*.ndjson files found in {import_dir}"

    batch = []
    errors = []
    successfully_read = []
    for filepath in files:
        try:
            with open(filepath, "r", encoding="utf-8", errors="surrogateescape") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        # Re-encode with surrogatepass then decode with
                        # replace so lone surrogates become U+FFFD instead
                        # of crashing downstream (SQLite, Streamlit, etc.).
                        line = line.encode("utf-8", errors="surrogatepass") \
                                   .decode("utf-8", errors="replace")
                        entry = json.loads(line)
                        if not isinstance(entry, dict):
                            continue
                        href = entry.get("href", "")
                        text = entry.get("text", "")
                        deadline = entry.get("deadline", "")
                        # Validate gleam.io giveaway URL (host + path pattern)
                        if href and is_gleam_giveaway_url(href):
                            # Skip truncated URLs (contain ellipsis … or end with ...)
                            if "\u2026" in href or href.endswith("..."):
                                continue
                            batch.append({
                                "title": clean_title(text, href),
                                "url": href,
                                "source": "extension",
                                "deadline": deadline,
                            })
                    except json.JSONDecodeError:
                        continue
            successfully_read.append(filepath)
        except OSError as e:
            errors.append(f"{os.path.basename(filepath)}: {e}")

    if not batch and not errors:
        return 0, f"All {len(files)} file(s) are empty (no gleam.io links found)"

    imported = add_giveaways_batch(batch) if batch else 0

    # Truncate only files that were fully and successfully read
    for filepath in successfully_read:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                pass
        except OSError:
            pass

    parts = [f"Imported {imported} new links from {len(files)} file(s) ({len(batch)} total in files)"]
    if errors:
        parts.append(f"Errors: {'; '.join(errors)}")
    return imported, ". ".join(parts)


def main():
    # Optimistic removal: track IDs removed this session so they vanish
    # instantly without waiting for the DB cache to refresh.
    if "removed_giveaway_ids" not in st.session_state:
        st.session_state.removed_giveaway_ids = set()

    # One-time cleanup on first load: remove non-gleam URLs, truncated URLs,
    # non-giveaway paths (e.g. /terms, /privacy), and fix titles
    if "db_cleaned" not in st.session_state:
        non_gleam = remove_non_gleam_giveaways()
        truncated = remove_truncated_giveaways()
        non_giveaway = remove_non_giveaway_gleam_paths()
        title_fixes = cleanup_titles()
        st.session_state.db_cleaned = True
        if non_gleam or truncated or non_giveaway or title_fixes:
            _cached_giveaways_display.clear()

    # Remove expired giveaways on every page load (fast indexed SQL query)
    removed = remove_expired_giveaways()
    # Also expire giveaways whose title contains a past date (e.g. "Ends April 5th")
    title_expired = expire_by_title_date()
    if removed or title_expired:
        logger.info("page_load: cleaned up expired giveaways -- removed=%d, title_expired=%d",
                     removed, title_expired)
        _cached_giveaways_display.clear()

    # Auto-import links from the browser extension NDJSON file
    if "ndjson_imported" not in st.session_state:
        imported, msg = import_ndjson_links()
        st.session_state.ndjson_imported = imported
        if imported > 0:
            # Run full enrichment: deadlines, T&C, eligibility
            run_enrichment_pipeline()
            st.toast(f"Imported {imported} new links from extension")

    st.markdown(f"""
    <div class="main-header">
        <h1>🎁 Giveaway Tracker</h1>
        <p class="subtitle">Discover, track, and auto-enter Gleam.io giveaways</p>
    </div>
    """, unsafe_allow_html=True)

    # --- Invalidate display cache if background enrichment marked it dirty ---
    if _enrichment_worker.cache_dirty:
        _cached_giveaways_display.clear()
        _enrichment_worker.clear_cache_dirty()

    # --- Background enrichment progress indicator ---
    _enrich_snap = _enrichment_worker.snapshot()
    if _enrich_snap["running"]:
        _pct = _enrich_snap["progress"] / 100.0
        _step_text = _enrich_snap["step"] or "Enriching..."
        _detail_text = _enrich_snap["detail"]
        st.progress(_pct, text=f"{_step_text}  {_detail_text}")
        # Poll every 2 seconds while enrichment is running
        time.sleep(2)
        st.rerun()
    elif _enrich_snap["done"] and not st.session_state.get("_enrich_notified"):
        # Enrichment just finished — refresh data and notify once
        _cached_giveaways_display.clear()
        st.session_state["_enrich_notified"] = True
        if _enrich_snap["error"]:
            st.warning(f"Enrichment finished with errors: {_enrich_snap['error']}")
        else:
            st.toast("Background enrichment complete")
        st.rerun()

    tab_dashboard, tab_giveaways, tab_autoenter, tab_settings = st.tabs([
        " 🎁 Dashboard",
        " 📋 Giveaways",
        " 🤖 Auto-Enter",
        " ⚙️ Settings",
    ])

    with tab_dashboard:
        stats = get_stats()

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.markdown(f"""
            <div class="stat-card purple">
                <div class="stat-icon">{SVG_ICONS['layers']}</div>
                <h3>Total Giveaways</h3>
                <p class="value">{stats['total']}</p>
                <p class="sub">Discovered</p>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown(f"""
            <div class="stat-card green">
                <div class="stat-icon">{SVG_ICONS['check']}</div>
                <h3>Participated</h3>
                <p class="value">{stats['participated']}</p>
                <p class="sub">Entered</p>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            st.markdown(f"""
            <div class="stat-card blue">
                <div class="stat-icon">{SVG_ICONS['zap']}</div>
                <h3>Eligible</h3>
                <p class="value">{stats['eligible']}</p>
                <p class="sub">Ready to enter</p>
            </div>
            """, unsafe_allow_html=True)
        with col4:
            st.markdown(f"""
            <div class="stat-card orange">
                <div class="stat-icon">{SVG_ICONS['clock']}</div>
                <h3>New</h3>
                <p class="value">{stats['new']}</p>
                <p class="sub">Unprocessed</p>
            </div>
            """, unsafe_allow_html=True)
        with col5:
            prob = stats['avg_win_probability']
            st.markdown(f"""
            <div class="stat-card red">
                <div class="stat-icon">{SVG_ICONS['trending']}</div>
                <h3>Avg Win Chance</h3>
                <p class="value">{format_probability(prob)}</p>
                <p class="sub">Per giveaway</p>
            </div>
            """, unsafe_allow_html=True)

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(f'<div class="section-title">{SVG_ICONS["clock"]} Recent Giveaways</div>', unsafe_allow_html=True)
        recent = _cached_giveaways_display()[:10]
        if recent:
            badge_labels = {
                "new": "New", "eligible": "Eligible", "participated": "Participated",
                "not_eligible": "Not Eligible", "expired": "Expired", "skipped": "Skipped",
                "needs_review": "Needs Review",
            }
            html_rows = []
            for r in recent:
                title = html_escape(r.get("title", "Untitled"))
                url = html_escape(r.get("url", "#"), quote=True)
                status = r.get("status", "new")
                badge_label = badge_labels.get(status, status)
                discovered = ""
                if r.get("discovered_at"):
                    try:
                        discovered = datetime.fromisoformat(r["discovered_at"]).strftime("%Y-%m-%d %H:%M")
                    except (ValueError, TypeError):
                        discovered = str(r.get("discovered_at", ""))
                html_rows.append(f"""<tr>
                    <td><a class="ga-title" href="{url}" target="_blank" rel="noopener">{title}</a></td>
                    <td><span class="ga-badge ga-badge-{status}">{badge_label}</span></td>
                    <td class="ga-muted">{discovered}</td>
                </tr>""")
            table_html = f"""<table class="ga-table">
                <thead><tr>
                    <th>Title</th>
                    <th>Status</th>
                    <th>Discovered</th>
                </tr></thead>
                <tbody>{"".join(html_rows)}</tbody>
            </table>"""
            st.markdown(table_html, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="empty-state">
                <p>No giveaways found yet. Import links from the browser extension to get started!</p>
            </div>
            """, unsafe_allow_html=True)

        # --- Account Status Section ---
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(f'<div class="section-title">{SVG_ICONS["globe"]} Account Status</div>', unsafe_allow_html=True)

        # Load or initialize account status from session state
        if "account_status" not in st.session_state:
            st.session_state.account_status = {
                "gleam_io": {"name": "Gleam.io", "status": "unknown", "detail": "Not checked"},
                "x_twitter": {"name": "X / Twitter", "status": "unknown", "detail": "Not checked"},
                "instagram": {"name": "Instagram", "status": "unknown", "detail": "Not checked"},
                "youtube": {"name": "YouTube", "status": "unknown", "detail": "Not checked"},
                "facebook": {"name": "Facebook", "status": "unknown", "detail": "Not checked"},
                "discord": {"name": "Discord", "status": "unknown", "detail": "Not checked"},
                "twitch": {"name": "Twitch", "status": "unknown", "detail": "Not checked"},
                "tiktok": {"name": "TikTok", "status": "unknown", "detail": "Not checked"},
            }

        account_icons = {
            "gleam_io": "&#x1F3B0;",
            "x_twitter": "&#x1D54F;",
            "instagram": "&#x1F4F7;",
            "youtube": "&#x25B6;",
            "facebook": "&#x1F44D;",
            "discord": "&#x1F4AC;",
            "twitch": "&#x1F3AE;",
            "tiktok": "&#x1F3B5;",
        }

        status_class_map = {
            "ok": "acc-status-ok",
            "warning": "acc-status-warning",
            "error": "acc-status-error",
            "unknown": "acc-status-unknown",
        }

        status_label_map = {
            "ok": "Connected",
            "warning": "Check needed",
            "error": "Not logged in",
            "unknown": "Not checked",
        }

        cards_html = '<div class="account-grid">'
        for key, acc in st.session_state.account_status.items():
            icon = account_icons.get(key, "&#x2699;")
            sc = status_class_map.get(acc["status"], "acc-status-unknown")
            label = acc.get("detail", status_label_map.get(acc["status"], "Unknown"))
            cards_html += f"""
            <div class="account-card">
                <div class="acc-icon">{icon}</div>
                <div>
                    <div class="acc-name">{html_escape(acc["name"])}</div>
                    <div class="acc-status {sc}">{html_escape(label)}</div>
                </div>
            </div>"""
        cards_html += '</div>'
        st.markdown(cards_html, unsafe_allow_html=True)

        if st.button("Check Account Status", key="check_accounts"):
            with st.spinner("Checking accounts via browser profile..."):
                _check_accounts_status()
            st.rerun()

        # --- Quick Actions ---
        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
        st.markdown(f'<div class="section-title">{SVG_ICONS["zap"]} Quick Actions</div>', unsafe_allow_html=True)
        qa_col1, qa_col2 = st.columns(2)
        with qa_col1:
            if st.button("Import from Extension", type="primary", use_container_width=True, key="dash_import"):
                imported, msg = import_ndjson_links()
                if imported > 0:
                    run_enrichment_pipeline()
                    st.toast(msg)
                    _cached_giveaways_display.clear()
                    st.rerun()
                else:
                    st.info(msg)
        with qa_col2:
            eligible_count = stats.get("eligible", 0)
            if st.button(f"Enter All Eligible ({eligible_count})", use_container_width=True, key="dash_enter_all"):
                eligible = get_giveaways("eligible")
                entered = 0
                for g in eligible:
                    with st.spinner(f"Entering: {g['title'][:50]}..."):
                        result, log = auto_enter_giveaway(g["url"])
                        if result == "success":
                            update_giveaway_status(g["id"], "participated")
                            entered += 1
                        elif result == "region_restricted":
                            update_giveaway_status(g["id"], "not_eligible")
                        elif result == "ended":
                            update_giveaway_status(g["id"], "expired")
                st.toast(f"Entered {entered} giveaways")
                _cached_giveaways_display.clear()
                st.rerun()

        # --- Entry Session Stats ---
        if "entry_stats" not in st.session_state:
            st.session_state.entry_stats = {"entered": 0, "failed": 0, "skipped": 0}

        es = st.session_state.entry_stats
        if es["entered"] + es["failed"] + es["skipped"] > 0:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f'<div class="section-title">{SVG_ICONS["trending"]} Session Entry Stats</div>', unsafe_allow_html=True)
            st.markdown(f"""
            <div class="entry-stats">
                <div class="entry-stat es-success">
                    <div class="es-value">{es['entered']}</div>
                    <div class="es-label">Entered</div>
                </div>
                <div class="entry-stat es-failed">
                    <div class="es-value">{es['failed']}</div>
                    <div class="es-label">Failed</div>
                </div>
                <div class="entry-stat es-skipped">
                    <div class="es-value">{es['skipped']}</div>
                    <div class="es-label">Skipped</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

    with tab_giveaways:
        st.markdown(f'<div class="section-title">{SVG_ICONS["list"]} All Giveaways</div>', unsafe_allow_html=True)

        filter_col1, filter_col2 = st.columns([1, 3])
        with filter_col1:
            status_filter = st.selectbox(
                "Filter by status",
                ["all", "new", "eligible", "participated", "not_eligible", "expired", "skipped", "needs_review"]
            )

        @st.fragment
        def _render_giveaway_table():
            """Fragment-wrapped giveaway table — only this section reruns on X click."""
            giveaways = _cached_giveaways_display(exclude_not_eligible=False) if status_filter == "all" else _cached_giveaways_display(status=status_filter)

            if not giveaways:
                st.caption("No giveaways found.")
                return

            df = pd.DataFrame(giveaways)

            # In the "all" view, hide expired giveaways (they stay in the DB
            # to prevent re-import, but should not clutter the main view).
            # Users can still view them via the "expired" status filter.
            if status_filter == "all":
                df = df[df["status"] != "expired"]

            # Optimistic removal: hide rows the user already clicked X on,
            # even if the cached query still contains them.
            removed = st.session_state.removed_giveaway_ids
            if removed:
                df = df[~df["id"].isin(removed)]
            if df.empty:
                st.caption("No giveaways found.")
                return

            # Vectorized sorting: map country_restriction to numeric order
            country_order = {"germany": 0, "dach": 1, "eu": 2, "worldwide": 3, "restricted": 4}
            df["_country_score"] = df["country_restriction"].map(country_order).fillna(5)

            # Penalty for Germany-excluded T&C
            def _terms_penalty(row):
                if row.get("terms_checked") and row.get("terms_excluded"):
                    excluded_list = [e.strip().lower() for e in row["terms_excluded"].split(",")]
                    if "germany" in excluded_list:
                        return 20
                return 0
            df["_terms_penalty"] = df.apply(_terms_penalty, axis=1)

            # Penalty for unchecked T&C
            df["_unchecked_penalty"] = (~df["terms_checked"].astype(bool)).astype(int) * 5

            # Deadline urgency bonus: giveaways ending soon should be entered first
            from database import parse_deadline
            now = datetime.now()

            def _deadline_urgency(row):
                dl = row.get("deadline", "")
                dt = parse_deadline(dl)
                if not dt:
                    return 3  # unknown deadline = neutral
                hours_left = (dt - now).total_seconds() / 3600
                if hours_left < 0:
                    return 100  # expired, push to bottom
                if hours_left < 24:
                    return -2  # critical urgency, push to top
                if hours_left < 72:
                    return -1  # ending soon
                return 3
            df["_deadline_urgency"] = df.apply(_deadline_urgency, axis=1)

            df["_sort_order"] = df["_country_score"] + df["_terms_penalty"] + df["_unchecked_penalty"] + df["_deadline_urgency"]
            df = df.sort_values("_sort_order").drop(columns=["_sort_order", "_country_score", "_terms_penalty", "_unchecked_penalty", "_deadline_urgency"])

            # Status badge mapping
            badge_labels = {
                "new": "New", "eligible": "Eligible", "participated": "Participated",
                "not_eligible": "Not Eligible", "expired": "Expired", "skipped": "Skipped",
                "needs_review": "Needs Review",
            }

            # Split: separate not-eligible from the rest when showing "all"
            if status_filter == "all":
                df_main = df[df["status"] != "not_eligible"]
                df_not_eligible = df[df["status"] == "not_eligible"]
            else:
                df_main = df
                df_not_eligible = pd.DataFrame()

            # --- Render main giveaway table with inline X buttons ---
            def _render_giveaway_rows(rows_df, key_prefix=""):
                """Render giveaway rows with inline remove buttons."""
                for _, row in rows_df.iterrows():
                    title = row.get("title", "Untitled")
                    url = row.get("url", "#")
                    status = row.get("status", "new")
                    badge_label = badge_labels.get(status, status)
                    win_chance = format_probability(row["win_probability"]) if row.get("total_entries", 0) > 0 else "---"
                    gid = row["id"]

                    # Deadline with countdown
                    raw_deadline = row.get("deadline", "") or ""
                    dl_dt = parse_deadline(raw_deadline)
                    if dl_dt:
                        hours_left = (dl_dt - now).total_seconds() / 3600
                        if hours_left < 0:
                            countdown = "EXPIRED"
                            urgency_class = "urgency-critical"
                        elif hours_left < 1:
                            mins_left = max(0, int((dl_dt - now).total_seconds() / 60))
                            countdown = f"{mins_left}m left"
                            urgency_class = "urgency-critical"
                        elif hours_left < 24:
                            h = int(hours_left)
                            countdown = f"{h}h left"
                            urgency_class = "urgency-critical"
                        elif hours_left < 72:
                            d = int(hours_left / 24)
                            h = int(hours_left % 24)
                            countdown = f"{d}d {h}h left"
                            urgency_class = "urgency-soon"
                        else:
                            d = int(hours_left / 24)
                            countdown = f"{d}d left"
                            urgency_class = "urgency-normal"
                    else:
                        countdown = "---"
                        urgency_class = "urgency-normal"

                    # Row layout: X button | Title | Status | Win Chance | Deadline
                    col_remove, col_title, col_status, col_chance, col_deadline = st.columns([0.5, 5, 1.5, 1.2, 1.5])
                    with col_remove:
                        if st.button("✗", key=f"{key_prefix}bl_{gid}", help="Remove & blacklist"):
                            st.session_state.removed_giveaway_ids.add(gid)
                            add_to_blacklist(url, "Manually blacklisted")
                            try:
                                st.rerun(scope="fragment")
                            except st.errors.StreamlitAPIException:
                                st.rerun()
                    with col_title:
                        st.markdown(f'<a class="ga-title ga-clickable" href="{html_escape(url, quote=True)}" target="_blank" rel="noopener">{html_escape(title)}</a>', unsafe_allow_html=True)
                    with col_status:
                        st.markdown(f'<span class="ga-badge ga-badge-{status}">{badge_label}</span>', unsafe_allow_html=True)
                    with col_chance:
                        st.markdown(f"<small>{win_chance}</small>", unsafe_allow_html=True)
                    with col_deadline:
                        st.markdown(f'<span class="{urgency_class}">{countdown}</span>', unsafe_allow_html=True)

            # Table header
            hdr_rm, hdr_title, hdr_status, hdr_chance, hdr_deadline = st.columns([0.5, 5, 1.5, 1.2, 1.5])
            with hdr_rm:
                st.markdown("")
            with hdr_title:
                st.markdown("**Title**")
            with hdr_status:
                st.markdown("**Status**")
            with hdr_chance:
                st.markdown("**Win %**")
            with hdr_deadline:
                st.markdown("**Deadline**")

            if not df_main.empty:
                _render_giveaway_rows(df_main)
            elif status_filter != "all":
                st.caption("No giveaways in this category.")

            # --- Not-eligible sub-section (only when showing "all") ---
            if not df_not_eligible.empty:
                st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
                ne_header_col, ne_action_col = st.columns([4, 1])
                with ne_header_col:
                    st.markdown(f'<div class="section-title">Not Eligible ({len(df_not_eligible)})</div>', unsafe_allow_html=True)
                with ne_action_col:
                    if st.button("🗑 Delete All Not Eligible", key="del_all_ne", use_container_width=True):
                        ne_ids = set(df_not_eligible["id"].tolist())
                        st.session_state.removed_giveaway_ids.update(ne_ids)
                        deleted = delete_not_eligible()
                        _cached_giveaways_display.clear()
                        st.success(f"Deleted {deleted} not-eligible giveaways.")
                        try:
                            st.rerun(scope="fragment")
                        except st.errors.StreamlitAPIException:
                            st.rerun()
                with st.expander("Review not-eligible giveaways", expanded=False):
                    _render_giveaway_rows(df_not_eligible, key_prefix="ne_")

        _render_giveaway_table()

        giveaways = _cached_giveaways_display(exclude_not_eligible=False) if status_filter == "all" else _cached_giveaways_display(status=status_filter)
        if giveaways:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Actions</div>', unsafe_allow_html=True)

            # Disable Playwright-dependent buttons while background enrichment is active
            _enrichment_busy = _enrichment_worker.running

            action_col1, action_col2 = st.columns(2)
            with action_col1:
                if st.button("🔄 Enrich All", use_container_width=True, disabled=_enrichment_busy):
                    unenriched = [g for g in giveaways
                                  if not g.get("terms_checked") or not g.get("deadline")]
                    if not unenriched:
                        st.info("All giveaways already enriched.")
                    else:
                        total = len(unenriched)
                        st.info(f"Enriching {total} giveaways (deadlines, T&C, status)...")
                        enrich_urls = [g["url"] for g in unenriched]
                        url_to_id = {g["url"]: g["id"] for g in unenriched}
                        ended_count = [0]
                        blocked_count = [0]

                        def _save_enrich(entry):
                            gid = url_to_id.get(entry["url"])
                            if not gid:
                                return
                            if entry.get("deadline"):
                                update_giveaway_deadline(gid, entry["deadline"])
                            # Only persist T&C if we actually checked (skip errors and email-blocked)
                            if not entry.get("email_blocked") and not entry.get("error"):
                                excluded_str = ",".join(entry["excluded"]) if entry.get("excluded") else ""
                                update_terms_check(gid, True, excluded_str, entry.get("region"))
                            if entry.get("ended"):
                                update_giveaway_status(gid, "expired")
                                ended_count[0] += 1
                            elif entry.get("region_blocked"):
                                update_giveaway_status(gid, "not_eligible")
                                blocked_count[0] += 1
                            elif entry.get("email_blocked"):
                                update_giveaway_status(gid, "needs_review", notes="enrichment_blocked:email_subscribe")
                            elif entry.get("error"):
                                update_giveaway_status(gid, "needs_review", notes=f"enrichment_error:{entry['error'][:200]}")

                        try:
                            enrich_giveaways_batch(enrich_urls, on_result=_save_enrich)
                        except Exception as e:
                            st.error(f"Enrichment failed: {e}")
                            return
                        parts = [f"Enriched {total} giveaways!"]
                        if ended_count[0]:
                            parts.append(f"{ended_count[0]} ended.")
                        if blocked_count[0]:
                            parts.append(f"{blocked_count[0]} region-blocked.")
                        st.success(" ".join(parts))
                        scan_existing_entries()
                        _cached_giveaways_display.clear()
                        st.rerun()
            with action_col2:
                if st.session_state.get("confirm_clear_all"):
                    st.warning("This will delete all giveaway data. Are you sure?")
                    confirm_col1, confirm_col2 = st.columns(2)
                    with confirm_col1:
                        if st.button("Yes, delete everything", type="primary", use_container_width=True):
                            conn = get_connection()
                            conn.execute("DELETE FROM giveaways")
                            conn.commit()
                            conn.close()
                            _cached_giveaways_display.clear()
                            st.session_state["confirm_clear_all"] = False
                            st.success("All data cleared!")
                            st.rerun()
                    with confirm_col2:
                        if st.button("Cancel", use_container_width=True):
                            st.session_state["confirm_clear_all"] = False
                            st.rerun()
                else:
                    if st.button("🗑️ Clear All Data", use_container_width=True):
                        st.session_state["confirm_clear_all"] = True
                        st.rerun()

            st.markdown("---")

        else:
            st.markdown(f"""
            <div class="empty-state">
                <p>No giveaways in this category.</p>
            </div>
            """, unsafe_allow_html=True)

    with tab_autoenter:
        st.markdown(f'<div class="section-title">{SVG_ICONS["bot"]} Auto-Enter Giveaways</div>', unsafe_allow_html=True)

        config = load_config()
        auto_enabled = config.get("auto_enter_enabled", True)

        auto_toggle = st.toggle("Enable Auto-Enter", value=auto_enabled)
        if auto_toggle != auto_enabled:
            config["auto_enter_enabled"] = auto_toggle
            save_config(config)

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

        @st.fragment
        def _render_eligible_giveaways():
            eligible = get_giveaways("eligible")
            if eligible:
                # Sort by deadline urgency: soonest-ending first
                from database import parse_deadline as _pd
                _now = datetime.now()
                def _dl_sort_key(g):
                    dt = _pd(g.get("deadline", ""))
                    if dt:
                        return dt
                    return datetime.max  # unknown deadlines go last
                eligible = sorted(eligible, key=_dl_sort_key)

                st.markdown(f'<div class="section-title">Eligible Giveaways ({len(eligible)})</div>', unsafe_allow_html=True)

                for g in eligible:
                    # Compute countdown text
                    dl_dt = _pd(g.get("deadline", ""))
                    if dl_dt:
                        hrs = (dl_dt - _now).total_seconds() / 3600
                        if hrs < 0:
                            dl_text = "EXPIRED"
                        elif hrs < 1:
                            mins = max(0, int((dl_dt - _now).total_seconds() / 60))
                            dl_text = f"{mins}m left"
                        elif hrs < 24:
                            dl_text = f"{int(hrs)}h left"
                        elif hrs < 72:
                            dl_text = f"{int(hrs/24)}d {int(hrs%24)}h left"
                        else:
                            dl_text = f"{int(hrs/24)}d left"
                    else:
                        dl_text = ""

                    col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                    with col1:
                        st.markdown(f"""
                        <div class="giveaway-card">
                            <div class="giveaway-title">{html_escape(g['title'][:80])}</div>
                            <div class="giveaway-meta">
                                <span>Source: {html_escape(g['source'])}</span>
                                <span>Region: {html_escape(g['country_restriction'])}</span>
                                {f'<span class="urgency-soon">{html_escape(dl_text)}</span>' if dl_text else ''}
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    with col2:
                        st.link_button("🔗 Open", g["url"])
                    with col3:
                        if st.button("▶️ Enter", key=f"enter_{g['id']}"):
                            if "entry_stats" not in st.session_state:
                                st.session_state.entry_stats = {"entered": 0, "failed": 0, "skipped": 0}
                            with st.spinner("Auto-entering..."):
                                result, log = auto_enter_giveaway(g["url"])
                                if result == "region_restricted":
                                    update_giveaway_status(g["id"], "not_eligible")
                                    st.session_state.entry_stats["failed"] += 1
                                    st.error("Region restricted! This giveaway is not available in your country.")
                                elif result == "ended":
                                    update_giveaway_status(g["id"], "expired")
                                    st.session_state.entry_stats["failed"] += 1
                                    st.error("This competition has ended!")
                                elif result == "success":
                                    update_giveaway_status(g["id"], "participated")
                                    st.session_state.entry_stats["entered"] += 1
                                    st.success("Entered successfully!")
                                else:
                                    st.session_state.entry_stats["failed"] += 1
                                    st.warning("Entry may have failed. Check the log.")
                                st.session_state.entry_log = log
                    with col4:
                        if st.button("⏭️ Skip", key=f"skip_{g['id']}"):
                            if "entry_stats" not in st.session_state:
                                st.session_state.entry_stats = {"entered": 0, "failed": 0, "skipped": 0}
                            st.session_state.entry_stats["skipped"] += 1
                            update_giveaway_status(g["id"], "skipped")
                            st.rerun()

                if st.button("⚡ Auto-Enter ALL Eligible", type="primary", use_container_width=True):
                    if "entry_stats" not in st.session_state:
                        st.session_state.entry_stats = {"entered": 0, "failed": 0, "skipped": 0}
                    for g in eligible:
                        with st.spinner(f"Entering: {g['title'][:60]}..."):
                            result, log = auto_enter_giveaway(g["url"])
                            if result == "region_restricted":
                                update_giveaway_status(g["id"], "not_eligible")
                                st.session_state.entry_stats["failed"] += 1
                                st.error(f"Region restricted: {g['title'][:60]}")
                            elif result == "ended":
                                update_giveaway_status(g["id"], "expired")
                                st.session_state.entry_stats["failed"] += 1
                                st.error(f"Ended: {g['title'][:60]}")
                            elif result == "success":
                                update_giveaway_status(g["id"], "participated")
                                st.session_state.entry_stats["entered"] += 1
                                st.success(f"Entered: {g['title'][:60]}")
                            else:
                                st.session_state.entry_stats["failed"] += 1
                                st.warning(f"Failed: {g['title'][:60]}")
                    st.rerun()
            else:
                st.markdown(f"""
                <div class="empty-state">
                    <p>No eligible giveaways found. Import links from the extension first!</p>
                </div>
                """, unsafe_allow_html=True)

        _render_eligible_giveaways()

        if st.session_state.get("entry_log"):
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f'<div class="section-title">{SVG_ICONS["list"]} Entry Log</div>', unsafe_allow_html=True)
            for entry in st.session_state.entry_log[-20:]:
                log_class = "log-entry"
                if "success" in entry.lower() or "completed" in entry.lower():
                    log_class += " log-success"
                elif "error" in entry.lower() or "failed" in entry.lower():
                    log_class += " log-error"
                elif "captcha" in entry.lower() or "timeout" in entry.lower():
                    log_class += " log-warning"
                st.markdown(f'<div class="{log_class}">{html_escape(entry)}</div>', unsafe_allow_html=True)

    with tab_settings:
        st.markdown(f'<div class="section-title">{SVG_ICONS["settings"]} Settings</div>', unsafe_allow_html=True)

        config = load_config()

        st.markdown('<div class="settings-section">', unsafe_allow_html=True)
        st.markdown(f'<h3>{SVG_ICONS["globe"]} Target Country</h3>', unsafe_allow_html=True)
        countries = {
            "germany": "Germany",
            "dach": "DACH (Germany, Austria, Switzerland)",
            "eu": "European Union",
            "worldwide": "Worldwide Only",
            "us": "United States",
            "uk": "United Kingdom",
        }
        tc = config.get("target_country", "germany")
        country_keys = list(countries.keys())
        selected_country = st.selectbox(
            "Your country for eligibility check",
            options=country_keys,
            format_func=lambda x: countries[x],
            index=country_keys.index(tc) if tc in countries else 0
        )
        if selected_country != config.get("target_country"):
            config["target_country"] = selected_country
            save_config(config)
            # Re-evaluate eligibility for all giveaways with the new country
            rescan_all_eligibility()
            _cached_giveaways_display.clear()
            st.success("Country updated! Eligibility re-evaluated.")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-section">', unsafe_allow_html=True)
        st.markdown(f'<h3>{SVG_ICONS["database"]} Database</h3>', unsafe_allow_html=True)
        db_stats = get_stats()
        st.markdown(f"""
        <div class="db-info">
            <p>Total giveaways in database: <strong style="color: var(--text-primary);">{db_stats['total']}</strong></p>
            <p>Database file: <code>{os.path.join(os.path.dirname(__file__), 'giveaways.db')}</code></p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-section">', unsafe_allow_html=True)
        st.markdown(f'<h3>{SVG_ICONS["link"]} Extension Import</h3>', unsafe_allow_html=True)
        current_import_dir = config.get("ndjson_import_dir", "")
        import_dir = st.text_input(
            "NDJSON import directory",
            value=current_import_dir,
            placeholder="~/Downloads",
            help="Directory containing gleam-links*.ndjson files exported by the "
                 "Gleam Link Monitor extension. All matching files (e.g. "
                 "gleam-links.ndjson, gleam-links (1).ndjson) are imported when "
                 "the app starts. Leave empty to use the project directory.",
        )
        if import_dir != current_import_dir:
            config["ndjson_import_dir"] = os.path.expanduser(import_dir) if import_dir else ""
            save_config(config)
            st.success("Import directory updated!")
        st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
