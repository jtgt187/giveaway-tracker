"""Shared pytest fixtures for giveaway-tracker tests."""

import os
import sys

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Provide a fresh temporary SQLite database for each test.

    Patches ``database.DB_PATH`` so that all database functions operate on
    an isolated temp database instead of the production ``giveaways.db``.
    Also patches the blacklist path to avoid touching the real blacklist.
    """
    import database

    db_file = str(tmp_path / "test_giveaways.db")
    bl_path = str(tmp_path / "test_blacklist.txt")
    monkeypatch.setattr(database, "DB_PATH", db_file)
    monkeypatch.setattr(database, "_blacklist_cache", None)
    monkeypatch.setattr(database, "_get_blacklist_path", lambda: bl_path)
    database.init_db()
    return db_file


@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    """Provide a fresh temporary config.json for each test.

    Patches ``config.CONFIG_PATH`` so that config functions operate on
    an isolated temp file.  Resets the in-memory cache.
    """
    import config

    config_file = str(tmp_path / "test_config.json")
    monkeypatch.setattr(config, "CONFIG_PATH", config_file)
    monkeypatch.setattr(config, "_config_cache", None)
    return config_file


@pytest.fixture()
def sample_giveaway():
    """Return a dict representing a typical giveaway for insertion."""
    return {
        "title": "Win a PlayStation 5",
        "url": "https://gleam.io/abc123/win-ps5",
        "source": "gleamfinder",
        "description": "Enter to win a PS5 console",
        "deadline": "Friday 10 April 2099 at 23:59:59",
        "country_restriction": "worldwide",
    }


@pytest.fixture()
def sample_giveaways():
    """Return a list of giveaway dicts for batch insertion tests."""
    return [
        {
            "title": "Win a PlayStation 5",
            "url": "https://gleam.io/abc123/win-ps5",
            "source": "gleamfinder",
            "description": "",
            "deadline": "Friday 10 April 2099 at 23:59:59",
            "country_restriction": "worldwide",
        },
        {
            "title": "Win an Xbox Series X",
            "url": "https://gleam.io/def456/win-xbox",
            "source": "bestofgleam",
            "description": "",
            "deadline": "Saturday 11 April 2099 at 22:00:00",
            "country_restriction": "germany",
        },
        {
            "title": "Win a Nintendo Switch",
            "url": "https://gleam.io/ghi789/win-switch",
            "source": "gleamdb",
            "description": "",
            "deadline": "Sunday 12 April 2099 at 20:00:00",
            "country_restriction": "us",
        },
        {
            "title": "Win Steam Keys",
            "url": "https://gleam.io/jkl012/win-steam",
            "source": "gleam_official",
            "description": "",
            "deadline": "",
            "country_restriction": "eu",
        },
    ]
