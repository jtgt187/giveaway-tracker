import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# In-memory config cache to avoid reading disk on every call
_config_cache = None

DEFAULT_CONFIG = {
    "target_country": "germany",
    "auto_enter_enabled": True,
    "auto_enter_methods": ["click"],
    "ndjson_import_path": "",
}


def load_config():
    global _config_cache
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
            # Config file is malformed (e.g. unescaped backslashes in Windows paths).
            # Try to salvage by reading as raw text and fixing common issues.
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    raw = f.read()
                # Fix unescaped backslashes (common with Windows paths pasted manually)
                fixed = raw.replace("\\", "\\\\")
                saved = json.loads(fixed)
                config = DEFAULT_CONFIG.copy()
                config.update(saved)
                # Re-save with proper escaping so this doesn't happen again
                save_config(config)
                return config.copy()
            except (json.JSONDecodeError, ValueError, OSError):
                # Completely broken -- back up and start fresh
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
    _config_cache = config.copy()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


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
