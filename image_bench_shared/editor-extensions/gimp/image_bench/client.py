"""
The connection to the Image Bench backend of SD WebUI or ComfyUI (see editor-extensions/PROTOCOL.md): uploads of the
image and its selection, and the WebSocket over which the backend sends images to open. No GIMP API here.

upload() and download() block: the panel runs them in a thread, the menu procedures directly.
"""
import http.client
import json
from urllib.parse import urlencode, urlsplit

from gi.repository import GLib

import net
from websocket import WebSocketClient

EDITOR_NAME = "GIMP"
WEBSOCKET_PATH = "/image-bench/editor/websocket"
UPLOAD_PATH = "/image-bench/editor/upload"
PROJECT_PATH = "/image-bench/editor/project"
RECONNECT_DELAY = 5000
# Close code of a connection replaced by another editor, which is not restored on its own (editor.REPLACED_CLOSE_CODE)
REPLACED_CLOSE_CODE = 4000
REQUEST_TIMEOUT = 60


class ClientError(Exception):
    pass


class ImageBenchClient:

    def __init__(self, version, url=""):
        self._version = version
        self._url = url.strip().rstrip("/")
        self._socket = None
        self._reconnect_source = None
        # "connected", "connecting", "disconnected" or "replaced" (by another editor)
        self.state = "disconnected"
        # Called with the state
        self.on_state_changed = None
        # Called with an OPEN_IMAGE message: {requestId, name, imageUrl, newDocument}
        self.on_open_image = None

    def url(self):
        return self._url

    # ---------- WebSocket (main loop) ----------

    def connect_to(self, url):
        """Connect to the server at url (http://host:port), dropping the current connection"""
        self._url = url.strip().rstrip("/")

        if self._socket is None:
            self._socket = WebSocketClient(self._on_connected, self._on_disconnected, self._on_message)

        self._connect()

    def _set_state(self, state):
        self.state = state

        if self.on_state_changed:
            self.on_state_changed(state)

    def _connect(self):
        self._cancel_reconnect()
        self._set_state("connecting")

        try:
            self._socket.open(self._url.replace("http", "ws", 1) + WEBSOCKET_PATH)
        except ValueError:
            self._on_disconnected(0)

        return False

    def _cancel_reconnect(self):
        if self._reconnect_source is not None:
            GLib.source_remove(self._reconnect_source)
            self._reconnect_source = None

    def _on_connected(self):
        self._set_state("connected")
        # The server then waits for OPEN_IMAGE_DONE, so that Image Bench shows the transfer until it ends
        self.send_json({"type": "HELLO", "editor": EDITOR_NAME, "version": self._version, "acks": True})

    def _on_disconnected(self, code):
        if code == REPLACED_CLOSE_CODE:
            self._set_state("replaced")
            return

        self._set_state("disconnected")
        self._cancel_reconnect()

        def reconnect():
            self._reconnect_source = None
            return self._connect()

        self._reconnect_source = GLib.timeout_add(RECONNECT_DELAY, reconnect)

    def _on_message(self, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return

        if msg.get("type") == "OPEN_IMAGE" and self.on_open_image:
            self.on_open_image(msg)

    def send_json(self, msg):
        if self._socket is not None:
            self._socket.send_text(json.dumps(msg))

    def close(self):
        self._cancel_reconnect()

        if self._socket is not None:
            self._socket.abort()

    # ---------- HTTP (any thread) ----------

    def _request(self, method, path, body=None, headers=None):
        """The body of the response to a request of a path of the server (net.connect: not urllib)"""
        parts = urlsplit(self._url)
        connection_class = net.HTTPSConnection if parts.scheme == "https" else net.HTTPConnection

        try:
            connection = connection_class(parts.hostname, parts.port, timeout=REQUEST_TIMEOUT)
        except (ValueError, TypeError):
            raise ClientError(f"Not a server address: {self._url}") from None

        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            data = response.read()
        except (OSError, http.client.HTTPException, ValueError):
            raise ClientError(f"Unable to connect to {self._url}") from None
        finally:
            connection.close()

        if not 200 <= response.status < 300:
            text = data.decode("utf-8", errors="replace")

            # The message of a JSON error ({"error"} of Image Bench, {"detail"} of FastAPI)
            try:
                body = json.loads(text)
                text = body.get("error") or body.get("detail") or text
            except (ValueError, AttributeError):
                pass

            raise ClientError(f"The server responded with {response.status}: {text}")

        return data

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
        response = self._request("POST", f"{UPLOAD_PATH}?{query}", data,
                                 {"Content-Type": "application/octet-stream"})

        try:
            result = json.loads(response or b"{}")
        except ValueError:
            result = {}

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

        response = self._request("POST", f"{PROJECT_PATH}?{urlencode(query)}", body,
                                 {"Content-Type": "application/octet-stream"})

        try:
            return json.loads(response)
        except ValueError:
            raise ClientError("The server sent an invalid response") from None

    def download(self, path):
        """Fetch a file by its URL relative to the server"""
        return self._request("GET", path)
