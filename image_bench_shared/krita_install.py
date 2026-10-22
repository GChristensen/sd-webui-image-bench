"""
The Krita plugin (editor-extensions/krita): its package and the version installed in the Python plugin folder of the
current user. It is installed from the downloaded .zip file, or in development with editor-extensions/krita/krita.py
deploy
"""
import json
import os
import sys

MANIFEST = os.path.join("image_bench", "manifest.json")

PACKAGE_EXTENSION = ".zip"

# Development files that are not a part of the plugin
EXCLUDED_FILES = ("dist", "README.md", "krita.py")

# The plugin's package folder and .desktop file (X-KDE-Library)
PACKAGE_NAME = "image_bench"


def get_install_locations():
    """The Python plugin folder of Krita and its settings file (kritarc), or None on an unsupported platform"""
    if sys.platform == "win32":
        return (os.path.join(os.environ.get("APPDATA", ""), "krita", "pykrita"),
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "kritarc"))

    if sys.platform == "darwin":
        return (os.path.expanduser("~/Library/Application Support/krita/pykrita"),
                os.path.expanduser("~/Library/Preferences/kritarc"))

    if sys.platform.startswith("linux"):
        data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return os.path.join(data_home, "krita", "pykrita"), os.path.join(config_home, "kritarc")

    return None


def get_status(manifest):
    """The version of the plugin installed on this computer (None if not installed)"""
    locations = get_install_locations()
    status = {"installed": None, "supported": locations is not None, "platform": sys.platform}

    if manifest and locations:
        try:
            with open(os.path.join(locations[0], MANIFEST), encoding="utf-8") as file:
                status["installed"] = json.load(file).get("version")
        except (OSError, ValueError):
            pass

    return status

