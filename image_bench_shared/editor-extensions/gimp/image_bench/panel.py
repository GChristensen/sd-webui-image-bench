"""
The Image Bench panel: the server URL with the connection state, the image to work on, the send buttons and the status
of the last transfer. GIMP plug-ins cannot add dockable dialogs, so it is a window of the panel process, which holds
the connection while it runs. Closing the window hides it; Quit ends the process and the connection.
"""
import os
import threading
import time

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("GimpUi", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gimp, GimpUi, GLib, Gtk  # noqa: E402

import actions  # noqa: E402
import document  # noqa: E402
import settings  # noqa: E402
from client import ClientError, ImageBenchClient  # noqa: E402

CONNECTION_STATES = {
    "connected": ("Connected", "Connected to the server: click to reconnect", "#3fb950"),
    "connecting": ("Connecting...", "Connecting to the server: click to retry", "#d29922"),
    "disconnected": ("Reconnect", "Not connected to the server: click to reconnect", "#f85149"),
    "replaced": ("Reconnect", "Another editor connected to the server: click to take the connection", "#8b949e"),
}

ERROR_COLOR = "#f85149"

# Panel groups: (title, ids of actions.SEND_ACTIONS)
GROUPS = [
    ("Input / Inpaint", ("send_image", "send_mask", "send_image_and_mask")),
    ("ControlNet", ("send_cn_preprocess", "send_cn_image", "send_cn_mask")),
    ("Keep", ("send_compare", "save_file", "save_final")),
]

# The window size and position in the settings
GEOMETRY_SETTING = "panelGeometry"


def _in_thread(work, done):
    """
    Run work() in a thread, then done(result, error, seconds) on the main loop (error: a ClientError message,
    seconds: the time work() took)
    """
    def run():
        start = time.monotonic()

        try:
            result, error = work(), None
        except ClientError as e:
            result, error = None, str(e)

        seconds = time.monotonic() - start
        GLib.idle_add(lambda: done(result, error, seconds) and False)

    threading.Thread(target=run, daemon=True).start()


class Panel(Gtk.Window):

    def __init__(self, version, image=None):
        super().__init__(title="Image Bench")
        self.set_border_width(8)
        self.set_default_size(360, -1)
        self._buttons = []
        self._busy = 0
        self._sending = False
        self._filling = False

        self.client = ImageBenchClient(version)
        self.client.on_state_changed = self._on_state_changed
        self.client.on_open_image = self._on_open_image

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(root)

        url_row = Gtk.Box(spacing=6)
        self._url = Gtk.ComboBoxText.new_with_entry()
        self._url.set_tooltip_text("SD WebUI or ComfyUI with the Image Bench extension")
        self._url.get_child().connect("activate", lambda _: self._apply_url())
        self._url.connect("changed", lambda combo: combo.get_active() >= 0 and self._apply_url())
        url_row.pack_start(self._url, True, True, 0)

        self._dot = Gtk.Label()
        url_row.pack_start(self._dot, False, False, 0)
        self._connection = Gtk.Button()
        self._connection.connect("clicked", lambda _: self._apply_url())
        url_row.pack_start(self._connection, False, False, 0)
        root.pack_start(url_row, False, False, 0)

        image_row = Gtk.Box(spacing=6)
        image_row.pack_start(Gtk.Label(label="Image"), False, False, 0)
        self._image = Gtk.ComboBoxText()
        self._image.set_tooltip_text("The image sent by the buttons, and the image that receives the layers "
                                     "sent from Image Bench")
        self._image.connect("notify::popup-shown", lambda combo, _: combo.get_property("popup-shown")
                            and self.refresh_images())
        image_row.pack_start(self._image, True, True, 0)
        root.pack_start(image_row, False, False, 0)

        titles = {action_id: text for action_id, _, text, _, _ in actions.SEND_ACTIONS}

        for title, ids in GROUPS:
            frame = Gtk.Frame(label=title)
            box = Gtk.Box(spacing=6, homogeneous=True)
            box.set_border_width(6)

            for action_id in ids:
                button = Gtk.Button(label=titles[action_id])
                button.connect("clicked", lambda _, action_id=action_id: self.run_action(action_id))
                box.pack_start(button, True, True, 0)
                self._buttons.append(button)

            frame.add(box)
            root.pack_start(frame, False, False, 0)

        self._status = Gtk.Label(xalign=0)
        self._status.set_line_wrap(True)
        self._status.set_selectable(True)
        root.pack_start(self._status, False, False, 0)

        bottom = Gtk.Box(spacing=6)
        quit_button = Gtk.Button(label="Quit")
        quit_button.set_tooltip_text("Close the panel and the connection: images sent from Image Bench are then "
                                     "not received until the panel is opened again")
        quit_button.connect("clicked", lambda _: self.quit())
        bottom.pack_end(quit_button, False, False, 0)
        root.pack_end(bottom, False, False, 0)

        self.connect("delete-event", self._on_delete)
        self.connect("focus-in-event", lambda *_: self.refresh_images() and False)

        self._restore_geometry()
        self._fill_urls()
        self.refresh_images(image)
        self._on_state_changed(self.client.state)
        self.client.connect_to(settings.url())

    # ---------- Window ----------

    def present_with_image(self, image=None):
        if image is not None:
            self.refresh_images(image)

        self.show_all()
        self.present()

    def _restore_geometry(self):
        geometry = settings.load().get(GEOMETRY_SETTING)

        if isinstance(geometry, list) and len(geometry) == 4 and all(isinstance(v, int) for v in geometry):
            x, y, width, height = geometry
            self.move(x, y)
            self.resize(width, height)

    def _save_geometry(self):
        x, y = self.get_position()
        width, height = self.get_size()
        settings.save(**{GEOMETRY_SETTING: [x, y, width, height]})

    def _on_delete(self, *_):
        # Hidden, not closed: the connection lasts until Quit
        self._save_geometry()
        self.hide()
        return True

    def quit(self):
        self._save_geometry()
        self.client.close()
        self.destroy()
        Gtk.main_quit()

    # ---------- Connection ----------

    def _fill_urls(self):
        current = settings.url()
        # Filling the list fires changed, which would reconnect
        self._filling = True
        self._url.remove_all()

        for url in [current] + [url for url in settings.recent_urls() if url != current]:
            self._url.append_text(url)

        self._url.set_active(0)
        self._filling = False

    def _apply_url(self):
        if self._filling:
            return

        url = self._url.get_active_text().strip()
        settings.save(url=url)
        self.client.connect_to(settings.url())

    def _on_state_changed(self, state):
        label, tooltip, color = CONNECTION_STATES[state]
        self._connection.set_label(label)
        self._connection.set_tooltip_text(tooltip)
        self._dot.set_markup(f'<span foreground="{color}">●</span>')

        if state == "connected":
            settings.add_recent_url(self.client.url())
            self._fill_urls()

    # ---------- Images ----------

    def refresh_images(self, select=None):
        """List the open images, keeping the selected one (or selecting the given image)"""
        selected = select.get_id() if select is not None else self._selected_image_id()
        self._image.remove_all()
        images = Gimp.get_images()

        for image in images:
            self._image.append(str(image.get_id()), f"{image.get_name()}-{image.get_id()}")

        if images and not self._image.set_active_id(str(selected)):
            self._image.set_active(0)

        return True

    def _selected_image_id(self):
        active = self._image.get_active_id()
        return int(active) if active else None

    def selected_image(self):
        """The image chosen in the panel, or another open image if it was closed; None without images"""
        image = document.find_image(self._selected_image_id())

        if image is None:
            self.refresh_images()
            image = document.find_image(self._selected_image_id())

        return image

    # ---------- Status ----------

    def _set_status(self, text, is_error=False, timings=None):
        """
        :param timings: the steps of a transfer and their times, [(step, seconds)], shown as the total time
            and in the tooltip
        """
        if timings and not is_error:
            text += f" ({sum(seconds for _, seconds in timings):.1f} s)"

        self._status.set_tooltip_text(", ".join(f"{step} {seconds:.2f} s" for step, seconds in timings or ()) or None)
        text = GLib.markup_escape_text(text)
        self._status.set_markup(f'<span foreground="{ERROR_COLOR}">{text}</span>' if is_error else text)

    def _set_busy(self, busy, text=None):
        self._busy = max(0, self._busy + (1 if busy else -1))

        if busy:
            self._set_status(f"{text}...")

        for button in self._buttons:
            button.set_sensitive(self._busy == 0)

    # ---------- Sending ----------

    def run_action(self, action_id):
        # One send at a time: double clicks would send twice
        if self._sending:
            return

        image = self.selected_image()

        if image is None:
            self._set_status("No image is open", True)
            return

        start = time.monotonic()

        try:
            reads = actions.read_pixels(action_id, image)
        except document.DocumentError as e:
            self._set_status(str(e), True)
            return

        read_seconds = time.monotonic() - start
        self._sending = True
        self._set_busy(True, "Sending")

        def done(result, error, upload_seconds):
            self._sending = False
            self._set_busy(False)
            total = time.monotonic() - start
            self._set_status(error or result, bool(error),
                             [("reading", read_seconds), ("upload", upload_seconds),
                              ("waiting", total - read_seconds - upload_seconds)])

        _in_thread(lambda: actions.upload(self.client, action_id, reads), done)

    # ---------- Receiving ----------

    def _on_open_image(self, msg):
        """Place an image sent from Image Bench as a layer of the panel's image, or open it as a new image"""
        name = msg.get("name") or "image.png"
        self._set_busy(True, f"Receiving {name}")
        start = time.monotonic()

        def done(data, error, download_seconds=0.0):
            place_start = time.monotonic()

            if error is None:
                try:
                    image = self.selected_image()

                    if image is not None and not msg.get("newDocument"):
                        document.place_layer(image, data, name)
                    else:
                        self.refresh_images(document.open_image(data, name))
                except document.DocumentError as e:
                    error = str(e)

            self._set_busy(False)

            if msg.get("requestId"):
                self.client.send_json({"type": "OPEN_IMAGE_DONE", "requestId": msg["requestId"],
                                       **({"error": error} if error else {})})

            end = time.monotonic()
            self._set_status(error or f"Received {os.path.splitext(name)[0]}", bool(error),
                             [("download", download_seconds), ("placing", end - place_start),
                              ("waiting", place_start - start - download_seconds)])

        image_url = msg.get("imageUrl")

        if not image_url:
            done(None, "The message has no image URL")
            return

        _in_thread(lambda: self.client.download(image_url), done)


def create(version, image=None):
    """Create and show the panel; the caller runs Gtk.main() until it is quit"""
    GimpUi.init("image_bench")
    panel = Panel(version, image)
    GimpUi.window_set_transient(panel)
    panel.show_all()
    return panel
