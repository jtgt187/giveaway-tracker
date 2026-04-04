import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

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
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
        config = DEFAULT_CONFIG.copy()
        config.update(saved)
        return config
    return DEFAULT_CONFIG.copy()


def save_config(config):
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
