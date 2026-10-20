"""
Installing the GIMP plugin (editor-extensions/gimp) into the plug-ins folder of the current user's GIMP 3 profile:
the folder of GIMP3_DIRECTORY if set (GIMP's own override of the profile folder, set by GIMP Portable's launcher),
else the newest GIMP/3.x folder. GIMP finds new plug-ins when it starts, so it is restarted afterwards; it need not be
closed meanwhile.
"""
import json
import os
import re
import shutil
import stat
import sys

from .editor_plugins import PluginError

MANIFEST = os.path.join("image_bench", "manifest.json")

PACKAGE_EXTENSION = ".zip"

# Development files that are not a part of the plugin
EXCLUDED_FILES = ("dist", "README.md", "gimp.py")

# The plug-in folder, which GIMP requires to hold a main file of the same name
PACKAGE_NAME = "image_bench"


def _config_roots():
    """Folders holding the GIMP/<version> profiles on this platform"""
    if sys.platform == "win32":
        return [os.path.join(os.environ.get("APPDATA", ""), "GIMP")]

    if sys.platform == "darwin":
        return [os.path.expanduser("~/Library/Application Support/GIMP")]

    if sys.platform.startswith("linux"):
        config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        return [os.path.join(config_home, "GIMP"), os.path.expanduser("~/.var/app/org.gimp.GIMP/config/GIMP")]

    return None


def get_plugins_dir():
    """
    The plug-ins folder of the GIMP 3 profile; None on an unsupported platform, "" if GIMP 3 has not run yet
    (it creates the profile on its first start)
    """
    profile = os.environ.get("GIMP3_DIRECTORY")

    if profile:
        return os.path.join(profile, "plug-ins") if os.path.isdir(profile) else ""

    roots = _config_roots()

    if roots is None:
        return None

    profiles = []

    for root in roots:
        try:
            names = os.listdir(root)
        except OSError:
            continue

        for name in names:
            match = re.fullmatch(r"3\.(\d+)", name)

            if match and os.path.isdir(os.path.join(root, name)):
                profiles.append((int(match.group(1)), os.path.join(root, name)))

    return os.path.join(max(profiles)[1], "plug-ins") if profiles else ""


def get_status(manifest):
    """The version of the plugin installed on this computer (None if not installed)"""
    plugins_dir = get_plugins_dir()
    status = {"installed": None, "supported": plugins_dir is not None, "platform": sys.platform}

    if manifest and plugins_dir:
        try:
            with open(os.path.join(plugins_dir, MANIFEST), encoding="utf-8") as file:
                status["installed"] = json.load(file).get("version")
        except (OSError, ValueError):
            pass

    return status


def install_or_elevate(plugin_dir, files, manifest):
    """
    Copy the plugin into the plug-ins folder of the GIMP 3 profile (see get_plugins_dir)

    Returns:
        {"result": "installed", "version": ...}

    Raises:
        PluginError: On an unsupported platform, or if GIMP 3 has never run
    """
    plugins_dir = get_plugins_dir()

    if plugins_dir is None:
        raise PluginError(f"Installing the plugin is not supported on {sys.platform}")

    if not plugins_dir:
        raise PluginError("No GIMP 3 settings folder was found: start GIMP 3 once and install again.")

    shutil.rmtree(os.path.join(plugins_dir, PACKAGE_NAME), ignore_errors=True)

    for path in files:
        target = os.path.join(plugins_dir, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(plugin_dir, path), target)

    # GIMP runs only executable plug-in files outside Windows
    main_file = os.path.join(plugins_dir, PACKAGE_NAME, PACKAGE_NAME + ".py")
    os.chmod(main_file, os.stat(main_file).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return {"result": "installed", "version": manifest["version"]}
