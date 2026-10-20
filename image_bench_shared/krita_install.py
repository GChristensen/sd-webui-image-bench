"""
Installing the Krita plugin (editor-extensions/krita) into the Python plugin folder of the current user and enabling
it in kritarc, as Krita's Python Plugin Manager does
"""
import json
import os
import shutil
import subprocess
import sys

from .editor_plugins import PluginError

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


def _is_krita_running():
    try:
        if sys.platform == "win32":
            output = subprocess.run(["tasklist", "/FI", "IMAGENAME eq krita.exe", "/NH"], capture_output=True,
                                    text=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
            return "krita.exe" in output.lower()

        return subprocess.run(["pgrep", "-x", "krita"], capture_output=True).returncode == 0
    except OSError:
        return False


def enable_plugin(kritarc, name=PACKAGE_NAME):
    """
    Set enable_<name>=true in the [python] section of kritarc, editing the lines only:
    configparser would rewrite the Qt settings format
    """
    key = f"enable_{name}"

    try:
        with open(kritarc, encoding="utf-8", newline="") as file:
            text = file.read()
    except FileNotFoundError:
        text = ""

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines()
    section_start = section_end = None

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith("[") and stripped.endswith("]"):
            if section_start is not None and section_end is None:
                section_end = i

            if stripped == "[python]":
                section_start = i
        elif section_start is not None and section_end is None and stripped.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}=true"
            break
    else:
        if section_start is None:
            lines += ([""] if lines and lines[-1].strip() else []) + ["[python]", f"{key}=true"]
        else:
            end = section_end if section_end is not None else len(lines)

            # Before the blank lines that end the section
            while end > section_start + 1 and not lines[end - 1].strip():
                end -= 1

            lines.insert(end, f"{key}=true")

    os.makedirs(os.path.dirname(kritarc), exist_ok=True)

    with open(kritarc, "w", encoding="utf-8", newline="") as file:
        file.write(newline.join(lines) + newline)


def install_or_elevate(plugin_dir, files, manifest):
    """
    Copy the plugin into Krita's Python plugin folder and enable it. Krita writes kritarc when it exits,
    so it must not run meanwhile.

    Returns:
        {"result": "installed", "version": ...}

    Raises:
        PluginError: On an unsupported platform, or if Krita is running
    """
    locations = get_install_locations()

    if not locations:
        raise PluginError(f"Installing the plugin is not supported on {sys.platform}")

    if _is_krita_running():
        raise PluginError("Krita is running: close it and install again (Krita rewrites its settings when it exits).")

    plugins_dir, kritarc = locations
    shutil.rmtree(os.path.join(plugins_dir, PACKAGE_NAME), ignore_errors=True)

    for path in files:
        target = os.path.join(plugins_dir, path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(plugin_dir, path), target)

    enable_plugin(kritarc)

    return {"result": "installed", "version": manifest["version"]}
