"""
The sidecar that restarts the host (SD WebUI / ComfyUI) when it hangs or has died, from the Image Bench window.
A hung host cannot restart itself, so this runs as a separate process, started detached by the backend
(host_restart.ensure) and outliving it: it kills the host's process tree (host_process.py) and runs the start script
named in store/host_restart.json, a file edited by hand only (the setting would let anyone reaching a host started with
--listen run any command). The new backend registers itself with the running sidecar.

Run as a script with the interpreter of the host. It listens where the host does (on the network with --listen, so
that a browser on another computer reaches it while the host hangs) on a fixed port, by default that of the host + 100,
with the host's TLS certificate if it has one (an https page may not request http). Address and a random token are
written to store/host_supervisor.json, which the backend passes to the Image Bench window (/image-bench/host_restart);
every request but the certificate page (/) needs the token in the X-Image-Bench-Token header.
It exits when the host is gone and no window has asked for its status for a while.
"""
import argparse
import json
import logging
import os
import secrets
import shlex
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler

try:
    from . import host_process
except ImportError:
    # Run as a script: an embedded Python (ComfyUI portable) does not put the script's folder on the path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import host_process

CONFIG_FILE = "host_restart.json"
STATE_FILE = "host_supervisor.json"
LOG_FILE = "host_supervisor.log"
# Output of a host started on POSIX, which has no console window to open
HOST_LOG_FILE = "host.log"

TOKEN_HEADER = "X-Image-Bench-Token"

# Seconds without a host and without a status request after which the sidecar exits
IDLE_EXIT = 120
# Seconds to wait for the host's port to be released after the kill
PORT_TIMEOUT = 15
# Seconds a started host has to register before the restart is reported failed
REGISTER_TIMEOUT = 300
CHECK_INTERVAL = 2
# Seconds before the kill, so that the reply to a restart asked through the host's backend reaches the window
KILL_DELAY = 0.5
# Seconds a connection may take (a client that does not finish its TLS handshake holds only its own thread)
CONNECTION_TIMEOUT = 15

# Shown to a browser opening the helper to accept its (self-signed) certificate
CERTIFICATE_PAGE = b"""<!doctype html><meta charset="utf-8"><title>Image Bench restart helper</title>
<body style="font: 14px sans-serif; padding: 2em">The browser accepts the restart helper of Image Bench now.
You can close this tab.</body>"""

log = logging.getLogger("image_bench_supervisor")


def read_config(store_dir):
    """The restart settings of store/host_restart.json, {} if there are none"""
    try:
        with open(os.path.join(store_dir, CONFIG_FILE), encoding="utf-8") as file:
            config = json.load(file)

        return config if isinstance(config, dict) else {}
    except (OSError, ValueError):
        return {}


def build_command(config):
    """
    The arguments and working folder of the start command of the host:
    a .bat/.cmd is run by cmd, a .ps1 by PowerShell, a .sh by bash, another file directly; a string that is not a
    file is a command line, a list the arguments
    :returns: (args, cwd), or (None, None) if no command is set
    """
    command = config.get("command")
    cwd = config.get("cwd") or None
    script = None

    if isinstance(command, list) and command:
        args = [str(arg) for arg in command]
        script = args[0]
    elif isinstance(command, str) and command.strip():
        command = os.path.expandvars(os.path.expanduser(command.strip()))
        extension = os.path.splitext(command)[1].lower()

        if os.path.isfile(command):
            script = command

        if extension in (".bat", ".cmd"):
            args = ["cmd", "/c", command]
        elif extension == ".ps1":
            args = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", command]
        elif extension == ".sh":
            args = ["bash", command]
        elif script:
            args = [command]
        else:
            args = command if host_process.IS_WINDOWS else shlex.split(command)
    else:
        return None, None

    if not cwd and script and os.path.isabs(script):
        cwd = os.path.dirname(script)

    return args, cwd


def launch(args, cwd, env, store_dir):
    """Start the host detached from this process: in a new console window on Windows"""
    if host_process.IS_WINDOWS:
        flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            return subprocess.Popen(args, cwd=cwd, env=env, creationflags=flags | host_process.CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            # The job of this process does not allow breaking away
            return subprocess.Popen(args, cwd=cwd, env=env, creationflags=flags)

    output = open(os.path.join(store_dir, HOST_LOG_FILE), "ab")

    try:
        return subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=output,
                                stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        output.close()


class Supervisor:
    def __init__(self, store_dir, host_pid, host_created, host_port):
        self.store_dir = store_dir
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.state = "running"
        self.error = None
        self.restart_started = 0
        self.last_request = time.monotonic()
        # The environment of the program that started the host (a terminal, explorer), for the restarted host
        self.launch_env = None
        self.host_pid = self.host_created = self.host_port = None
        self.root = self.root_created = None
        self.register(host_pid, host_created, host_port)

    def register(self, pid, created, port):
        """The (new) backend process: its root is found while it runs, since a dead process has no parent"""
        procs = host_process.snapshot()
        root = host_process.find_root(pid, {os.getpid()}, procs)

        with self.lock:
            self.host_pid, self.host_created, self.host_port = pid, created, port
            self.root = root
            self.root_created = procs[root].create_time if root in procs else None
            self.state = "running"
            self.error = None
            self.last_request = time.monotonic()

        if self.launch_env is None:
            self.launch_env = self.starter_environment(root, procs)

        log.info("Host registered: pid %s, root %s (%s), port %s", pid, root,
                 procs[root].name if root in procs else "?", port)

    @staticmethod
    def starter_environment(root, procs):
        """The environment of the parent of the host's root: the start script sets its own variables again"""
        parent = procs.get(root) and procs.get(procs[root].ppid)

        if parent is None or parent.pid == os.getpid() or not host_process.psutil:
            return None

        try:
            return host_process.psutil.Process(parent.pid).environ() or None
        except Exception:
            return None

    def status(self):
        with self.lock:
            self.last_request = time.monotonic()
            pid, created, state, error = self.host_pid, self.host_created, self.state, self.error

        args, _ = build_command(read_config(self.store_dir))
        host_alive = host_process.alive(pid, created)

        return {"state": state, "error": error, "hostAlive": host_alive,
                "memory": host_process.memory(pid) if host_alive else None,
                "configured": args is not None}

    def restart(self):
        """Start a restart; None, or the reason it is refused"""
        args, cwd = build_command(read_config(self.store_dir))

        if args is None:
            return f"No start command is set in store/{CONFIG_FILE}"

        with self.lock:
            if self.state == "restarting":
                return "The host is restarting"

            self.state = "restarting"
            self.error = None
            self.restart_started = time.monotonic()
            self.last_request = time.monotonic()

        threading.Thread(target=self._restart, args=(args, cwd), daemon=True).start()
        return None

    def _restart(self, args, cwd):
        try:
            time.sleep(KILL_DELAY)
            self.kill_host()
            self.wait_port()
            process = launch(args, cwd, self.launch_env, self.store_dir)
            log.info("Started %s in %s: pid %s", args, cwd, process.pid)
        except Exception as e:
            log.exception("Restart failed")

            with self.lock:
                self.state = "failed"
                self.error = str(e)

    def kill_host(self):
        procs = host_process.snapshot()
        own = os.getpid()

        with self.lock:
            pid, created, root, root_created = self.host_pid, self.host_created, self.root, self.root_created

        roots = []

        if host_process.alive(pid, created, procs):
            roots.append(host_process.find_root(pid, {own}, procs))

        # The shell of the start script outlives a crashed server (waiting at `pause`)
        if root not in roots and host_process.alive(root, root_created, procs):
            roots.append(root)

        exclude = set(host_process.own_chain({pid}))

        for target in roots:
            name = procs[target].name if target in procs else "?"
            remaining = host_process.kill_tree(target, exclude)
            log.info("Killed the tree of %s (%s)%s", target, name, f", still running: {remaining}" if remaining else "")

    def wait_port(self):
        deadline = time.monotonic() + PORT_TIMEOUT

        while self.host_port and host_process.port_in_use(self.host_port) and time.monotonic() < deadline:
            time.sleep(0.5)

    def should_exit(self):
        """Exit when the host is gone, nothing restarts it and no window asked for the status for a while"""
        with self.lock:
            if self.state == "restarting":
                if time.monotonic() - self.restart_started > REGISTER_TIMEOUT:
                    self.state = "failed"
                    self.error = "The host did not start"
                return False

            pid, created, idle = self.host_pid, self.host_created, time.monotonic() - self.last_request

        if host_process.alive(pid, created):
            return False

        with self.lock:
            if self.state == "running":
                self.state = "exited"

        return idle > IDLE_EXIT


def make_handler(supervisor):
    class Handler(BaseHTTPRequestHandler):
        timeout = CONNECTION_TIMEOUT

        def log_message(self, format, *args):
            log.debug(format, *args)

        def cors(self):
            origin = self.headers.get("Origin")

            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def reply(self, status, body=None):
            data = json.dumps(body if body is not None else {}).encode()
            self.send_response(status)
            self.cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            if secrets.compare_digest(self.headers.get(TOKEN_HEADER, ""), supervisor.token):
                return True

            self.reply(403, {"error": "Forbidden"})
            return False

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)

            try:
                return json.loads(self.rfile.read(length) or b"{}") if length else {}
            except ValueError:
                return {}

        def do_OPTIONS(self):
            self.send_response(204)
            self.cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", f"{TOKEN_HEADER}, Content-Type")
            # Chrome asks before a page of a LAN address reaches a loopback one
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")
            self.end_headers()

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(CERTIFICATE_PAGE)))
                self.end_headers()
                self.wfile.write(CERTIFICATE_PAGE)
                return

            if not self.authorized():
                return

            if self.path == "/status":
                self.reply(200, supervisor.status())
            else:
                self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if not self.authorized():
                return

            if self.path == "/restart":
                error = supervisor.restart()
                self.reply(409 if error else 200, {"error": error} if error else {"state": "restarting"})
            elif self.path == "/register":
                body = self.body()

                try:
                    supervisor.register(int(body["pid"]), body.get("createTime"), int(body.get("port") or 0))
                    self.reply(200, {"state": "running"})
                except (KeyError, TypeError, ValueError):
                    self.reply(400, {"error": "Bad request"})
            else:
                self.reply(404, {"error": "Not found"})

    return Handler


def write_state(path, state):
    temp = f"{path}.{os.getpid()}.tmp"

    with open(temp, "w", encoding="utf-8") as file:
        json.dump(state, file)

    os.replace(temp, path)


def remove_state(path):
    """Remove the state file if it still names this process (a newer sidecar may have replaced it)"""
    try:
        with open(path, encoding="utf-8") as file:
            owned = json.load(file).get("pid") == os.getpid()

        # Closed first: Windows does not remove an open file
        if owned:
            os.remove(path)
    except (OSError, ValueError):
        pass


def open_console(title):
    """The console window a detached sidecar may still get on Windows (a venv's python.exe is a launcher stub, whose
    child, the real interpreter, gets a console of its own), titled; a stream writing into it, or None without one.
    The standard streams are those of the backend (devnull), so the console is opened by name"""
    if not host_process.IS_WINDOWS:
        return None

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32

        if not kernel32.GetConsoleWindow():
            return None

        kernel32.SetConsoleTitleW(title)
        return open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--host-pid", type=int, required=True)
    parser.add_argument("--host-create-time", type=float, default=None)
    parser.add_argument("--host-port", type=int, default=0)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--certfile")
    parser.add_argument("--keyfile")
    options = parser.parse_args()

    handler = RotatingFileHandler(os.path.join(options.store, LOG_FILE), maxBytes=256 * 1024, backupCount=1,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    console = open_console(f"Image Bench restart helper (host pid {options.host_pid}, port {options.host_port})")

    if console:
        console.write("Image Bench restart helper\n\n"
                      "This sidecar watches the SD WebUI / ComfyUI host and restarts it from the Image Bench window\n"
                      "when it hangs or has died. Closing this window ends it: a hung host then cannot be restarted\n"
                      "until the backend, while it answers, starts the helper again. The helper exits by itself when\n"
                      "the host is gone and no Image Bench window asks for it.\n\n")
        console_handler = logging.StreamHandler(console)
        console_handler.setFormatter(handler.formatter)
        log.addHandler(console_handler)

    supervisor = Supervisor(options.store, options.host_pid, options.host_create_time, options.host_port)

    try:
        server = ThreadingHTTPServer((options.bind, options.port), make_handler(supervisor))

        if options.certfile and options.keyfile:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(options.certfile, options.keyfile)
            # The handshake is made by the thread of the connection, not by the accepting one
            server.socket = context.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
    except Exception:
        log.exception("Unable to listen on %s:%s", options.bind, options.port)
        return

    server.daemon_threads = True
    scheme = "https" if options.certfile and options.keyfile else "http"
    state_path = os.path.join(options.store, STATE_FILE)
    write_state(state_path, {"pid": os.getpid(), "bind": options.bind, "port": server.server_address[1],
                             "scheme": scheme, "token": supervisor.token})
    log.info("Supervisor started: pid %s, %s://%s:%s, psutil %s", os.getpid(), scheme, options.bind,
             server.server_address[1], "yes" if host_process.psutil else "no")

    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        while not supervisor.should_exit():
            time.sleep(CHECK_INTERVAL)
    finally:
        remove_state(state_path)
        server.shutdown()
        log.info("Supervisor exited")


if __name__ == "__main__":
    # A detached process may have no streams; nothing is printed anyway
    if sys.stdout is None:
        sys.stdout = sys.stderr = open(os.devnull, "w")

    main()
