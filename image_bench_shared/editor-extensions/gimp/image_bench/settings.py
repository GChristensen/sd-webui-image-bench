"""
The plugin settings: a JSON file in GIMP's profile folder, read by every run of the plugin (each GIMP procedure runs
in its own process, so they cannot share memory)
"""
import json
import os

from gi.repository import Gimp

DEFAULT_URL = "http://127.0.0.1:7860"
MAX_RECENT_URLS = 5


def _path():
    return os.path.join(Gimp.directory(), "image_bench.json")


def load():
    try:
        with open(_path(), encoding="utf-8") as file:
            settings = json.load(file)
            return settings if isinstance(settings, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**values):
    """Update the given settings, keeping the others"""
    settings = {**load(), **values}

    try:
        with open(_path(), "w", encoding="utf-8") as file:
            json.dump(settings, file, indent=2)
    except OSError:
        pass


def url():
    return (load().get("url") or "").strip() or DEFAULT_URL


def recent_urls():
    urls = load().get("recentUrls")
    return [url for url in urls if isinstance(url, str)] if isinstance(urls, list) else []


def add_recent_url(url):
    """Put a URL the plugin connected to at the top of the recent ones"""
    save(recentUrls=([url] + [u for u in recent_urls() if u != url])[:MAX_RECENT_URLS])
