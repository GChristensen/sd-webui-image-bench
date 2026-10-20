#!/usr/bin/env python3
"""
The Image Bench plugin for GIMP 3: the send commands of the Tools › Image Bench menu, each run in its own process, and the
panel, whose process holds the connection to Image Bench while it runs (see editor-extensions/PROTOCOL.md).

Only one panel runs: it installs a temporary procedure, and Tools › Image Bench › Panel calls it when it exists, so the
running panel shows itself instead of a second one taking the connection from it.
"""
import json
import os
import sys

import gi

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp, GLib, GObject  # noqa: E402

import actions  # noqa: E402
import settings  # noqa: E402
from client import ClientError, ImageBenchClient  # noqa: E402
from document import DocumentError  # noqa: E402

# GIMP 3 shows no new top-level menus of plug-ins: a submenu of Tools
MENU_PATH = "<Image>/Tools/Image Bench"
PANEL_PROC = "plug-in-image-bench-panel"
# Installed by the running panel
SHOW_PANEL_PROC = "plug-in-image-bench-panel-show"
SEND_PROC_PREFIX = "plug-in-image-bench-"

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json"), encoding="utf-8") as _file:
    VERSION = json.load(_file)["version"]

ATTRIBUTION = ("Image Bench", "Image Bench", "2026")


def _send_proc_name(action_id):
    return SEND_PROC_PREFIX + action_id.replace("_", "-")


def _success(procedure):
    return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, GLib.Error())


def run_send(procedure, run_mode, image, drawables, config, action_id):
    try:
        reads = actions.read_pixels(action_id, image)
        actions.upload(ImageBenchClient(VERSION, settings.url()), action_id, reads)
    except (ClientError, DocumentError) as e:
        return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(str(e)))

    return _success(procedure)


def run_panel(procedure, run_mode, image, drawables, config, data):
    pdb = Gimp.get_pdb()

    if pdb.procedure_exists(SHOW_PANEL_PROC):
        show = pdb.lookup_procedure(SHOW_PANEL_PROC)
        show_config = show.create_config()
        show_config.set_property("run-mode", Gimp.RunMode.NONINTERACTIVE)
        show_config.set_property("image", image)
        show.run(show_config)
        return _success(procedure)

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk
    import panel as panel_module

    plug_in = procedure.get_plug_in()
    panel = panel_module.create(VERSION, image)

    def run_show(show_procedure, show_config, _):
        panel.present_with_image(show_config.get_property("image"))
        return _success(show_procedure)

    show = Gimp.Procedure.new(plug_in, SHOW_PANEL_PROC, Gimp.PDBProcType.TEMPORARY, run_show, None)
    show.set_documentation("Show the running Image Bench panel", "", SHOW_PANEL_PROC)
    show.set_attribution(*ATTRIBUTION)
    show.add_enum_argument("run-mode", "Run mode", "The run mode", Gimp.RunMode, Gimp.RunMode.NONINTERACTIVE,
                           GObject.ParamFlags.READWRITE)
    show.add_image_argument("image", "Image", "The image to select in the panel", True,
                            GObject.ParamFlags.READWRITE)
    plug_in.add_temp_procedure(show)
    # Calls of the temporary procedure arrive on the main loop
    plug_in.persistent_enable()

    Gtk.main()
    plug_in.remove_temp_procedure(SHOW_PANEL_PROC)
    return _success(procedure)


class ImageBench(Gimp.PlugIn):

    def do_query_procedures(self):
        return [PANEL_PROC] + [_send_proc_name(action[0]) for action in actions.SEND_ACTIONS]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        if name == PANEL_PROC:
            procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_panel, None)
            procedure.set_menu_label("_Panel...")
            procedure.set_documentation("Show the Image Bench panel",
                                        "Send images to SD WebUI or ComfyUI with the Image Bench extension, "
                                        "and receive the images sent from Image Bench while the panel runs", name)
            # Also without an image
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE
                                           | Gimp.ProcedureSensitivityMask.DRAWABLES
                                           | Gimp.ProcedureSensitivityMask.NO_DRAWABLES
                                           | Gimp.ProcedureSensitivityMask.NO_IMAGE)
        else:
            action = next(action for action in actions.SEND_ACTIONS if _send_proc_name(action[0]) == name)
            action_id, menu_text, _, _, result = action
            procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, run_send, action_id)
            procedure.set_menu_label(menu_text)
            procedure.set_documentation(menu_text.replace("_", ""), f"{result} (Image Bench)", name)
            procedure.set_sensitivity_mask(Gimp.ProcedureSensitivityMask.DRAWABLE
                                           | Gimp.ProcedureSensitivityMask.DRAWABLES
                                           | Gimp.ProcedureSensitivityMask.NO_DRAWABLES)

        procedure.set_image_types("*")
        procedure.set_attribution(*ATTRIBUTION)
        procedure.add_menu_path(MENU_PATH)
        return procedure


Gimp.main(ImageBench.__gtype__, sys.argv)
