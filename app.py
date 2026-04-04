import streamlit as st
import pandas as pd
from datetime import datetime
import threading
import queue
import time
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from database import init_db, add_giveaway, get_giveaways, update_giveaway_status, get_stats, update_giveaway_entries, get_giveaway_by_url, delete_not_eligible, update_terms_check, add_to_blacklist, get_blacklist, remove_from_blacklist
from config import load_config, save_config, add_custom_site, remove_custom_site, get_custom_sites
from crawler.gleamfinder import GleamfinderCrawler
from crawler.gleam_official import GleamOfficialCrawler
from crawler.bestofgleam import BestOfGleamCrawler
from crawler.gleamdb import GleamDBCrawler
from crawler.custom_sites import CustomSitesCrawler
from entry.auto_enter import auto_enter_giveaway, check_giveaway_terms
from utils.country_check import is_eligible_for_country
from utils.probability import format_probability

init_db()

st.set_page_config(
    page_title="Giveaway Tracker",
    page_icon="🎁",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

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
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

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


def run_crawl(crawl_sources, custom_sites_list, progress_placeholder):
    new_count = 0
    eligible_count = 0
    total_found = 0
    target_country = load_config().get("target_country", "germany")
    crawl_status = {}

    crawlers = []
    if "gleamfinder" in crawl_sources:
        crawlers.append(GleamfinderCrawler())
    if "gleam_official" in crawl_sources:
        crawlers.append(GleamOfficialCrawler())
    if "bestofgleam" in crawl_sources:
        crawlers.append(BestOfGleamCrawler())
    if "gleamdb" in crawl_sources:
        crawlers.append(GleamDBCrawler())
    if custom_sites_list:
        crawlers.append(CustomSitesCrawler())

    total_crawlers = len(crawlers)
    for i, crawler in enumerate(crawlers):
        progress_placeholder.progress((i / total_crawlers), text=f"Crawling {crawler.name}...")
        source_count = 0
        this_status = {"status": "unknown", "count": 0, "error": ""}
        try:
            if crawler.name == "custom_sites":
                giveaways = crawler.extract_giveaways(custom_sites_list)
            else:
                giveaways = crawler.extract_giveaways()

            st.info(f"{crawler.name}: Found {len(giveaways)} giveaways")
            this_status["status"] = "ok"
            this_status["count"] = len(giveaways)

            for g in giveaways:
                total_found += 1
                source_count += 1
                is_new = add_giveaway(
                    g["title"], g["url"], g["source"],
                    g.get("description", ""), g.get("deadline", ""),
                    g.get("country_restriction", "worldwide")
                )
                if is_new:
                    new_count += 1
                    existing = get_giveaway_by_url(g["url"])
                    if existing and is_eligible_for_country(existing.get("country_restriction", "worldwide"), target_country):
                        eligible_count += 1
        except Exception as e:
            st.error(f"Crawler {crawler.name} failed: {e}")
            this_status["status"] = "failed"
            this_status["error"] = str(e)
        finally:
            crawl_status[crawler.name] = this_status

    try:
        if hasattr(st, "session_state"):
            st.session_state["crawl_status"] = crawl_status
    except Exception:
        pass
    return new_count, eligible_count, total_found


def scan_existing_entries():
    giveaways = get_giveaways()
    target_country = load_config().get("target_country", "germany")

    for g in giveaways:
        if g["status"] == "new":
            country = g.get("country_restriction", "worldwide")
            if is_eligible_for_country(country, target_country):
                update_giveaway_status(g["id"], "eligible")
            else:
                update_giveaway_status(g["id"], "not_eligible")


def main():
    if "crawl_running" not in st.session_state:
        st.session_state.crawl_running = False
    if "crawl_log" not in st.session_state:
        st.session_state.crawl_log = []
    if "crawl_new_count" not in st.session_state:
        st.session_state.crawl_new_count = 0

    st.markdown(f"""
    <div class="main-header">
        <h1>🎁 Giveaway Tracker</h1>
        <p class="subtitle">Discover, track, and auto-enter Gleam.io giveaways</p>
    </div>
    """, unsafe_allow_html=True)

    tab_dashboard, tab_giveaways, tab_crawl, tab_autoenter, tab_settings = st.tabs([
        " 🎁 Dashboard",
        " 📋 Giveaways",
        " 🔎 Crawl",
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
        recent = get_giveaways()[:10]
        if recent:
            df = pd.DataFrame(recent)
            df_display = df[["title", "source", "country_restriction", "status", "discovered_at"]].copy()
            df_display["discovered_at"] = pd.to_datetime(df_display["discovered_at"]).dt.strftime("%Y-%m-%d %H:%M")
            df_display.columns = ["Title", "Source", "Region", "Status", "Discovered"]
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.markdown(f"""
            <div class="empty-state">
                <p>No giveaways found yet. Run a crawl to get started!</p>
            </div>
            """, unsafe_allow_html=True)

    with tab_giveaways:
        st.markdown(f'<div class="section-title">{SVG_ICONS["list"]} All Giveaways</div>', unsafe_allow_html=True)

        filter_col1, filter_col2 = st.columns([1, 3])
        with filter_col1:
            status_filter = st.selectbox(
                "Filter by status",
                ["all", "new", "eligible", "participated", "not_eligible", "expired", "skipped"]
            )

        giveaways = get_giveaways() if status_filter == "all" else get_giveaways(status=status_filter)

        if giveaways:
            df = pd.DataFrame(giveaways)

            def sort_key(row):
                country = row.get("country_restriction", "worldwide")
                order = {"germany": 0, "dach": 1, "eu": 2, "worldwide": 3, "restricted": 4}
                base = order.get(country, 5)
                
                if row.get("terms_checked"):
                    excluded = row.get("terms_excluded", "")
                    if excluded:
                        excluded_list = [e.strip().lower() for e in excluded.split(",")]
                        # Heavy penalty if Germany itself is excluded
                        if "germany" in excluded_list:
                            base += 20
                        # Moderate penalty if only non-DACH/non-EU countries are excluded
                        # (good sign -- means Germany is likely eligible)
                        non_eu_countries = ["us", "uk", "canada", "australia", "japan", "china", "brazil", "india"]
                        if not any(c in excluded_list for c in ["germany", "austria", "switzerland"]):
                            if any(c in excluded_list for c in non_eu_countries):
                                pass  # No penalty -- these exclusions don't affect Germany
                
                if not row.get("terms_checked"):
                    base += 5
                
                return base

            df["_sort_order"] = df.apply(sort_key, axis=1)
            df = df.sort_values("_sort_order").drop(columns=["_sort_order"])

            def status_badge(status):
                badges = {
                    "new": "New",
                    "eligible": "Eligible",
                    "participated": "Participated",
                    "not_eligible": "Not Eligible",
                    "expired": "Expired",
                    "skipped": "Skipped",
                }
                return badges.get(status, status)

            def terms_status(row):
                if row.get("terms_checked"):
                    excluded = row.get("terms_excluded", "")
                    if excluded:
                        return f"Excluded: {excluded}"
                    return "✓ Checked"
                return "✗ Not Checked"

            df["Status"] = df["status"].apply(status_badge)
            df["T&C"] = df.apply(terms_status, axis=1)
            df["Win Chance"] = df.apply(
                lambda r: format_probability(r["win_probability"]) if r["total_entries"] > 0 else "—",
                axis=1
            )

            display_cols = ["title", "source", "T&C", "Status", "Win Chance", "deadline", "url"]
            available_cols = [c for c in display_cols if c in df.columns]
            df_display = df[available_cols].copy()
            df_display.columns = ["Title", "Source", "T&C", "Status", "Win Chance", "Deadline", "URL"]

            st.dataframe(df_display, use_container_width=True, hide_index=True)

            st.markdown("---")
            for idx, row in df.iterrows():
                col_title, col_btn = st.columns([6, 1])
                with col_title:
                    st.caption(f"**{row.get('title', '')[:50]}** - {row.get('url', '')[:60]}")
                with col_btn:
                    if st.button("✗", key=f"bl_{row['id']}"):
                        add_to_blacklist(row["url"], "Manually blacklisted")
                        st.rerun()

            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Actions</div>', unsafe_allow_html=True)
            action_col1, action_col2, action_col3 = st.columns(3)
            with action_col1:
                if st.button("🔄 Check T&C", use_container_width=True):
                    st.info("Opening browser to check Terms & Conditions... This may take a while.")
                    checked_count = 0
                    for g in giveaways:
                        if not g.get("terms_checked"):
                            excluded, detected_region, _ = check_giveaway_terms(g["url"])
                            excluded_str = ",".join(excluded) if excluded else ""
                            update_terms_check(g["id"], True, excluded_str, detected_region)
                            checked_count += 1
                    st.success(f"Checked T&C for {checked_count} giveaways!")
                    # Re-evaluate eligibility after T&C updates
                    scan_existing_entries()
                    st.rerun()
            with action_col2:
                if st.button("🔄 Refresh Eligibility", use_container_width=True):
                    scan_existing_entries()
                    st.rerun()
            with action_col3:
                if st.button("🗑️ Clear All Data", use_container_width=True):
                    st.warning("This will delete all giveaway data. Are you sure?")
                    if st.button("Yes, delete everything", type="primary"):
                        import sqlite3
                        conn = sqlite3.connect("giveaways.db")
                        conn.execute("DELETE FROM giveaways")
                        conn.commit()
                        conn.close()
                        st.success("All data cleared!")
                        st.rerun()

            st.markdown("---")

        else:
            st.markdown(f"""
            <div class="empty-state">
                <p>No giveaways in this category.</p>
            </div>
            """, unsafe_allow_html=True)

    with tab_crawl:
        st.markdown(f'<div class="section-title">{SVG_ICONS["search"]} Crawl for Giveaways</div>', unsafe_allow_html=True)

        config = load_config()
        crawl_sources = config.get("crawl_sources", [])
        custom_sites = config.get("custom_sites", [])

        st.markdown('<div class="settings-section">', unsafe_allow_html=True)
        st.markdown(f'<h3>{SVG_ICONS["link"]} Active Sources</h3>', unsafe_allow_html=True)
        for source in crawl_sources:
            st.markdown(f"""
            <div class="source-card">
                <div class="source-icon">{SVG_ICONS['globe']}</div>
                <div>
                    <div class="source-name">{source.replace('_', ' ').title()}</div>
                    <div class="source-status">Configured and ready</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        if custom_sites:
            st.markdown(f"""
            <div class="source-card">
                <div class="source-icon">{SVG_ICONS['link']}</div>
                <div>
                    <div class="source-name">Custom Sites</div>
                    <div class="source-status">{len(custom_sites)} site(s) configured</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
        if not crawl_sources and not custom_sites:
            st.markdown('<p style="color: var(--text-tertiary); font-size: 0.875rem;">No sources configured. Add sources in Settings.</p>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        if st.button("Start Crawl", type="primary", use_container_width=True, disabled=st.session_state.crawl_running):
            st.session_state.crawl_running = True
            st.session_state.crawl_new_count = 0
            progress_placeholder = st.empty()
            status_placeholder = st.empty()

            new_count, eligible_count, total_found = run_crawl(
                crawl_sources, custom_sites, progress_placeholder
            )

            st.session_state.crawl_new_count = new_count
            st.session_state.crawl_running = False

            progress_placeholder.progress(1.0, text="Crawl complete!")
            statuses = getattr(st.session_state, 'crawl_status', None)
            if statuses:
                st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
                st.markdown('<div class="section-title">Crawl Summary</div>', unsafe_allow_html=True)
                for name, s in statuses.items():
                    badge_color = '#10b981' if s.get('status') == 'ok' else '#ef4444'
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:12px;margin:8px 0;'>"
                        f"<span style='font-weight:600;color:var(--text-primary);'>{name}</span>"
                        f"<span style='background:{badge_color};color:white;padding:4px 10px;border-radius:999px;font-size:0.75rem;font-weight:600;'>"
                        f"{s.get('status', 'unknown').upper()}"
                        f"</span>"
                        f"<span style='color:var(--text-tertiary);font-size:0.8rem;'>{s.get('count', 0)} found</span>"
                        f"<span style='color:var(--text-tertiary);font-size:0.8rem;'>{s.get('error','')}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            status_placeholder.markdown(f"""
            <div class="results-summary">
                <div class="results-title">{SVG_ICONS['check']} Crawl Finished</div>
                <div class="results-detail">
                    Found <strong>{total_found}</strong> giveaways total,
                    <strong>{new_count}</strong> new added,
                    <strong>{eligible_count}</strong> eligible for your region
                </div>
            </div>
            """, unsafe_allow_html=True)

            scan_existing_entries()
            st.rerun()

        if st.session_state.crawl_running:
            st.info("Crawl in progress... Please wait.")

    with tab_autoenter:
        st.markdown(f'<div class="section-title">{SVG_ICONS["bot"]} Auto-Enter Giveaways</div>', unsafe_allow_html=True)

        config = load_config()
        auto_enabled = config.get("auto_enter_enabled", True)

        auto_toggle = st.toggle("Enable Auto-Enter", value=auto_enabled)
        if auto_toggle != auto_enabled:
            config["auto_enter_enabled"] = auto_toggle
            save_config(config)

        st.markdown('<hr class="section-divider">', unsafe_allow_html=True)

        eligible = get_giveaways("eligible")
        if eligible:
            st.markdown(f'<div class="section-title">Eligible Giveaways ({len(eligible)})</div>', unsafe_allow_html=True)

            for g in eligible:
                col1, col2, col3, col4 = st.columns([3, 2, 1, 1])
                with col1:
                    st.markdown(f"""
                    <div class="giveaway-card">
                        <div class="giveaway-title">{g['title'][:80]}</div>
                        <div class="giveaway-meta">
                            <span>Source: {g['source']}</span>
                            <span>Region: {g['country_restriction']}</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                with col2:
                    st.link_button("🔗 Open", g["url"])
                with col3:
                    if st.button("▶️ Enter", key=f"enter_{g['id']}"):
                        with st.spinner("Auto-entering..."):
                            result, log = auto_enter_giveaway(g["url"])
                            if result == "region_restricted":
                                update_giveaway_status(g["id"], "not_eligible")
                                st.error("Region restricted! This giveaway is not available in your country.")
                            elif result is True:
                                update_giveaway_status(g["id"], "participated")
                                st.success("Entered successfully!")
                            else:
                                st.warning("Entry may have failed. Check the log.")
                            st.session_state.crawl_log = log
                with col4:
                    if st.button("⏭️ Skip", key=f"skip_{g['id']}"):
                        update_giveaway_status(g["id"], "skipped")
                        st.rerun()

            if st.button("⚡ Auto-Enter ALL Eligible", type="primary", use_container_width=True):
                for g in eligible:
                    with st.spinner(f"Entering: {g['title'][:60]}..."):
                        result, log = auto_enter_giveaway(g["url"])
                        if result == "region_restricted":
                            update_giveaway_status(g["id"], "not_eligible")
                            st.error(f"Region restricted: {g['title'][:60]}")
                        elif result is True:
                            update_giveaway_status(g["id"], "participated")
                            st.success(f"Entered: {g['title'][:60]}")
                        else:
                            st.warning(f"Failed: {g['title'][:60]}")
                st.rerun()
        else:
            st.markdown(f"""
            <div class="empty-state">
                <p>No eligible giveaways found. Run a crawl first!</p>
            </div>
            """, unsafe_allow_html=True)

        if st.session_state.crawl_log:
            st.markdown('<hr class="section-divider">', unsafe_allow_html=True)
            st.markdown(f'<div class="section-title">{SVG_ICONS["list"]} Entry Log</div>', unsafe_allow_html=True)
            for entry in st.session_state.crawl_log[-20:]:
                log_class = "log-entry"
                if "success" in entry.lower() or "completed" in entry.lower():
                    log_class += " log-success"
                elif "error" in entry.lower() or "failed" in entry.lower():
                    log_class += " log-error"
                elif "captcha" in entry.lower() or "timeout" in entry.lower():
                    log_class += " log-warning"
                st.markdown(f'<div class="{log_class}">{entry}</div>', unsafe_allow_html=True)

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
        selected_country = st.selectbox(
            "Your country for eligibility check",
            options=list(countries.keys()),
            format_func=lambda x: countries[x],
            index=list(countries.keys()).index(config.get("target_country", "germany"))
        )
        if selected_country != config.get("target_country"):
            config["target_country"] = selected_country
            save_config(config)
            st.success("Country updated!")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-section">', unsafe_allow_html=True)
        st.markdown(f'<h3>{SVG_ICONS["search"]} Crawl Sources</h3>', unsafe_allow_html=True)
        available_sources = ["gleamfinder", "gleam_official", "bestofgleam", "gleamdb"]
        current_sources = config.get("crawl_sources", [])

        for source in available_sources:
            is_active = source in current_sources
            if st.checkbox(source.replace('_', ' ').title(), value=is_active):
                if source not in current_sources:
                    current_sources.append(source)
            else:
                if source in current_sources:
                    current_sources.remove(source)

        config["crawl_sources"] = current_sources
        save_config(config)
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-section">', unsafe_allow_html=True)
        st.markdown(f'<h3>{SVG_ICONS["link"]} Custom Sites</h3>', unsafe_allow_html=True)
        custom_sites = config.get("custom_sites", [])

        new_site = st.text_input("Add custom site URL", placeholder="https://example.com/giveaways")
        if st.button("Add Site"):
            if new_site and new_site.startswith("http"):
                if add_custom_site(new_site):
                    st.success("Site added!")
                    config = load_config()
                    custom_sites = config.get("custom_sites", [])
                else:
                    st.warning("Site already exists")
            else:
                st.error("Please enter a valid URL")

        if custom_sites:
            for i, site in enumerate(custom_sites):
                st.markdown(f"""
                <div class="site-item">
                    <code>{site}</code>
                </div>
                """, unsafe_allow_html=True)
                if st.button("Remove", key=f"remove_site_{i}"):
                    remove_custom_site(site)
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="settings-section">', unsafe_allow_html=True)
        st.markdown(f'<h3>{SVG_ICONS["zap"]} Network Settings</h3>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            min_delay = st.slider("Min delay (seconds)", 1, 15, config.get("min_delay", 3))
        with col2:
            max_delay = st.slider("Max delay (seconds)", 2, 20, config.get("max_delay", 10))

        if min_delay != config.get("min_delay") or max_delay != config.get("max_delay"):
            config["min_delay"] = min_delay
            config["max_delay"] = max_delay
            save_config(config)
            st.success("Delay settings updated!")
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


if __name__ == "__main__":
    main()
