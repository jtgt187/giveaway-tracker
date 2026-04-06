import json
import os
import tempfile
import threading

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# In-memory config cache to avoid reading disk on every call
_config_cache = None
_config_lock = threading.Lock()

DEFAULT_CONFIG = {
    "target_country": "germany",
    "auto_enter_enabled": True,
    "auto_enter_methods": ["click"],
    "ndjson_import_dir": "",
}


def load_config():
    global _config_cache
    with _config_lock:
        if _config_cache is not None:
            return _config_cache.copy()
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                config = DEFAULT_CONFIG.copy()
                config.update(saved)
                _config_cache = config
                return config.copy()
            except (json.JSONDecodeError, ValueError) as e:
                backup = CONFIG_PATH + ".bak"
                try:
                    os.replace(CONFIG_PATH, backup)
                except OSError:
                    pass
                _config_cache = DEFAULT_CONFIG.copy()
                return DEFAULT_CONFIG.copy()
        _config_cache = DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()


def save_config(config):
    global _config_cache
    with _config_lock:
        _config_cache = config.copy()
    # Atomic write: write to temp file then rename, so a crash during
    # json.dump can't leave a truncated/corrupt config.json.
    config_dir = os.path.dirname(CONFIG_PATH) or "."
    fd, tmp = tempfile.mkstemp(dir=config_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        os.replace(tmp, CONFIG_PATH)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_custom_sites():
    """Deprecated — custom sites removed. Kept for backwards compat."""
    return []


def add_custom_site(url):
    """Deprecated — custom sites removed. Kept for backwards compat."""
    return False


def remove_custom_site(url):
    """Deprecated — custom sites removed. Kept for backwards compat."""
    return False


def get_target_country():
    config = load_config()
    return config.get("target_country", "germany")
