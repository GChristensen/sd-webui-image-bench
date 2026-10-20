"""
A small WebSocket client (RFC 6455, text messages only) over QTcpSocket / QSslSocket: Krita's PyQt5 has QtNetwork,
but not necessarily QtWebSockets. It runs on the Qt event loop, so its signals arrive on the main thread.
"""
import base64
import os
import struct

from PyQt5.QtCore import QObject, QUrl, pyqtSignal
from PyQt5.QtNetwork import QAbstractSocket, QTcpSocket

try:
    from PyQt5.QtNetwork import QSslSocket
except ImportError:
    QSslSocket = None

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


class WebSocketClient(QObject):
    connected = pyqtSignal()
    # The close code sent by the server, 0 without one
    disconnected = pyqtSignal(int)
    textReceived = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._socket = None
        self._buffer = b""
        self._handshaken = False
        self._fragments = None
        self._open = False

    def open(self, url):
        """Connect to a ws:// or wss:// URL; disconnected is emitted if it fails"""
        self.abort()
        url = QUrl(url)
        secure = url.scheme() == "wss"

        if secure and (QSslSocket is None or not QSslSocket.supportsSsl()):
            raise ValueError("Secure connections (https) are not supported by this Krita")

        self._socket = socket = QSslSocket(self) if secure else QTcpSocket(self)
        self._buffer, self._handshaken, self._fragments = b"", False, None
        path = url.path() or "/"
        port = url.port(443 if secure else 80)
        host = url.host()

        def on_connected():
            key = base64.b64encode(os.urandom(16)).decode()
            socket.write((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                          f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
                         .encode())

        socket.readyRead.connect(lambda: socket is self._socket and self._on_ready_read())
        socket.disconnected.connect(lambda: socket is self._socket and self._on_closed())
        # errorOccurred since Qt 5.15, error before
        error_signal = getattr(socket, "errorOccurred", None) or socket.error
        error_signal.connect(lambda _: socket is self._socket and self._on_closed())

        if secure:
            socket.encrypted.connect(on_connected)
            socket.connectToHostEncrypted(host, port)
        else:
            socket.connected.connect(on_connected)
            socket.connectToHost(host, port)

    def abort(self):
        """Drop the connection without emitting disconnected"""
        socket, self._socket = self._socket, None
        self._open = False

        if socket:
            socket.abort()
            socket.deleteLater()

    def is_open(self):
        return self._open

    def send_text(self, text):
        if self._open:
            self._send_frame(OPCODE_TEXT, text.encode("utf-8"))

    def _send_frame(self, opcode, payload):
        header = bytes([0x80 | opcode])
        length = len(payload)

        # Client frames are masked
        if length < 126:
            header += bytes([0x80 | length])
        elif length < 1 << 16:
            header += bytes([0x80 | 126]) + struct.pack(">H", length)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", length)

        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self._socket.write(header + mask + masked)

    def _on_closed(self, code=0):
        was_connected = self._socket is not None
        self.abort()

        if was_connected:
            self.disconnected.emit(code)

    def _on_ready_read(self):
        self._buffer += bytes(self._socket.readAll())

        if not self._handshaken:
            end = self._buffer.find(b"\r\n\r\n")

            if end < 0:
                return

            status_line = self._buffer[:self._buffer.find(b"\r\n")]
            self._buffer = self._buffer[end + 4:]

            if b" 101 " not in status_line + b" ":
                self._on_closed()
                return

            self._handshaken = self._open = True
            self.connected.emit()

        while self._socket is not None and self._read_frame():
            pass

    def _read_frame(self):
        """Handle one complete frame of the buffer; False if it holds no complete frame"""
        data = self._buffer

        if len(data) < 2:
            return False

        fin, opcode = data[0] & 0x80, data[0] & 0x0F
        masked, length = data[1] & 0x80, data[1] & 0x7F
        offset = 2

        if length == 126:
            if len(data) < 4:
                return False
            length, offset = struct.unpack(">H", data[2:4])[0], 4
        elif length == 127:
            if len(data) < 10:
                return False
            length, offset = struct.unpack(">Q", data[2:10])[0], 10

        mask = data[offset:offset + 4] if masked else None
        offset += 4 if masked else 0

        if len(data) < offset + length:
            return False

        payload = data[offset:offset + length]
        self._buffer = data[offset + length:]

        if mask:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

        if opcode == OPCODE_PING:
            self._send_frame(OPCODE_PONG, payload)
        elif opcode == OPCODE_CLOSE:
            self._send_frame(OPCODE_CLOSE, payload[:2])
            self._on_closed(struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 0)
        elif opcode == OPCODE_TEXT:
            self._fragments = payload
        elif opcode == OPCODE_CONTINUATION and self._fragments is not None:
            self._fragments += payload

        if fin and opcode in (OPCODE_TEXT, OPCODE_CONTINUATION) and self._fragments is not None:
            text, self._fragments = self._fragments, None
            self.textReceived.emit(text.decode("utf-8", errors="replace"))

        return True
