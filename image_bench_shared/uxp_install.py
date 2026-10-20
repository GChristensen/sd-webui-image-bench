"""
The Photoshop UXP plugins (editor-extensions/photoshop, photoshop-canny): their package and the version installed
where the Creative Cloud app installs plugins. They are installed from the downloaded .ccx file, or in development
with editor-extensions/photoshop/uxp.ps1 deploy
"""
import json
import os
import sys

MANIFEST = "manifest.json"

PACKAGE_EXTENSION = ".ccx"

# Development files that are not a part of the plugin
EXCLUDED_FILES = ("dist", "README.md", "uxp.ps1")


def get_install_locations():
    """
    The shared UXP plugin directory and the Photoshop plugin registry of the current user,
    or None on an unsupported platform
    """
    if sys.platform == "win32":
        common_files = os.environ.get("CommonProgramFiles", r"C:\Program Files\Common Files")
        return (os.path.join(common_files, "Adobe", "UXP", "Plugins", "External"),
                os.path.join(os.environ.get("APPDATA", ""), "Adobe", "UXP", "PluginsInfo", "v1", "PS.json"))

    if sys.platform == "darwin":
        return ("/Library/Application Support/Adobe/UXP/Plugins/External",
                os.path.expanduser("~/Library/Application Support/Adobe/UXP/PluginsInfo/v1/PS.json"))

    return None


def _read_registered_plugins(info_file):
    try:
        with open(info_file, encoding="utf-8-sig") as file:
            return [p for p in (json.load(file).get("plugins") or []) if p]
    except FileNotFoundError:
        return []


def get_status(manifest):
    """The version of the plugin installed on this computer (None if not installed)"""
    status = {"installed": None, "supported": get_install_locations() is not None, "platform": sys.platform}

    if manifest and status["supported"]:
        _, info_file = get_install_locations()

        try:
            plugin = next((p for p in _read_registered_plugins(info_file) if p.get("pluginId") == manifest["id"]),
                          None)
            status["installed"] = plugin and plugin.get("versionString")
        except (OSError, ValueError):
            pass

    return status
