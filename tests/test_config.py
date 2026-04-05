"""Tests for config.py -- covers all config operations triggered by Settings widgets.

Covers:
  - load_config defaults (app startup, no config.json)
  - save_config + load_config round-trip (any Settings change)
  - Country selectbox persistence
  - Custom site stubs (deprecated, always return False/[])
  - NDJSON import directory text input
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
    assert config["auto_enter_enabled"] == DEFAULT_CONFIG["auto_enter_enabled"]
    assert config["ndjson_import_dir"] == DEFAULT_CONFIG["ndjson_import_dir"]


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
# Custom site stubs (deprecated -- always return False/[])
# ---------------------------------------------------------------------------

def test_add_custom_site(tmp_config):
    from config import add_custom_site, get_custom_sites, load_config

    load_config()  # initialise defaults
    result = add_custom_site("https://newsite.com")
    assert result is False  # deprecated, always returns False
    assert get_custom_sites() == []


def test_add_custom_site_duplicate(tmp_config):
    from config import add_custom_site, load_config

    load_config()
    result = add_custom_site("https://newsite.com")
    assert result is False


# ---------------------------------------------------------------------------
# Remove Site stub (deprecated)
# ---------------------------------------------------------------------------

def test_remove_custom_site(tmp_config):
    from config import remove_custom_site, load_config

    load_config()
    result = remove_custom_site("https://newsite.com")
    assert result is False


def test_remove_custom_site_missing(tmp_config):
    from config import remove_custom_site, load_config

    load_config()
    result = remove_custom_site("https://nonexistent.com")
    assert result is False


# ---------------------------------------------------------------------------
# Arbitrary config key round-trip (e.g. old config keys from previous versions)
# ---------------------------------------------------------------------------

def test_arbitrary_config_key_roundtrip(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["some_custom_key"] = ["a", "b"]
    save_config(config)
    cfg._config_cache = None
    assert load_config()["some_custom_key"] == ["a", "b"]


# ---------------------------------------------------------------------------
# NDJSON import directory text input
# ---------------------------------------------------------------------------

def test_ndjson_dir_persists(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["ndjson_import_dir"] = "/tmp/test-dir"
    save_config(config)
    cfg._config_cache = None

    assert load_config()["ndjson_import_dir"] == "/tmp/test-dir"


def test_ndjson_dir_empty(tmp_config):
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["ndjson_import_dir"] = ""
    save_config(config)
    cfg._config_cache = None

    assert load_config()["ndjson_import_dir"] == ""


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
    assert config["auto_enter_enabled"] == DEFAULT_CONFIG["auto_enter_enabled"]
    assert config["ndjson_import_dir"] == DEFAULT_CONFIG["ndjson_import_dir"]


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


def test_get_target_country_default(tmp_config):
    """get_target_country should return 'germany' when no config exists."""
    from config import get_target_country

    assert get_target_country() == "germany"


# ---------------------------------------------------------------------------
# Config cache behavior
# ---------------------------------------------------------------------------

def test_config_cache_avoids_disk_read(tmp_config):
    """Second call to load_config should return cached data without reading disk."""
    import config as cfg
    from config import load_config, save_config

    config = load_config()
    config["target_country"] = "us"
    save_config(config)

    # Now delete the config file -- cached value should still work
    os.unlink(tmp_config)
    loaded = load_config()
    assert loaded["target_country"] == "us"


def test_config_cache_returns_copy(tmp_config):
    """load_config should return a copy, not a reference to the cache."""
    from config import load_config

    a = load_config()
    b = load_config()
    a["target_country"] = "modified"
    # b should not be affected
    assert b["target_country"] != "modified"


# ---------------------------------------------------------------------------
# Malformed config.json with backslash recovery
# ---------------------------------------------------------------------------

def test_load_config_backslash_recovery(tmp_config):
    """Config with unescaped backslashes (invalid JSON) should be backed up and reset to defaults."""
    import config as cfg
    from config import load_config, DEFAULT_CONFIG

    # Write JSON with unescaped backslashes (common Windows path issue) — invalid JSON
    with open(tmp_config, "w") as f:
        f.write('{"ndjson_import_dir": "C:\\Users\\test\\downloads"}')

    cfg._config_cache = None
    config = load_config()
    # Malformed config is backed up and defaults are returned
    assert config == DEFAULT_CONFIG
    assert os.path.exists(tmp_config + ".bak")


def test_load_config_creates_backup_on_irrecoverable(tmp_config):
    """Completely broken config should be backed up to .bak."""
    import config as cfg
    from config import load_config, DEFAULT_CONFIG

    # Write something that can't be fixed even with backslash replacement
    with open(tmp_config, "w") as f:
        f.write("{{{totally broken json with no hope of recovery}}}")

    cfg._config_cache = None
    config = load_config()

    # Should fall back to defaults
    assert config["target_country"] == DEFAULT_CONFIG["target_country"]

    # Backup file should exist
    assert os.path.exists(tmp_config + ".bak")


# ---------------------------------------------------------------------------
# DEFAULT_CONFIG completeness
# ---------------------------------------------------------------------------

def test_default_config_has_required_keys(tmp_config):
    """DEFAULT_CONFIG should contain all keys needed by the application."""
    from config import DEFAULT_CONFIG

    required_keys = ["target_country", "auto_enter_enabled", "ndjson_import_dir"]
    for key in required_keys:
        assert key in DEFAULT_CONFIG, f"Missing key in DEFAULT_CONFIG: {key}"


# ---------------------------------------------------------------------------
# save_config updates cache
# ---------------------------------------------------------------------------

def test_save_config_updates_cache_immediately(tmp_config):
    """save_config should update the in-memory cache so next load_config
    returns the new value without resetting _config_cache."""
    from config import load_config, save_config

    config = load_config()
    config["target_country"] = "uk"
    save_config(config)

    # Do NOT reset _config_cache -- the save should have updated it
    loaded = load_config()
    assert loaded["target_country"] == "uk"
