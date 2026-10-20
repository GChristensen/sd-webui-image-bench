"""
Krita plugin management from a shell (just krita-package / krita-deploy / krita-undeploy), through the same backend
code as the install card of the Image Bench manual:
  package  - Build dist/image_bench_<version>.zip, importable with Tools › Scripts › Import Python Plugin from File
  deploy   - Copy the plugin to Krita's Python plugin folder and enable it (Krita must be closed)
  undeploy - Remove the plugin installed by deploy
"""
import os
import shutil
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "..", "..", "common-extension"))

from shared_backend import editor_plugins, krita_install  # noqa: E402


def main(action):
    if action == "package":
        name, content = editor_plugins.package("krita")
        os.makedirs(os.path.join(PLUGIN_DIR, "dist"), exist_ok=True)

        with open(os.path.join(PLUGIN_DIR, "dist", name), "wb") as file:
            file.write(content)

        print(f"dist/{name}")
    elif action == "deploy":
        print(f"Installed {editor_plugins.install_or_elevate('krita')['version']}")
    elif action == "undeploy":
        plugins_dir, _ = krita_install.get_install_locations()
        shutil.rmtree(os.path.join(plugins_dir, krita_install.PACKAGE_NAME), ignore_errors=True)

        try:
            os.remove(os.path.join(plugins_dir, krita_install.PACKAGE_NAME + ".desktop"))
        except FileNotFoundError:
            pass

        print("Removed")
    else:
        sys.exit(f"Unknown action: {action} (package, deploy or undeploy)")


if __name__ == "__main__":
    try:
        main(sys.argv[1] if len(sys.argv) > 1 else "")
    except editor_plugins.PluginError as e:
        sys.exit(str(e))
