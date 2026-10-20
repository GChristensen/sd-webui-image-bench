"""
The backend side of the host restart (host_supervisor.py): starts the sidecar, or registers this backend process with
the running one, tells the Image Bench window how to reach it (/image-bench/host_restart) and passes it a restart
asked while the host answers (the window may not reach the sidecar: another computer, a certificate not accepted yet).
The restart is enabled by store/host_restart.json only, which is never written here.
Nothing here may raise into the host or print (the output is fed into the console drawer).
"""
import json
import os
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from . import host_process
from .host_supervisor import CONFIG_FILE, STATE_FILE, TOKEN_HEADER, build_command, read_config

SUPERVISOR_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host_supervisor.py")

# The port of the sidecar unless the config file sets one: that of the host + this
PORT_OFFSET = 100

# Seconds to wait for a started sidecar to write its state file
START_TIMEOUT = 10
# Seconds to wait for a replaced sidecar to release its port
REPLACE_TIMEOUT = 5
REQUEST_TIMEOUT = 3

_lock = threading.Lock()
# The sidecar this backend is registered with: (pid, port, token)
_registered = None


def host_server(port, network=False, certfile=None, keyfile=None):
    """
    How the host serves: its port, whether it listens on the network (--listen) and its TLS files, which the sidecar
    takes over, so that the browser reaching the host reaches the sidecar as well
    """
    return {"port": int(port or 0), "network": bool(network), "certfile": certfile or None,
            "keyfile": keyfile or None}


def _sidecar_settings(config, server):
    """Address, port and TLS files of the sidecar: those of the host unless the config file sets them"""
    listen = config.get("listen")
    network = listen if isinstance(listen, bool) else server["network"]
    tls = bool(server["certfile"] and server["keyfile"])

    try:
        port = int(config.get("port") or 0)
    except (TypeError, ValueError):
        port = 0

    return {"bind": "0.0.0.0" if network else "127.0.0.1",
            "port": port or (server["port"] + PORT_OFFSET if server["port"] else 0),
            "scheme": "https" if tls else "http",
            "certfile": server["certfile"] if tls else None,
            "keyfile": server["keyfile"] if tls else None}


def _read_state(store_dir):
    try:
        with open(os.path.join(store_dir, STATE_FILE), encoding="utf-8") as file:
            state = json.load(file)

        return state if isinstance(state, dict) and state.get("port") and state.get("token") else None
    except (OSError, ValueError):
        return None


def _matches(state, settings):
    return (state.get("bind") == settings["bind"] and state.get("scheme") == settings["scheme"]
            and (not settings["port"] or state.get("port") == settings["port"]))


def _request(state, method, path, body=None):
    scheme = state.get("scheme", "http")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{scheme}://127.0.0.1:{state['port']}{path}", data=data, method=method,
                                     headers={TOKEN_HEADER: state["token"], "Content-Type": "application/json"})

    # Not through a proxy of the environment; the certificate is that of the host's name, not of 127.0.0.1
    handlers = [urllib.request.ProxyHandler({})]

    if scheme == "https":
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))

    with urllib.request.build_opener(*handlers).open(request, timeout=REQUEST_TIMEOUT) as response:
        return json.load(response)


def _spawn(store_dir, server, settings):
    """Start the sidecar detached, so that it survives the kill of this process and its console"""
    args = [sys.executable, SUPERVISOR_SCRIPT, "--store", store_dir, "--host-pid", str(os.getpid()),
            "--host-port", str(server["port"]), "--bind", settings["bind"], "--port", str(settings["port"])]
    created = host_process.create_time(os.getpid())

    if created is not None:
        args += ["--host-create-time", repr(created)]

    if settings["certfile"]:
        args += ["--certfile", settings["certfile"], "--keyfile", settings["keyfile"]]

    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)

    if host_process.IS_WINDOWS:
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)

        try:
            subprocess.Popen(args, creationflags=flags | host_process.CREATE_BREAKAWAY_FROM_JOB, **options)
        except OSError:
            subprocess.Popen(args, creationflags=flags, **options)
    else:
        subprocess.Popen(args, start_new_session=True, **options)

    deadline = time.monotonic() + START_TIMEOUT

    while time.monotonic() < deadline:
        state = _read_state(store_dir)

        if state and state.get("pid") != (_registered or (None,))[0] and host_process.alive(state.get("pid")):
            return state

        time.sleep(0.2)

    return None


def _replace(state):
    """
    End a sidecar started with other settings (an earlier config or version), freeing its port; only its process:
    the host it started after a restart is its child
    """
    host_process.kill(state["pid"])
    deadline = time.monotonic() + REPLACE_TIMEOUT

    while state.get("port") and host_process.port_in_use(state["port"]) and time.monotonic() < deadline:
        time.sleep(0.2)


def ensure(store_dir, server):
    """
    Have a sidecar watching this backend if the restart is configured: register with the running one, or start one
    :returns: its state {pid, bind, port, scheme, token}, or None
    """
    global _registered

    store_dir = os.path.normpath(store_dir)
    config = read_config(store_dir)

    if build_command(config)[0] is None:
        return None

    settings = _sidecar_settings(config, server)

    with _lock:
        try:
            state = _read_state(store_dir)

            if state and host_process.alive(state.get("pid")):
                if not _matches(state, settings):
                    _replace(state)
                else:
                    key = (state["pid"], state["port"], state["token"])

                    if key == _registered:
                        return state

                    try:
                        _request(state, "POST", "/register", {"pid": os.getpid(), "port": server["port"],
                                                              "createTime": host_process.create_time(os.getpid())})
                        _registered = key
                        return state
                    except Exception:
                        pass

            state = _spawn(store_dir, server, settings)

            if state:
                _registered = (state["pid"], state["port"], state["token"])

            return state
        except Exception:
            return None


def ensure_in_background(store_dir, server):
    """ensure() without delaying the start of the host"""
    threading.Thread(target=ensure, args=(store_dir, server), daemon=True).start()


def info(store_dir, server):
    """
    The restart settings for the Image Bench window: the configured command (or the detected start script to put
    into the config file) and the address and token of the sidecar
    """
    config = read_config(store_dir)
    args, cwd = build_command(config)
    state = ensure(store_dir, server) if args is not None else None
    detected = None

    try:
        # The sidecar runs the script after a restart: the walk up stops below it
        stop = {state["pid"]} if state else set()
        detected = host_process.detect_start_command(host_process.find_root(os.getpid(), stop))
    except Exception:
        pass

    return {
        "configured": args is not None,
        "command": config.get("command") if args is not None else None,
        "cwd": cwd,
        "configPath": os.path.join(store_dir, CONFIG_FILE),
        "detected": detected,
        "port": state["port"] if state else None,
        "scheme": state.get("scheme", "http") if state else None,
        "network": state.get("bind") != "127.0.0.1" if state else None,
        "token": state["token"] if state else None,
        "running": state is not None,
    }


def restart(store_dir, server):
    """
    Ask the sidecar to restart the host, for a window that may not reach it itself
    :returns: (HTTP status, body)
    """
    state = ensure(store_dir, server)

    if state is None:
        return 409, {"error": "The restart helper is not running"}

    try:
        return 200, _request(state, "POST", "/restart")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 502, {"error": f"The restart helper does not answer: {e}"}
