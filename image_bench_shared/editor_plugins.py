"""
The editor plugins supplied with the extension (editor-extensions/): packaging one for download from the manual
and telling the installed version. The editor-specific parts are in the installer modules (uxp_install for
Photoshop, krita_install for Krita, gimp_install for GIMP), which provide get_status(manifest), the
PACKAGE_EXTENSION of the download, MANIFEST (the path of manifest.json in the plugin folder) and EXCLUDED_FILES
(development files that are not a part of the plugin). The extension never installs a plugin itself: the plugins
are installed from the downloads, or in development by the scripts of their folders (editor-extensions/krita/krita.py,
gimp/gimp.py deploy, photoshop/uxp.ps1), which are not shipped
"""
import importlib
import io
import json
import os
import zipfile

_SHARED_DIR = os.path.dirname(os.path.abspath(__file__))

_REPOSITORY_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..")

# Folder of the plugin folders: copied next to this module by the deploy, or the repository folder
# (the extension's image_bench_shared directory is a symlink to common-extension/shared_backend)
EDITOR_EXTENSIONS_DIRS = (os.path.join(_SHARED_DIR, "editor-extensions"),
                          os.path.join(_REPOSITORY_DIR, "editor-extensions"))

# The plugins by their name in the API (?plugin=): their folder in editor-extensions/ and their installer module
PLUGINS = {
    "image-bench": {"dir": "photoshop", "installer": "uxp_install"},
    "canny": {"dir": "photoshop-canny", "installer": "uxp_install"},
    "krita": {"dir": "krita", "installer": "krita_install"},
    "gimp": {"dir": "gimp", "installer": "gimp_install"},
}
DEFAULT_PLUGIN = "image-bench"


class PluginError(Exception):
    pass


def _get_plugin(plugin):
    if plugin not in PLUGINS:
        raise PluginError(f"Unknown editor plugin: {plugin}")

    return PLUGINS[plugin], importlib.import_module("." + PLUGINS[plugin]["installer"], __package__)


def get_plugin_dir(plugin=DEFAULT_PLUGIN):
    """
    Args:
        plugin: A key of PLUGINS
    """
    info, installer = _get_plugin(plugin)

    for root in EDITOR_EXTENSIONS_DIRS:
        path = os.path.join(root, info["dir"])

        if os.path.isfile(os.path.join(path, installer.MANIFEST)):
            return os.path.normpath(path)

    raise PluginError("The editor plugin files are not found in the extension")


def read_manifest(plugin_dir, installer):
    with open(os.path.join(plugin_dir, installer.MANIFEST), encoding="utf-8") as file:
        return json.load(file)


def get_plugin_files(plugin_dir, excluded=()):
    """Paths of the plugin files relative to its directory, without the excluded top-level files and folders"""
    result = []

    for root, dirs, files in os.walk(plugin_dir):
        relative_root = os.path.relpath(root, plugin_dir)
        dirs[:] = [d for d in dirs if d != "__pycache__" and not d.startswith(".")
                   and not (relative_root == "." and d in excluded)]

        if relative_root == ".":
            files = [f for f in files if f not in excluded]

        result += [os.path.normpath(os.path.join(relative_root, f)) for f in files
                   if not f.startswith(".") and not f.endswith(".pyc")]

    return result


def _load(plugin):
    """The plugin's installer module, folder, files and manifest"""
    _, installer = _get_plugin(plugin)
    plugin_dir = get_plugin_dir(plugin)
    return installer, plugin_dir, get_plugin_files(plugin_dir, installer.EXCLUDED_FILES), \
        read_manifest(plugin_dir, installer)


def package(plugin=DEFAULT_PLUGIN):
    """
    Package the plugin as a zip archive of its files: a .ccx file installed by double-clicking it with
    the Creative Cloud app, or a .zip file imported in Krita (Tools › Scripts › Import Python Plugin from File)

    Returns:
        (file name, file content)
    """
    installer, plugin_dir, files, manifest = _load(plugin)
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(os.path.join(plugin_dir, path), path.replace(os.sep, "/"))

    return f"{manifest['id']}_{manifest['version']}{installer.PACKAGE_EXTENSION}", buffer.getvalue()


def get_status(plugin=DEFAULT_PLUGIN):
    """
    The version of the supplied plugin, and the version installed on this computer (None if not installed):
    {available, installed, supported, platform, package}
    """
    try:
        installer, _, _, manifest = _load(plugin)
    except (PluginError, OSError, ValueError):
        installer = _get_plugin(plugin)[1]
        status = installer.get_status(None)
        return {**status, "available": None, "installed": None, "package": installer.PACKAGE_EXTENSION}

    return {**installer.get_status(manifest), "available": manifest["version"],
            "package": installer.PACKAGE_EXTENSION}
