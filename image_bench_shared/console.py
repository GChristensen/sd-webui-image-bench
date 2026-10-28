"""
The terminal output of the host process for the console drawer of the Image Bench window (/image-bench/console).
sys.stdout and sys.stderr are wrapped once (install_stream_tee): everything is written through to the real streams and
kept in a buffer of the last lines, which the connected sockets receive with what is written later (serve).
The host keeps the socket and passes callables to send and receive, so this works with FastAPI and aiohttp alike.
Nothing here may print: the output would be fed back into the buffer.
"""
import asyncio
import json
import logging
import re
import sys
import threading
from collections import deque

# Finished lines kept for the sockets that connect later
MAX_LINES = 2000

# Seconds to collect output before it is sent, so that progress bars do not send a message per update
BATCH_DELAY = 0.1

# Characters of one message at most: the end of a longer batch is sent
MAX_MESSAGE = 256 * 1024


# Escape sequences, line feeds, carriage returns and text, as consoleText.js of the popup reads them
TOKEN = re.compile(r"\x1b\[([0-9;?]*)([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][\x20-\x7e]|\x1b[\x20-\x7e]"
                   r"|\n|\r|[^\x1b\n\r]+")

# An escape sequence cut off by the end of a write, completed by the next one
INCOMPLETE = re.compile(r"\x1b(?:\[[0-9;?]*|\][^\x07\x1b]*|[()])?$")


class Subscriber:
    """A connected socket: the output written since its last message, and the event that wakes its sender"""

    def __init__(self, loop):
        self.loop = loop
        self.event = asyncio.Event()
        self.pending = []
        self.size = 0

    def add(self, text):
        self.pending.append(text)
        self.size += len(text)

        # A socket that does not keep up: only the end can be sent anyway
        if self.size > 2 * MAX_MESSAGE:
            self.pending = ["".join(self.pending)[-MAX_MESSAGE:]]
            self.size = len(self.pending[0])

        try:
            self.loop.call_soon_threadsafe(self.event.set)
        except RuntimeError:
            # The loop is closed
            pass


class ConsoleBuffer:
    """The last lines of the output and the sockets receiving it; written from any thread"""

    def __init__(self):
        self._lock = threading.Lock()
        # The lines as a terminal shows them, the redraws of progress bars applied
        self._lines = deque([""], maxlen=MAX_LINES)
        # The line of the cursor: the last one, unless a cursor move went up (tqdm bars of a position other than 0
        # are drawn on the following lines and the cursor goes back up)
        self._row = 0
        # A carriage return was written: the next text replaces the line
        self._returned = False
        # An escape sequence cut off by the end of a write
        self._carry = ""
        self._subscribers = set()
        self._feeding = threading.local()

    def feed(self, text):
        if not text or getattr(self._feeding, "active", False):
            return

        self._feeding.active = True

        try:
            with self._lock:
                self._append(text)

                for subscriber in self._subscribers:
                    subscriber.add(text)
        except Exception:
            pass
        finally:
            self._feeding.active = False

    def _append(self, text):
        """Follow the output as consoleText.js does, so that the backlog shows what an open drawer shows"""
        text = self._carry + text
        self._carry = ""
        incomplete = INCOMPLETE.search(text)

        if incomplete:
            self._carry = incomplete.group(0)
            text = text[:incomplete.start()]

        for match in TOKEN.finditer(text):
            token = match.group(0)

            if token == "\n":
                if self._row < len(self._lines) - 1:
                    # Onto a line written before: the next text replaces it
                    self._row += 1
                    self._returned = True
                else:
                    self._returned = False
                    self._lines.append("")
                    self._row = len(self._lines) - 1
            elif token == "\r":
                self._returned = True
            # Text and colors are kept, other escape sequences dropped
            elif token[0] != "\x1b" or match.group(2) == "m":
                if self._returned:
                    self._lines[self._row] = ""
                    self._returned = False

                self._lines[self._row] += token
            # Erase the whole line
            elif match.group(2) == "K" and match.group(1) == "2":
                self._lines[self._row] = ""
            elif match.group(2) in ("A", "B"):
                rows = int(match.group(1)) if match.group(1).isdigit() else 1
                row = self._row - rows if match.group(2) == "A" else self._row + rows
                self._row = min(max(row, 0), len(self._lines) - 1)

    def subscribe(self, loop):
        """Add a socket, returning it with the output so far, so that nothing is lost or sent twice"""
        subscriber = Subscriber(loop)

        with self._lock:
            backlog = "\n".join(self._lines)
            above = len(self._lines) - 1 - self._row

            # The cursor of a bar drawn above others, for the cursor moves of its next redraw
            if above:
                backlog += f"\x1b[{above}A"
            self._subscribers.add(subscriber)

        return subscriber, backlog

    def unsubscribe(self, subscriber):
        with self._lock:
            self._subscribers.discard(subscriber)

    def take(self, subscriber):
        """The output of a socket waiting to be sent (on the loop of the socket)"""
        with self._lock:
            text = "".join(subscriber.pending)
            subscriber.pending = []
            subscriber.size = 0
            subscriber.event.clear()

        return text[-MAX_MESSAGE:]


BUFFER = ConsoleBuffer()


class TeeStream:
    """A text stream writing through to the original one and into the buffer; anything else is the original's"""

    _image_bench_console = True

    def __init__(self, stream, buffer):
        self.original = stream
        self._buffer = buffer

    def write(self, data):
        result = self.original.write(data)

        if isinstance(data, str):
            self._buffer.feed(data)

        return result

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def __getattr__(self, name):
        # isatty, encoding, fileno, buffer, flush...: rich and tqdm behave as with the real terminal
        return getattr(self.original, name)


def _is_console(stream):
    """Whether a stream writes to the terminal: an earlier wrapper of it may be any object (ComfyUI's LogInterceptor,
    the logger of ComfyUI-Manager), so it is told by its file descriptor"""
    if getattr(stream, "_image_bench_console", False):
        return False

    try:
        return stream.fileno() in (1, 2)
    except Exception:
        return False


def _redirect_handlers(replacements, buffer):
    """
    Point the logging handlers writing to the terminal to tees: they keep the stream of their creation, which may be
    a stream replaced since (ComfyUI's root handler writes to its LogInterceptor, which ComfyUI-Manager wrapped)
    """
    loggers = [logging.getLogger()]
    loggers += [logger for logger in logging.Logger.manager.loggerDict.values() if isinstance(logger, logging.Logger)]

    for logger in loggers:
        for handler in list(logger.handlers):
            # WebUI's TqdmLoggingHandler writes through a handler of its own
            for target in (handler, getattr(handler, "fallback_handler", None)):
                if (not isinstance(target, logging.StreamHandler) or isinstance(target, logging.FileHandler)
                        or not _is_console(target.stream)):
                    continue

                # One tee per stream, so that handlers sharing a stream share it
                tee = replacements.get(id(target.stream))

                if tee is None:
                    tee = replacements[id(target.stream)] = TeeStream(target.stream, buffer)

                try:
                    target.setStream(tee)
                except Exception:
                    pass


def install_stream_tee(buffer=BUFFER):
    """Wrap sys.stdout and sys.stderr (once: a reload of the extension finds them wrapped)"""
    replacements = {}

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)

        if stream is None or getattr(stream, "_image_bench_console", False):
            continue

        tee = TeeStream(stream, buffer)
        replacements[id(stream)] = tee
        setattr(sys, name, tee)

    if replacements:
        _redirect_handlers(replacements, buffer)


def install_comfy_console(buffer=BUFFER):
    """
    ComfyUI keeps the output since its start (app.logger): it begins the buffer, which the wrapped streams continue
    """
    if not getattr(sys.stdout, "_image_bench_console", False):
        try:
            from app import logger as comfy_logger

            buffer.feed("".join(entry["m"] for entry in comfy_logger.get_logs() or ()))
        except Exception:
            pass

    install_stream_tee(buffer)


async def _wait_closed(receive_text):
    try:
        while True:
            await receive_text()
    except Exception:
        pass


async def serve(send_text, receive_text, buffer=BUFFER):
    """
    Send the output to a connected socket until it closes: the output so far, then what is written in batches
    :param send_text: async callable sending a text message
    :param receive_text: async callable receiving a message, raising when the socket is closed
    """
    subscriber, backlog = buffer.subscribe(asyncio.get_running_loop())
    closed = asyncio.ensure_future(_wait_closed(receive_text))

    try:
        await send_text(json.dumps({"type": "backlog", "text": backlog[-MAX_MESSAGE:]}))

        while not closed.done():
            woken = asyncio.ensure_future(subscriber.event.wait())
            await asyncio.wait({woken, closed}, return_when=asyncio.FIRST_COMPLETED)

            if closed.done():
                woken.cancel()
                break

            await asyncio.sleep(BATCH_DELAY)
            text = buffer.take(subscriber)

            if text:
                await send_text(json.dumps({"type": "append", "text": text}))
    except Exception:
        pass
    finally:
        buffer.unsubscribe(subscriber)
        closed.cancel()
