"""
The plugin controller: one connection for the Krita session, whether or not the docker is shown, the send actions
of the docker and of the Tools › Scripts › Image Bench menu, and the images received from Image Bench
"""
import json
import os

from krita import Extension, Krita
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QMenu, QMessageBox

from . import document
from .client import ClientError, ImageBenchClient

SETTINGS_GROUP = "image_bench"
DEFAULT_URL = "http://127.0.0.1:7860"
MAX_RECENT_URLS = 5
# The Tools › Scripts › Image Bench submenu
SUBMENU_ID = "image_bench_menu"

with open(os.path.join(os.path.dirname(__file__), "manifest.json"), encoding="utf-8") as _file:
    VERSION = json.load(_file)["version"]

# The extension instance, for the dockers (Krita creates them independently)
instance = None


def send_image(client):
    client.upload("image", document.read_image(document.active_document()))
    return "Image sent to the input image"


def send_mask(client):
    client.upload("mask", document.read_mask(document.active_document()))
    return "Mask sent to the input mask"


def send_image_and_mask(client):
    doc = document.active_document()
    # Read the selection first, so nothing is sent if there is no selection
    mask = document.read_mask(doc)
    client.upload("image", document.read_image(doc))
    client.upload("mask", mask)
    return "Image and mask sent to the input"


def send_controlnet_preprocess(client):
    client.upload("image", document.read_image(document.active_document()), "cn_preprocess")
    return "Image sent to the ControlNet preprocessor"


def send_controlnet_image(client):
    client.upload("image", document.read_image(document.active_document()), "cn_image")
    return "Image sent as the ControlNet control image"


def send_controlnet_mask(client):
    client.upload("mask", document.read_mask(document.active_document()), "cn_mask")
    return "Mask sent to ControlNet"


def send_compare(client):
    client.upload("image", document.read_image(document.active_document()), "compare")
    return "Image added to the Compare tab"


def _saved(result):
    return f"Saved {', '.join(result['files'])} in {result['project']}"


def save_file(client):
    return _saved(client.save_document("file", document.read_document(document.active_document())))


def save_final(client):
    doc = document.active_document()
    return _saved(client.save_document("final", document.read_document(doc), document.read_image(doc)))


# (id, menu text, docker button text, function), in the order of the docker groups
SEND_ACTIONS = [
    ("send_image", "Send Image", "Image", send_image),
    ("send_mask", "Send Mask", "Mask", send_mask),
    ("send_image_and_mask", "Send Image and Mask", "Image + Mask", send_image_and_mask),
    ("send_cn_preprocess", "Send to ControlNet Preprocessor", "Preprocess", send_controlnet_preprocess),
    ("send_cn_image", "Send ControlNet Image", "Image", send_controlnet_image),
    ("send_cn_mask", "Send ControlNet Mask", "Mask", send_controlnet_mask),
    ("send_compare", "Send to Compare", "Compare", send_compare),
    ("save_file", "Save to Project as File", "File", save_file),
    ("save_final", "Save to Project as Final", "Final", save_final),
]


class ImageBenchExtension(Extension):
    # Status text and whether it is an error
    statusChanged = pyqtSignal(str, bool)
    busyChanged = pyqtSignal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        global instance
        instance = self
        self.client = ImageBenchClient(VERSION, self)
        self.client.openImageRequested.connect(self._on_open_image)
        self.client.stateChanged.connect(self._on_state_changed)
        self._busy = 0
        self._sending = False

    def setup(self):
        self.client.connect_to(self.url())

    def createActions(self, window):
        # createAction() places actions only in existing menus, found by object name along the path:
        # the submenu is an action of Tools › Scripts holding a QMenu, named like the last part of the path
        submenu = window.createAction(SUBMENU_ID, "Image Bench", "tools/scripts")
        submenu.setMenu(QMenu("Image Bench", window.qwindow()))

        for action_id, text, _, function in SEND_ACTIONS:
            action = window.createAction(f"image_bench_{action_id}", text, f"tools/scripts/{SUBMENU_ID}")
            action.triggered.connect(lambda checked=False, function=function: self.run(function))

    # ---------- Settings ----------

    def url(self):
        return Krita.instance().readSetting(SETTINGS_GROUP, "url", "") or DEFAULT_URL

    def recent_urls(self):
        try:
            urls = json.loads(Krita.instance().readSetting(SETTINGS_GROUP, "recentUrls", "[]"))
            return [url for url in urls if isinstance(url, str)]
        except ValueError:
            return []

    def set_url(self, url):
        """Save the URL and reconnect"""
        Krita.instance().writeSetting(SETTINGS_GROUP, "url", url.strip())
        self.client.connect_to(self.url())

    def _on_state_changed(self, state):
        # Put a URL the plugin connected to at the top of the recent ones
        if state == "connected":
            url = self.client.url()
            urls = [url] + [u for u in self.recent_urls() if u != url]
            Krita.instance().writeSetting(SETTINGS_GROUP, "recentUrls", json.dumps(urls[:MAX_RECENT_URLS]))

    # ---------- Sending ----------

    def _set_busy(self, busy, text=None):
        self._busy = max(0, self._busy + (1 if busy else -1))

        if busy:
            self.statusChanged.emit(f"{text}...", False)

        self.busyChanged.emit(self._busy > 0)

    def run(self, function, from_docker=False):
        """
        Run a send action, reporting the result in the docker, or errors in a message box when invoked from the menu
        """
        # One send at a time: double clicks would send twice
        if self._sending:
            return

        self._sending = True
        self._set_busy(True, "Sending")

        try:
            result, failure = function(self.client), None
        except (ClientError, document.DocumentError) as error:
            result, failure = None, str(error)
        finally:
            self._sending = False
            self._set_busy(False)

        if failure is None:
            self.statusChanged.emit(result, False)
        else:
            self.statusChanged.emit(failure, True)

            if not from_docker:
                self._alert(failure)

    @staticmethod
    def _alert(message):
        window = Krita.instance().activeWindow()
        QMessageBox.warning(window.qwindow() if window else None, "Image Bench", message)

    # ---------- Receiving ----------

    def _on_open_image(self, msg):
        """Place an image sent from Image Bench as a layer of the active document, or open it as a new document"""
        name = msg.get("name") or "image.png"
        self._set_busy(True, f"Receiving {name}")
        error = None

        try:
            data = self.client.download(msg["imageUrl"])
            doc = Krita.instance().activeDocument()

            if doc is not None and not msg.get("newDocument"):
                document.place_layer(doc, data, os.path.splitext(name)[0])
            else:
                document.open_document(data, os.path.splitext(name)[0])
        except (ClientError, document.DocumentError, KeyError) as e:
            error = str(e)

        self._set_busy(False)

        if msg.get("requestId"):
            self.client.send_json({"type": "OPEN_IMAGE_DONE", "requestId": msg["requestId"],
                                   **({"error": error} if error else {})})

        self.statusChanged.emit(error or f"Received {name}", bool(error))
