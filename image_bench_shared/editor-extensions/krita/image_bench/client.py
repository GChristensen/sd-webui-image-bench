"""
The connection to the Image Bench backend of SD WebUI or ComfyUI (see editor-extensions/PROTOCOL.md): uploads of the
document and its selection, and the WebSocket over which the backend sends images to open. No Krita API here.
"""
import json
from urllib.parse import urlencode

from PyQt5.QtCore import QByteArray, QEventLoop, QObject, QTimer, QUrl, pyqtSignal
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .websocket import WebSocketClient

EDITOR_NAME = "Krita"
WEBSOCKET_PATH = "/image-bench/editor/websocket"
UPLOAD_PATH = "/image-bench/editor/upload"
PROJECT_PATH = "/image-bench/editor/project"
RECONNECT_DELAY = 5000
# Close code of a connection replaced by another editor, which is not restored on its own (editor.REPLACED_CLOSE_CODE)
REPLACED_CLOSE_CODE = 4000
REQUEST_TIMEOUT = 60000


class ClientError(Exception):
    pass


class ImageBenchClient(QObject):
    # "connected", "connecting", "disconnected" or "replaced" (by another editor)
    stateChanged = pyqtSignal(str)
    # An OPEN_IMAGE message: {requestId, name, imageUrl, newDocument}
    openImageRequested = pyqtSignal(dict)

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self._version = version
        self._url = ""
        self._network = QNetworkAccessManager(self)
        self._socket = WebSocketClient(self)
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textReceived.connect(self._on_message)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._connect)
        self.state = "disconnected"

    def url(self):
        return self._url

    def connect_to(self, url):
        """Connect to the server at url (http://host:port), dropping the current connection"""
        self._url = url.strip().rstrip("/")
        self._connect()

    def _set_state(self, state):
        self.state = state
        self.stateChanged.emit(state)

    def _connect(self):
        self._reconnect_timer.stop()
        self._set_state("connecting")

        try:
            self._socket.open(self._url.replace("http", "ws", 1) + WEBSOCKET_PATH)
        except ValueError:
            self._on_disconnected(0)

    def _on_connected(self):
        self._set_state("connected")
        # The server then waits for OPEN_IMAGE_DONE, so that Image Bench shows the transfer until it ends
        self.send_json({"type": "HELLO", "editor": EDITOR_NAME, "version": self._version, "acks": True})

    def _on_disconnected(self, code):
        if code == REPLACED_CLOSE_CODE:
            self._set_state("replaced")
            return

        self._set_state("disconnected")
        self._reconnect_timer.start(RECONNECT_DELAY)

    def _on_message(self, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return

        if msg.get("type") == "OPEN_IMAGE":
            self.openImageRequested.emit(msg)

    def send_json(self, msg):
        self._socket.send_text(json.dumps(msg))

    def _wait(self, reply):
        """Wait for a reply, keeping Krita responsive; returns its body"""
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(reply.abort)
        reply.finished.connect(loop.quit)
        timer.start(REQUEST_TIMEOUT)

        if not reply.isFinished():
            loop.exec_()

        timer.stop()
        body = bytes(reply.readAll())
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        error = reply.error()
        reply.deleteLater()

        if status is not None and not 200 <= status < 300:
            text = body.decode("utf-8", errors="replace")

            # The message of a JSON error ({"error"} of Image Bench, {"detail"} of FastAPI)
            try:
                message = json.loads(text)
                text = message.get("error") or message.get("detail") or text
            except (ValueError, AttributeError):
                pass

            raise ClientError(f"The server responded with {status}: {text}")

        if error != QNetworkReply.NoError:
            raise ClientError(f"Unable to connect to {self._url}")

        return body

    def upload(self, kind, pixels, target="input"):
        """
        Send raw pixels to the backend, which forwards them to the connected WebUI or ComfyUI pages
        :param kind: "image" or "mask"
        :param pixels: (data, width, height, components), 8-bit R,G,B(,A) or a 1-component mask
        :param target: "input", "cn_preprocess", "cn_image", "cn_mask" or "compare"
        """
        data, width, height, components = pixels
        query = urlencode({"kind": kind, "width": width, "height": height, "components": components,
                           "target": target})
        request = QNetworkRequest(QUrl(f"{self._url}{UPLOAD_PATH}?{query}"))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/octet-stream")
        result = json.loads(self._wait(self._network.post(request, QByteArray(data))) or b"{}")

        # Images of the Compare tab are saved by the server and shown when the Image Bench window opens
        if not result.get("clients") and not result.get("saved"):
            raise ClientError("No WebUI or ComfyUI page is open")

    def save_document(self, save, psd, pixels=None):
        """
        Save the document into the folder of the current project of Image Bench
        :param save: "file" (<project>-NNN.psd) or "final" (final-NNN.psd, .png and .jpg, the project's final image)
        :param psd: the document as a PSD file
        :param pixels: the merged image as (data, width, height, components) for "final"
        :return: {"project": name, "files": names of the files written}
        """
        query = {"save": save, "psd": len(psd)}
        body = psd

        if pixels is not None:
            data, width, height, components = pixels
            query.update(width=width, height=height, components=components)
            body = psd + data

        request = QNetworkRequest(QUrl(f"{self._url}{PROJECT_PATH}?{urlencode(query)}"))
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/octet-stream")

        try:
            return json.loads(self._wait(self._network.post(request, QByteArray(body))))
        except ValueError:
            raise ClientError("The server sent an invalid response") from None

    def download(self, path):
        """Fetch a file by its URL relative to the server"""
        return self._wait(self._network.get(QNetworkRequest(QUrl(self._url + path))))
