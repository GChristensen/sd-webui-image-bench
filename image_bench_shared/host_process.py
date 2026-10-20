"""
The operating system processes of the host (SD WebUI / ComfyUI) for its restart (host_supervisor.py): the tree started
by the user's start script, found by walking up from the server process, and killed as a whole.
psutil is used when it is installed (ComfyUI requires it); without it, the processes are listed by the system tools,
which give no command lines, creation times or memory sizes.
Imported by the backend (a package) and by the sidecar script (a plain module), so only the standard library is
imported here. Nothing here may print: the backend's output is fed into the console drawer.
"""
import os
import re
import signal
import socket
import subprocess
import time

try:
    import psutil
except ImportError:
    psutil = None

IS_WINDOWS = os.name == "nt"

# Parents that belong to the start of the host: interpreters, launchers and the shells running a start script.
# The walk up stops at anything else (explorer, a terminal, an IDE) and keeps it alive
PYTHON_NAME = re.compile(r"^python[\d.]*w?(\.exe)?$", re.IGNORECASE)
LAUNCHER_NAMES = {"cmd.exe", "powershell.exe", "pwsh.exe", "pwsh", "sh", "bash", "zsh", "dash", "uv", "uv.exe"}

KILL_TIMEOUT = 10

# Process creation flags of Windows: break away from a job the host runs in (some terminals and launchers kill the
# processes of their job when it closes)
CREATE_BREAKAWAY_FROM_JOB = 0x01000000


class Proc:
    def __init__(self, pid, ppid, name, create_time=None):
        self.pid = pid
        self.ppid = ppid
        self.name = name or ""
        self.create_time = create_time


def _no_window():
    return subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0


def _windows_snapshot():
    """pid -> Proc from the Toolhelp snapshot (names and parents only)"""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_wchar * 260)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    procs = {}

    if snapshot in (None, wintypes.HANDLE(-1).value):
        return procs

    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))

        while more:
            procs[entry.th32ProcessID] = Proc(entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile)
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    return procs


def _posix_snapshot():
    procs = {}
    output = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,comm="], capture_output=True, text=True).stdout

    for line in output.splitlines():
        parts = line.split(None, 2)

        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            procs[int(parts[0])] = Proc(int(parts[0]), int(parts[1]), os.path.basename(parts[2]))

    return procs


def snapshot():
    """All processes: pid -> Proc"""
    if psutil:
        procs = {}

        for process in psutil.process_iter(["pid", "ppid", "name", "create_time"]):
            info = process.info
            procs[info["pid"]] = Proc(info["pid"], info["ppid"], info["name"], info["create_time"])

        return procs

    try:
        return _windows_snapshot() if IS_WINDOWS else _posix_snapshot()
    except Exception:
        return {}


def create_time(pid):
    """The creation time of a process (None if unknown), which tells it from a later one with a reused pid"""
    if psutil:
        try:
            return psutil.Process(pid).create_time()
        except Exception:
            return None

    return None


def alive(pid, created=None, procs=None):
    """Whether the process runs, and is the one created at `created` if both times are known"""
    if not pid:
        return False

    proc = (procs if procs is not None else snapshot()).get(pid)

    if proc is None:
        return False

    return created is None or proc.create_time is None or abs(proc.create_time - created) < 1


def _parent(proc, procs):
    """The parent of a process, unless it is gone (an orphan's ppid may name a later process with a reused pid)"""
    parent = procs.get(proc.ppid)

    if parent is None or parent.pid == proc.pid:
        return None

    if parent.create_time is not None and proc.create_time is not None and parent.create_time > proc.create_time:
        return None

    return parent


def ancestors(pid, procs=None):
    """The pids above a process, nearest first"""
    procs = procs if procs is not None else snapshot()
    result = []
    proc = procs.get(pid)

    while proc is not None and len(result) < 64:
        proc = _parent(proc, procs)

        if proc is not None:
            result.append(proc.pid)

    return result


def is_launcher(name):
    name = name.lower()
    return bool(PYTHON_NAME.match(name)) or name in LAUNCHER_NAMES


def find_root(pid, stop_pids=(), procs=None):
    """
    The topmost process of the host's start: the server process, its interpreter launcher (a venv python.exe starts
    the base interpreter) and the shell running the start script (which may wait at `pause`), up to a process that
    is none of these or one of `stop_pids` (the sidecar, which runs the script after a restart)
    """
    procs = procs if procs is not None else snapshot()
    proc = procs.get(pid)

    if proc is None:
        return pid

    while True:
        parent = _parent(proc, procs)

        if parent is None or parent.pid in stop_pids or not is_launcher(parent.name):
            return proc.pid

        proc = parent


def descendants(root, procs=None):
    """The pids below a process"""
    procs = procs if procs is not None else snapshot()
    children = {}

    for proc in procs.values():
        if _parent(proc, procs) is not None:
            children.setdefault(proc.ppid, []).append(proc.pid)

    result = []
    pending = list(children.get(root, ()))

    while pending:
        pid = pending.pop()

        if pid not in result:
            result.append(pid)
            pending.extend(children.get(pid, ()))

    return result


def kill(pid):
    try:
        if psutil:
            psutil.Process(pid).kill()
        elif IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, creationflags=_no_window())
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def kill_tree(root, exclude=()):
    """
    Kill a process and all below it but the `exclude` pids, waiting until they are gone
    :returns: the pids still running after the timeout
    """
    procs = snapshot()

    if root not in procs:
        return []

    pids = [pid for pid in [root, *descendants(root, procs)] if pid not in exclude]
    created = {pid: procs[pid].create_time for pid in pids}

    for pid in pids:
        kill(pid)

    deadline = time.monotonic() + KILL_TIMEOUT

    while True:
        procs = snapshot()
        remaining = [pid for pid in pids if alive(pid, created[pid], procs)]

        if not remaining or time.monotonic() > deadline:
            return remaining

        time.sleep(0.25)


def memory(pid):
    """The resident memory of a process in bytes (None if unknown)"""
    if psutil:
        try:
            return psutil.Process(pid).memory_info().rss
        except Exception:
            return None

    return None


def _cmdline(pid):
    try:
        process = psutil.Process(pid)
        return process.cmdline(), process.cwd()
    except Exception:
        return None, None


SCRIPT_EXTENSIONS = (".bat", ".cmd", ".ps1", ".sh")
# A quoted script path within an argument (cmd.exe keeps `/c ""D:\x y\run.bat" "` as one)
QUOTED_SCRIPT = re.compile(r'"([^"]+?\.(?:bat|cmd|ps1|sh))"', re.IGNORECASE)


def _find_script(args):
    for arg in args:
        candidate = arg.strip().strip('"').strip()

        if candidate.lower().endswith(SCRIPT_EXTENSIONS):
            return candidate

        match = QUOTED_SCRIPT.search(arg)

        if match:
            return match.group(1)

    return None


def detect_start_command(root):
    """
    The start script of the host as its root process ran it (a suggestion for host_restart.json), or the command line
    of the interpreter started without a script; None if unknown
    """
    if not psutil:
        return None

    args, cwd = _cmdline(root)

    if not args:
        return None

    script = _find_script(args[1:])

    if script:
        if cwd and not os.path.isabs(script):
            script = os.path.join(cwd, script)

        return os.path.normpath(script)

    return subprocess.list2cmdline(args) if IS_WINDOWS else " ".join(args)


def port_in_use(port):
    """Whether a server listens on the local port"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def own_chain(stop_pids=()):
    """
    This process and the interpreter launchers above it (a venv python.exe stub, started by the backend) up to one of
    `stop_pids` (the backend): kept alive when the host's tree is killed
    """
    procs = snapshot()
    pid = os.getpid()
    chain = [pid]

    for parent in ancestors(pid, procs):
        if parent in stop_pids or not PYTHON_NAME.match(procs[parent].name):
            break

        chain.append(parent)

    return chain
