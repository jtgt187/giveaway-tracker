import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

# In-memory config cache to avoid reading disk on every call
_config_cache = None

DEFAULT_CONFIG = {
    "target_country": "germany",
    "crawl_sources": [
        "gleamfinder",
        "gleam_official",
        "bestofgleam",
        "gleamdb",
    ],
    "custom_sites": [
        "https://giveawaydrop.com/",
    ],
    "auto_enter_enabled": True,
    "auto_enter_methods": ["click"],
    "min_delay": 3,
    "max_delay": 10,
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
    config = load_config()
    return config.get("custom_sites", [])


def add_custom_site(url):
    config = load_config()
    if url not in config["custom_sites"]:
        config["custom_sites"].append(url)
        save_config(config)
        return True
    return False


def remove_custom_site(url):
    config = load_config()
    if url in config["custom_sites"]:
        config["custom_sites"].remove(url)
        save_config(config)
        return True
    return False


def get_target_country():
    config = load_config()
    return config.get("target_country", "germany")
