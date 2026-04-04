"""Tests for config.py -- covers all config operations triggered by Settings widgets.

Covers:
  - load_config defaults (app startup, no config.json)
  - save_config + load_config round-trip (any Settings change)
  - Country selectbox persistence
  - add_custom_site / remove_custom_site (Add Site / Remove buttons)
  - Crawl source checkbox toggles
  - Delay slider persistence
  - NDJSON import path text input
  - Malformed config.json resilience
"""

import json
import os


# ---------------------------------------------------------------------------
# load_config / save_config
# ---------------------------------------------------------------------------

def test_load_config_defaults(tmp_config):
    from config import load_config, DEFAULT_CONFIG

    config = load_config()
    assert config["target_country"] == DEFAULT_CONFIG["target_country"]
    assert config["crawl_sources"] == DEFAULT_CONFIG["crawl_sources"]
    assert config["auto_enter_enabled"] == DEFAULT_CONFIG["auto_enter_enabled"]
    assert config["min_delay"] == DEFAULT_CONFIG["min_delay"]
    assert config["max_delay"] == DEFAULT_CONFIG["max_delay"]


def test_save_and_load_config(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["target_country"] = "uk"
    save_config(config)

    # Reset cache to force re-read from disk
    cfg._config_cache = None
    loaded = load_config()
    assert loaded["target_country"] == "uk"


def test_save_config_persists_to_disk(tmp_config):
    from config import load_config, save_config

    config = load_config()
    config["min_delay"] = 99
    save_config(config)

    # Read raw JSON from disk
    with open(tmp_config, "r") as f:
        raw = json.load(f)
    assert raw["min_delay"] == 99


# ---------------------------------------------------------------------------
# Country selectbox
# ---------------------------------------------------------------------------

def test_country_selectbox_persists(tmp_config):
    import config as cfg
    from config import load_config, save_config

    for country in ["germany", "dach", "eu", "us", "uk", "worldwide"]:
        config = load_config()
        config["target_country"] = country
        save_config(config)
        cfg._config_cache = None
        assert load_config()["target_country"] == country


# ---------------------------------------------------------------------------
# Add Site button + text input
# ---------------------------------------------------------------------------

def test_add_custom_site(tmp_config):
    from config import add_custom_site, get_custom_sites, load_config

    load_config()  # initialise defaults
    result = add_custom_site("https://newsite.com")
    assert result is True
    assert "https://newsite.com" in get_custom_sites()


def test_add_custom_site_duplicate(tmp_config):
    from config import add_custom_site, load_config

    load_config()
    add_custom_site("https://newsite.com")
    result = add_custom_site("https://newsite.com")
    assert result is False


# ---------------------------------------------------------------------------
# Remove Site button
# ---------------------------------------------------------------------------

def test_remove_custom_site(tmp_config):
    from config import add_custom_site, remove_custom_site, get_custom_sites, load_config

    load_config()
    add_custom_site("https://newsite.com")
    result = remove_custom_site("https://newsite.com")
    assert result is True
    assert "https://newsite.com" not in get_custom_sites()


def test_remove_custom_site_missing(tmp_config):
    from config import remove_custom_site, load_config

    load_config()
    result = remove_custom_site("https://nonexistent.com")
    assert result is False


# ---------------------------------------------------------------------------
# Crawl source checkboxes
# ---------------------------------------------------------------------------

def test_crawl_source_toggle(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["crawl_sources"] = ["gleamfinder"]
    save_config(config)
    cfg._config_cache = None
    assert load_config()["crawl_sources"] == ["gleamfinder"]

    # Toggle on more sources
    config = load_config()
    config["crawl_sources"] = ["gleamfinder", "bestofgleam", "gleamdb"]
    save_config(config)
    cfg._config_cache = None
    assert load_config()["crawl_sources"] == ["gleamfinder", "bestofgleam", "gleamdb"]


def test_crawl_source_empty(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["crawl_sources"] = []
    save_config(config)
    cfg._config_cache = None
    assert load_config()["crawl_sources"] == []


# ---------------------------------------------------------------------------
# Delay sliders
# ---------------------------------------------------------------------------

def test_delay_slider_persists(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["min_delay"] = 5
    config["max_delay"] = 15
    save_config(config)
    cfg._config_cache = None

    loaded = load_config()
    assert loaded["min_delay"] == 5
    assert loaded["max_delay"] == 15


# ---------------------------------------------------------------------------
# NDJSON import path text input
# ---------------------------------------------------------------------------

def test_ndjson_path_persists(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["ndjson_import_path"] = "/tmp/test.ndjson"
    save_config(config)
    cfg._config_cache = None

    assert load_config()["ndjson_import_path"] == "/tmp/test.ndjson"


def test_ndjson_path_empty(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["ndjson_import_path"] = ""
    save_config(config)
    cfg._config_cache = None

    assert load_config()["ndjson_import_path"] == ""


# ---------------------------------------------------------------------------
# Auto-Enter toggle
# ---------------------------------------------------------------------------

def test_auto_enter_toggle(tmp_config):
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


# ---------------------------------------------------------------------------
# Malformed config.json resilience
# ---------------------------------------------------------------------------

def test_load_config_malformed_json(tmp_config):
    import config as cfg
    from config import load_config, DEFAULT_CONFIG

    with open(tmp_config, "w") as f:
        f.write("{bad json content!!!")

    cfg._config_cache = None
    config = load_config()
    # Should fall back to defaults without crashing
    assert config["target_country"] == DEFAULT_CONFIG["target_country"]


def test_load_config_merges_partial(tmp_config):
    """A config file with only some keys should be merged with defaults."""
    import config as cfg
    from config import load_config, DEFAULT_CONFIG

    with open(tmp_config, "w") as f:
        json.dump({"target_country": "us"}, f)

    cfg._config_cache = None
    config = load_config()
    assert config["target_country"] == "us"
    # Other keys should come from defaults
    assert config["crawl_sources"] == DEFAULT_CONFIG["crawl_sources"]
    assert config["min_delay"] == DEFAULT_CONFIG["min_delay"]


# ---------------------------------------------------------------------------
# get_target_country helper
# ---------------------------------------------------------------------------

def test_get_target_country(tmp_config):
    import config as cfg
    from config import load_config, save_config, get_target_country

    config = load_config()
    config["target_country"] = "dach"
    save_config(config)
    cfg._config_cache = None

    assert get_target_country() == "dach"
