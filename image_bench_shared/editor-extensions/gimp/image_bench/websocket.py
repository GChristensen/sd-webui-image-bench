"""
A small WebSocket client (RFC 6455, text messages only) over a socket read by a thread: GIMP's Python has no
WebSocket module. The callbacks run on the GLib main loop (GLib.idle_add), where the GIMP API may be called.
"""
import base64
import os
import ssl
import struct
import threading
from urllib.parse import urlsplit

from gi.repository import GLib

import net

OPCODE_CONTINUATION = 0x0
OPCODE_TEXT = 0x1
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

CONNECT_TIMEOUT = 10


class WebSocketClient:

    def __init__(self, on_open, on_close, on_text):
        """
        :param on_open: called when the connection is established
        :param on_close: called with the close code sent by the server (0 without one) when it is lost or fails
        :param on_text: called with each text message
        """
        self._on_open, self._on_close, self._on_text = on_open, on_close, on_text
        self._socket = None
        self._lock = threading.Lock()
        # Incremented by each open and abort: callbacks of an older connection are dropped
        self._generation = 0
        self._open = False

    def open(self, url):
        """Connect to a ws:// or wss:// URL; on_close is called if it fails"""
        self.abort()
        parts = urlsplit(url)

        if parts.scheme not in ("ws", "wss") or not parts.hostname:
            raise ValueError(f"Not a WebSocket URL: {url}")

        generation = self._generation
        threading.Thread(target=self._run, args=(generation, parts), daemon=True).start()

    def abort(self):
        """Drop the connection without calling on_close"""
        with self._lock:
            self._generation += 1
            sock, self._socket = self._socket, None
            self._open = False

        if sock:
            try:
                sock.close()
            except OSError:
                pass

    def is_open(self):
        return self._open

    def send_text(self, text):
        if self._open:
            self._send_frame(OPCODE_TEXT, text.encode("utf-8"))

    def _dispatch(self, generation, callback, *args):
        """Run a callback on the main loop unless the connection was replaced meanwhile"""
        def run():
            if generation == self._generation:
                callback(*args)
            return False

        GLib.idle_add(run)

    def _send_frame(self, opcode, payload, sock=None):
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

        with self._lock:
            sock = sock or self._socket

            if sock is not None:
                try:
                    sock.sendall(header + mask + masked)
                except OSError:
                    pass

    def _run(self, generation, parts):
        secure = parts.scheme == "wss"
        port = parts.port or (443 if secure else 80)
        close_code = 0
        sock = None

        try:
            sock = net.connect(parts.hostname, port, CONNECT_TIMEOUT)

            if secure:
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parts.hostname)

            with self._lock:
                if generation != self._generation:
                    sock.close()
                    return

                self._socket = sock

            key = base64.b64encode(os.urandom(16)).decode()
            sock.sendall((f"GET {parts.path or '/'} HTTP/1.1\r\nHost: {parts.hostname}:{port}\r\n"
                          f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                          f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
            buffer = b""

            while b"\r\n\r\n" not in buffer:
                chunk = sock.recv(4096)

                if not chunk:
                    raise OSError("Connection closed during the handshake")

                buffer += chunk

            end = buffer.find(b"\r\n\r\n")
            status_line = buffer[:buffer.find(b"\r\n")]
            buffer = buffer[end + 4:]

            if b" 101 " not in status_line + b" ":
                raise OSError(f"Handshake refused: {status_line.decode(errors='replace')}")

            # The connection lasts until the server closes it: no read timeout
            sock.settimeout(None)
            self._open = True
            self._dispatch(generation, self._on_open)
            close_code = self._read_frames(generation, sock, buffer)
        except (OSError, ValueError):
            pass

        with self._lock:
            if generation != self._generation:
                return

            self._socket = None
            self._open = False

        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

        self._dispatch(generation, self._on_close, close_code)

    def _read_frames(self, generation, sock, buffer):
        """Read frames until the connection ends; returns the close code (0 without one)"""
        fragments = None

        def read_exactly(count):
            nonlocal buffer

            while len(buffer) < count:
                chunk = sock.recv(65536)

                if not chunk:
                    raise OSError("Connection closed")

                buffer += chunk

            data, buffer = buffer[:count], buffer[count:]
            return data

        while True:
            head = read_exactly(2)
            fin, opcode = head[0] & 0x80, head[0] & 0x0F
            masked, length = head[1] & 0x80, head[1] & 0x7F

            if length == 126:
                length = struct.unpack(">H", read_exactly(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", read_exactly(8))[0]

            mask = read_exactly(4) if masked else None
            payload = read_exactly(length)

            if mask:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

            if opcode == OPCODE_PING:
                self._send_frame(OPCODE_PONG, payload, sock)
            elif opcode == OPCODE_CLOSE:
                self._send_frame(OPCODE_CLOSE, payload[:2], sock)
                return struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 0
            elif opcode == OPCODE_TEXT:
                fragments = payload
            elif opcode == OPCODE_CONTINUATION and fragments is not None:
                fragments += payload

            if fin and opcode in (OPCODE_TEXT, OPCODE_CONTINUATION) and fragments is not None:
                text, fragments = fragments, None
                self._dispatch(generation, self._on_text, text.decode("utf-8", errors="replace"))
