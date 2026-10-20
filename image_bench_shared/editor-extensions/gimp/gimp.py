"""
GIMP plugin management from a shell (just gimp-package / gimp-deploy / gimp-undeploy), through the same backend
code as the install card of the Image Bench manual:
  package  - Build dist/image_bench_gimp_<version>.zip, to unpack into the plug-ins folder of GIMP
  deploy   - Copy the plugin to the plug-ins folder of the GIMP 3 profile: GIMP3_DIRECTORY (e.g. from .env, for
             GIMP Portable's Data/GimpAppData), else the newest GIMP/3.x folder; restart GIMP afterwards
  undeploy - Remove the plugin installed by deploy
"""
import os
import shutil
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "..", "..", "common-extension"))

from shared_backend import editor_plugins, gimp_install  # noqa: E402


def main(action):
    if action == "package":
        name, content = editor_plugins.package("gimp")
        os.makedirs(os.path.join(PLUGIN_DIR, "dist"), exist_ok=True)

        with open(os.path.join(PLUGIN_DIR, "dist", name), "wb") as file:
            file.write(content)

        print(f"dist/{name}")
    elif action == "deploy":
        print(f"Installed {editor_plugins.install_or_elevate('gimp')['version']} into {gimp_install.get_plugins_dir()}")
    elif action == "undeploy":
        plugins_dir = gimp_install.get_plugins_dir()

        if plugins_dir:
            shutil.rmtree(os.path.join(plugins_dir, gimp_install.PACKAGE_NAME), ignore_errors=True)

        print("Removed")
    else:
        sys.exit(f"Unknown action: {action} (package, deploy or undeploy)")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "")
    except editor_plugins.PluginError as e:
        sys.exit(str(e))
