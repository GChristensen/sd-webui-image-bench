"""
Projects of the Library tab.

The projects are a directory tree under the project root (the projectRoot setting of the extension config, a local
or UNC path as the server sees it). A directory that contains ib_project/ is a project; the tree is not searched
below it. ib_project/ holds:

    project.json        name, tags, notes, final image, parameter snapshot, tray counts
    final.<ext>         copy of the image considered final
    trays/<kind>/       the trays in the layout of the tray download, so that any of them, zipped, can be imported into a tray
    controlnet/         control images of the parameter snapshot
    workflow.json       ComfyUI workflow of the parameter snapshot
    prompt_history.json the prompt history of the Generate tab and its variants (not part of the unsaved changes)
    thumbs/             thumbnails of the image files of the project directory
    file_info.json      generation parameters of the image files of the project directory (by name, size and time)

The trays of the store directory are the workspace, which is saved into a project and restored from it.
store/current_project.json points to the current project, with the hashes of the tray store files at the last save
or open, which tell the unsaved changes. store/project_index.json caches the summaries of the projects
(revalidated by the modification time of project.json), so that network shares are not read through on every visit.

All paths of the requests are relative to the root ('/'-separated) and must stay inside it.
This module is framework-agnostic: the hosts call dispatch() off the event loop.
"""

import ctypes
import filecmp
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from PIL import Image

from . import media
from .controlnet_inputs import HASH, image_hashes, input_dir, input_path
from .persist import PROMPT_HISTORY_FILE, read_json_file, replace_file
from .tray import TRAY_FILES, unique_file_path

PROJECT_DIR = "ib_project"
PROJECT_FILE = "project.json"
WORKFLOW_FILE = "workflow.json"
CONTROLNET_DIR = "controlnet"
TRAYS_DIR = "trays"
THUMBS_DIR = "thumbs"
FILE_INFO_FILE = "file_info.json"
INDEX_FILE = "project_index.json"
CURRENT_FILE = "current_project.json"

# Trays saved into a project, in this order
TRAY_KINDS = ("image_tray", "concept_tray", "compare")

# Marking of the final choice in the trays; a project saved without a final image takes the image marked with it
FINAL_MARKING = "\U0001F3C1"

# Name of the tray content in the saved trays, as in the tray download, which any tray imports
ARCHIVE_TRAY_FILE = TRAY_FILES["image_tray"]

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif", ".psd", ".tif", ".tiff"}
# The files of a project: images, videos and audio
FILE_EXTENSIONS = IMAGE_EXTENSIONS | media.MEDIA_EXTENSIONS
# Images whose generation parameters are read (infotext, or the prompt of ComfyUI)
INFO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
# Served as they are; other images are converted to PNG
BROWSER_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"} | media.MEDIA_EXTENSIONS
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif", ".bmp": "image/bmp", ".avif": "image/avif", **media.MEDIA_TYPES}

# Directories not shown in the tree
SKIPPED_DIRS = {PROJECT_DIR.lower(), "$recycle.bin", "system volume information", "__pycache__", "node_modules"}

MAX_TREE_DEPTH = 16
# Subdirectories of a project searched for image files
MAX_FILE_DEPTH = 3
MAX_FILES = 2000
THUMB_SIZE = 256

INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class ProjectError(Exception):
    """An error reported to the popup, with the HTTP status of the response"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class FileResult:
    """A file response: a path on disk or content in memory"""

    def __init__(self, media_type: str, path: Optional[str] = None, content: Optional[bytes] = None):
        self.media_type = media_type
        self.path = path
        self.content = content


# ---------- Paths ----------

def get_root(config: Dict[str, Any]) -> str:
    root = (config or {}).get("projectRoot") or ""
    return os.path.normpath(root.strip()) if root.strip() else ""


def split_path(path: Optional[str]) -> List[str]:
    """Components of a relative path; '..' is refused"""
    parts = [part for part in (path or "").replace("\\", "/").split("/") if part and part != "."]

    if any(part == ".." for part in parts):
        raise ProjectError("Invalid path")

    return parts


def join_path(parts: List[str]) -> str:
    return "/".join(parts)


def resolve(root: str, path: Optional[str]) -> str:
    """Absolute path of a path relative to the root, which must stay inside it"""
    if not root:
        raise ProjectError("The project root is not set (Settings › Library).", 409)

    absolute = os.path.normpath(os.path.join(root, *split_path(path)))

    if os.path.normcase(os.path.commonpath([root, absolute])) != os.path.normcase(root):
        raise ProjectError("Invalid path")

    return absolute


def relative(root: str, absolute: str) -> str:
    rel = os.path.relpath(absolute, root)
    return "" if rel == "." else rel.replace(os.sep, "/")


def check_name(name: Optional[str]) -> str:
    """A valid file name for a folder or project"""
    name = (name or "").strip().rstrip(".")

    if not name or INVALID_NAME.search(name) or name in (".", "..") or name.lower() == PROJECT_DIR:
        raise ProjectError(f"Invalid name: {name!r}")

    return name


def is_project_dir(path: str) -> bool:
    return os.path.isdir(os.path.join(path, PROJECT_DIR))


def project_paths(root: str, path: str):
    """(project directory, its ib_project directory); the project must exist"""
    directory = resolve(root, path)
    data_dir = os.path.join(directory, PROJECT_DIR)

    if not os.path.isdir(data_dir):
        raise ProjectError("The project does not exist.", 404)

    return directory, data_dir


def host_name(platform: str) -> str:
    """Host of the popup ("webui" or "comfy") by the platform of the tray functions ("webui" or "comfyui")"""
    return "comfy" if platform == "comfyui" else "webui"


# ---------- JSON files ----------

def read_json(path: str, default=None):
    if not os.path.isfile(path):
        return default

    data = read_json_file(path)
    return default if data is None else data


def write_json(path: str, data) -> None:
    """Write a JSON file through a temporary file, so that it is never left half-written"""
    replace_file(path, json.dumps(data, ensure_ascii=False, indent=1))


def read_project_file(data_dir: str) -> Dict[str, Any]:
    data = read_json(os.path.join(data_dir, PROJECT_FILE), {})
    return data if isinstance(data, dict) else {}


# ---------- Root ----------

def check_root(root: str) -> Dict[str, Any]:
    """Whether a root directory exists and is writable, and the number of projects under it"""
    if not root:
        return {"exists": False, "writable": False, "projects": 0, "error": "No path"}

    if not os.path.isdir(root):
        return {"exists": False, "writable": False, "projects": 0, "error": "The directory does not exist"}

    # os.access() is unreliable on network shares
    try:
        with tempfile.TemporaryFile(dir=root):
            pass
        writable = True
    except OSError:
        writable = False

    return {"exists": True, "writable": writable, "projects": count_projects(scan_dir(root, root, 0, {}, set()))}


def count_projects(nodes) -> int:
    return sum(1 if node["type"] == "project" else count_projects(node["children"]) for node in nodes)


# ---------- Tree ----------

def summarize(data: Dict[str, Any]) -> Dict[str, Any]:
    """Summary of a project kept in the index: what the tree shows and searches"""
    params = (data.get("parameters") or {}).get("params") or {}

    return {
        # Name the project was saved under; the folder may have been renamed or copied outside Image Bench
        "name": data.get("name"),
        "host": data.get("host"),
        "tags": data.get("tags") or [],
        "prompt": params.get("prompt") or "",
        "negativePrompt": params.get("negativePrompt") or "",
        "savedAt": data.get("savedAt"),
        "final": data.get("final")
    }


def scan_dir(root: str, directory: str, depth: int, index: Dict[str, Any], seen: set) -> List[Dict[str, Any]]:
    """Folders and projects in a directory, sorted by name"""
    try:
        entries = sorted((entry for entry in os.scandir(directory)
                          if entry.is_dir() and not entry.name.startswith(".")
                          and entry.name.lower() not in SKIPPED_DIRS),
                         key=lambda entry: entry.name.lower())
    except OSError:
        return []

    nodes = []

    for entry in entries:
        rel = relative(root, entry.path)

        if is_project_dir(entry.path):
            seen.add(rel)
            nodes.append({"type": "project", "name": entry.name, "path": rel,
                          "project": project_summary(entry.path, rel, index)})
        else:
            children = scan_dir(root, entry.path, depth + 1, index, seen) if depth < MAX_TREE_DEPTH else []
            nodes.append({"type": "folder", "name": entry.name, "path": rel, "children": children})

    return nodes


def project_summary(directory: str, rel: str, index: Dict[str, Any]) -> Dict[str, Any]:
    """Summary from the index, read again if project.json was changed since"""
    project_file = os.path.join(directory, PROJECT_DIR, PROJECT_FILE)

    try:
        mtime = os.stat(project_file).st_mtime
    except OSError:
        mtime = 0

    cached = index.get(rel)

    if cached and cached.get("mtime") == mtime:
        return cached["summary"]

    summary = summarize(read_project_file(os.path.join(directory, PROJECT_DIR)))
    index[rel] = {"mtime": mtime, "summary": summary}
    return summary


def get_tree(root: str, store_dir: str) -> Dict[str, Any]:
    if not root:
        return {"root": "", "exists": False, "nodes": []}

    if not os.path.isdir(root):
        return {"root": root, "exists": False, "nodes": []}

    index_path = os.path.join(store_dir, INDEX_FILE)
    stored = read_json(index_path, {})
    index = dict(stored.get("projects") or {}) if stored.get("root") == root else {}
    seen = set()

    nodes = scan_dir(root, root, 0, index, seen)

    # Projects removed or moved outside of Image Bench are dropped from the index
    index = {rel: entry for rel, entry in index.items() if rel in seen}

    if stored.get("root") != root or index != stored.get("projects"):
        try:
            write_json(index_path, {"root": root, "projects": index})
        except OSError as e:
            print(f"[Image Bench] Unable to write the project index: {e}")

    return {"root": root, "exists": True, "nodes": nodes, "trash": can_trash(root)}


# ---------- Project ----------

def list_files(directory: str) -> List[Dict[str, Any]]:
    """Image, video and audio files of a project directory and its subdirectories, except ib_project and nested projects"""
    files = []

    def walk(path: str, prefix: str, depth: int):
        try:
            entries = list(os.scandir(path))
        except OSError:
            return

        for entry in entries:
            if len(files) >= MAX_FILES:
                return

            if entry.is_dir():
                if (depth < MAX_FILE_DEPTH and entry.name.lower() not in SKIPPED_DIRS
                        and not entry.name.startswith(".") and not is_project_dir(entry.path)):
                    walk(entry.path, prefix + entry.name + "/", depth + 1)
            elif os.path.splitext(entry.name)[1].lower() in FILE_EXTENSIONS:
                try:
                    stat = entry.stat()
                except OSError:
                    continue

                files.append({"name": prefix + entry.name, "size": stat.st_size, "modified": stat.st_mtime})

    walk(directory, "", 0)
    files.sort(key=lambda file: file["modified"], reverse=True)
    return files


def add_file_parameters(directory: str, data_dir: str, files: List[Dict[str, Any]]) -> None:
    """
    Add the generation parameters of the image files ("parameters", left out if they have none), read once and kept
    in ib_project/file_info.json by name, size and modification time
    """
    from .pnginfo import image_info

    cache_path = os.path.join(data_dir, FILE_INFO_FILE)
    cached = read_json(cache_path, {})
    cached = cached if isinstance(cached, dict) else {}
    cache = {}

    for file in files:
        ext = os.path.splitext(file["name"])[1].lower()

        if ext not in INFO_EXTENSIONS and ext not in media.VIDEO_EXTENSIONS:
            continue

        key = f"{file['size']}|{file['modified']}"
        entry = cached.get(file["name"])

        if not entry or entry.get("key") != key:
            file_path = os.path.join(directory, *split_path(file["name"]))

            try:
                if ext in media.VIDEO_EXTENSIONS:
                    parameters = media.media_info(file_path).get("parameters") or {}
                else:
                    with open(file_path, "rb") as source:
                        parameters = image_info(source.read()).get("parameters") or {}
            except OSError:
                continue

            entry = {"key": key, "parameters": parameters}

        cache[file["name"]] = entry

        if entry["parameters"]:
            file["parameters"] = entry["parameters"]

    if cache != cached:
        try:
            write_json(cache_path, cache)
        except OSError:
            pass  # A read-only project is read again the next time


def get_project(root: str, path: str) -> Dict[str, Any]:
    directory, data_dir = project_paths(root, path)
    data = read_project_file(data_dir)
    files = list_files(directory)
    add_file_parameters(directory, data_dir, files)

    return {
        "path": relative(root, directory),
        "name": os.path.basename(directory),
        "data": data,
        "files": files,
        "trays": {kind: os.path.isfile(tray_file(tray_dir(data_dir, kind))) for kind in TRAY_KINDS}
    }


def project_file_path(root: str, path: str, name: str) -> str:
    """A file of a project directory (also in ib_project), by its name relative to the directory"""
    directory, _ = project_paths(root, path)
    file_path = os.path.normpath(os.path.join(directory, *split_path(name)))

    if os.path.normcase(os.path.commonpath([directory, file_path])) != os.path.normcase(directory) \
            or not os.path.isfile(file_path):
        raise ProjectError("File not found", 404)

    return file_path


def get_file(root: str, path: str, name: str, thumb: bool = False) -> FileResult:
    file_path = project_file_path(root, path, name)
    ext = os.path.splitext(file_path)[1].lower()

    if thumb:
        return get_thumbnail(root, path, name, file_path)

    # The workflow of the parameter snapshot
    if ext == ".json":
        return FileResult("application/json", path=file_path)

    if ext in BROWSER_EXTENSIONS:
        return FileResult(MEDIA_TYPES[ext], path=file_path)

    try:
        with Image.open(file_path) as image:
            buffer = io.BytesIO()
            to_rgb(image).save(buffer, format="PNG", compress_level=1)
    except Exception as e:
        raise ProjectError(f"Unable to read the image: {e}", 415)

    return FileResult("image/png", content=buffer.getvalue())


def to_rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        return image.convert("RGBA")

    return image.convert("RGB")


def get_thumbnail(root: str, path: str, name: str, file_path: str) -> FileResult:
    """JPEG thumbnail, cached in ib_project/thumbs by the name, size and modification time of the file"""
    _, data_dir = project_paths(root, path)
    stat = os.stat(file_path)
    return cached_thumbnail(data_dir, f"{name}|{stat.st_size}|{stat.st_mtime_ns}", lambda: file_path,
                            video=media.media_kind(file_path) == "video")


def cached_thumbnail(data_dir: str, key: str, open_source, video: bool = False) -> FileResult:
    """
    JPEG thumbnail cached in ib_project/thumbs under the hash of a key that changes with the image
    open_source() gives the image to open: a path or a file object; of a video (a path), a frame is taken.
    Audio files have no thumbnail (the popup shows a placeholder)
    """
    thumb_path = os.path.join(data_dir, THUMBS_DIR, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".jpg")

    if os.path.isfile(thumb_path):
        return FileResult("image/jpeg", path=thumb_path)

    def open_image() -> Image.Image:
        if video:
            return media.video_frame(open_source())

        with Image.open(open_source()) as image:
            image.draft("RGB", (THUMB_SIZE * 2, THUMB_SIZE * 2))
            return to_rgb(image)

    try:
        content = media.thumbnail_jpeg(open_image, THUMB_SIZE)
    except Exception as e:
        raise ProjectError(f"Unable to read the image: {e}", 415)

    try:
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

        with open(thumb_path, "wb") as file:
            file.write(content)
    except OSError:
        pass  # A read-only project is shown without the cache

    return FileResult("image/jpeg", content=content)


# ---------- File system ----------

def add_file(root: str, path: str, filename: Optional[str], content: Optional[bytes]) -> Dict[str, Any]:
    """Save an image, video or audio file into a project directory under its name (another name if it is taken)"""
    directory, _ = project_paths(root, path)
    name = os.path.basename((filename or "").replace("\\", "/")) or "image.png"

    if content is None:
        raise ProjectError("No file")

    if os.path.splitext(name)[1].lower() not in FILE_EXTENSIONS:
        raise ProjectError("Not an image file.", 415)

    target = unique_file_path(directory, check_name(name))

    with open(target, "wb") as file:
        file.write(content)

    return {"name": os.path.basename(target), "project": get_project(root, path)}


# Documents saved by the editor plugins (Keep › File / Final): the file names and formats
EDITOR_SAVES = {"file": (".psd",), "final": (".psd", ".png", ".jpg")}
JPEG_QUALITY = 95


def editor_save_stem(directory: str, save: str) -> str:
    """
    The name of the next document saved by an editor plugin: <project folder name>-NNN (File) or final-NNN (Final),
    numbered after the highest number of that name in the folder, in any format
    """
    prefix = os.path.basename(os.path.normpath(directory)) if save == "file" else "final"
    pattern = re.compile(re.escape(prefix.lower()) + r"-(\d+)\.[^.]+")
    numbers = [int(match.group(1)) for match in map(pattern.fullmatch, (name.lower() for name in os.listdir(directory)))
               if match]
    return f"{prefix}-{max(numbers, default=0) + 1:03d}"


def save_editor_document(root: str, store_dir: str, save: str, psd: bytes,
                         image: Optional[Image.Image] = None) -> Dict[str, Any]:
    """
    Save a document of an editor plugin into the folder of the current project: save="file" as <project>-NNN.psd,
    save="final" as final-NNN.psd, .png and .jpg (the image is the merged document), whose PNG becomes
    the project's final image

    Returns:
        {"project": name of the project, "files": names of the files written}
    """
    if save not in EDITOR_SAVES:
        raise ProjectError(f"Unknown save: {save}")

    if not psd.startswith(b"8BPS"):
        raise ProjectError("The document is not a PSD file.", 415)

    if save == "final" and image is None:
        raise ProjectError("The merged image of the document is missing.")

    path = read_current(store_dir).get("path")

    if path is None:
        raise ProjectError("No project is open in Image Bench.", 409)

    directory, _ = project_paths(root, path)
    stem = editor_save_stem(directory, save)
    files = []

    for ext in EDITOR_SAVES[save]:
        target = os.path.join(directory, stem + ext)

        if ext == ".psd":
            with open(target, "wb") as file:
                file.write(psd)
        elif ext == ".png":
            image.save(target, format="PNG")
        else:
            rgb = to_rgb(image)

            # JPEG has no transparency: flattened onto white
            if rgb.mode == "RGBA":
                background = Image.new("RGB", rgb.size, (255, 255, 255))
                background.paste(rgb, mask=rgb.getchannel("A"))
                rgb = background

            rgb.save(target, format="JPEG", quality=JPEG_QUALITY, subsampling=0)

        files.append(stem + ext)

    if save == "final":
        set_final(root, path, name=stem + ".png")

    return {"project": os.path.basename(directory), "files": files}


def create_folder(root: str, parent: str, name: str) -> Dict[str, Any]:
    directory = os.path.join(resolve(root, parent), check_name(name))

    if os.path.exists(directory):
        raise ProjectError(f"'{name}' already exists.", 409)

    os.makedirs(directory)
    return {"path": relative(root, directory)}


def create_project(root: str, parent: str, name: str, platform: str) -> Dict[str, Any]:
    parent_dir = resolve(root, parent)

    if parent and is_project_dir(parent_dir):
        raise ProjectError("A project cannot be created inside another project.")

    directory = os.path.join(parent_dir, check_name(name))

    if os.path.exists(directory):
        raise ProjectError(f"'{name}' already exists.", 409)

    os.makedirs(os.path.join(directory, PROJECT_DIR))
    write_json(os.path.join(directory, PROJECT_DIR, PROJECT_FILE), {
        "version": 1,
        "name": os.path.basename(directory),
        "host": host_name(platform),
        "created": time.time(),
        "tags": [],
        "notes": "",
        "final": None
    })

    return {"path": relative(root, directory)}


def check_movable(root: str, path: str) -> str:
    source = resolve(root, path)

    if os.path.normcase(source) == os.path.normcase(root):
        raise ProjectError("The project root cannot be changed here.")

    if not os.path.isdir(source):
        raise ProjectError("The folder does not exist.", 404)

    return source


def rename(root: str, store_dir: str, path: str, name: str) -> Dict[str, Any]:
    source = check_movable(root, path)
    target = os.path.join(os.path.dirname(source), check_name(name))

    # A change of case only is a rename on case-insensitive file systems
    if os.path.exists(target) and os.path.normcase(target) != os.path.normcase(source):
        raise ProjectError(f"'{name}' already exists.", 409)

    os.rename(source, target)
    new_path = relative(root, target)
    update_current_path(store_dir, path, new_path)

    # A project renamed here keeps its name in step with the folder
    if is_project_dir(target):
        data_dir = os.path.join(target, PROJECT_DIR)
        data = read_project_file(data_dir)
        data["name"] = os.path.basename(target)
        write_json(os.path.join(data_dir, PROJECT_FILE), data)

    return {"path": new_path}


def move(root: str, store_dir: str, path: str, to: str) -> Dict[str, Any]:
    source = check_movable(root, path)
    parent = resolve(root, to)

    if not os.path.isdir(parent):
        raise ProjectError("The target folder does not exist.", 404)

    if is_project_dir(parent):
        raise ProjectError("A folder or project cannot be moved into a project.")

    source_key = os.path.normcase(source)
    parent_key = os.path.normcase(parent)

    if parent_key == source_key or parent_key.startswith(source_key + os.sep):
        raise ProjectError("A folder cannot be moved into itself.")

    target = os.path.join(parent, os.path.basename(source))

    if os.path.normcase(target) == source_key:
        return {"path": path}

    if os.path.exists(target):
        raise ProjectError(f"'{os.path.basename(source)}' already exists in the target folder.", 409)

    shutil.move(source, target)
    new_path = relative(root, target)
    update_current_path(store_dir, path, new_path)
    return {"path": new_path}


def can_trash(path: str) -> bool:
    """Whether deleted files go to the Recycle Bin (not on network shares)"""
    if path.startswith("\\\\") or path.startswith("//"):
        return False

    try:
        import send2trash  # noqa: F401
        return True
    except ImportError:
        return os.name == "nt"


def trash(path: str) -> None:
    try:
        from send2trash import send2trash
        send2trash(path)
        return
    except ImportError:
        pass

    if os.name != "nt":
        raise ProjectError("The Recycle Bin is not available.", 500)

    # SHFileOperationW with FOF_ALLOWUNDO moves to the Recycle Bin
    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p),
                    ("pTo", ctypes.c_wchar_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", ctypes.c_wchar_p)]

    fo_delete, fof_silent, fof_noconfirmation, fof_allowundo, fof_noerrorui = 3, 0x4, 0x10, 0x40, 0x400
    operation = SHFILEOPSTRUCTW(wFunc=fo_delete, pFrom=os.path.abspath(path) + "\0",
                                fFlags=fof_silent | fof_noconfirmation | fof_allowundo | fof_noerrorui)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))

    if result or operation.fAnyOperationsAborted:
        raise ProjectError(f"Unable to move to the Recycle Bin (error {result}).", 500)


def delete(root: str, store_dir: str, path: str) -> Dict[str, Any]:
    target = check_movable(root, path)

    if can_trash(target):
        trash(target)
    else:
        shutil.rmtree(target)

    update_current_path(store_dir, path, None)
    return {}


def delete_file(root: str, path: str, name: str) -> Dict[str, Any]:
    """Delete an image file of a project directory (into the Recycle Bin where it is available); not in ib_project"""
    if split_path(name)[:1] and split_path(name)[0].lower() == PROJECT_DIR:
        raise ProjectError("Files of ib_project cannot be deleted.")

    file_path = project_file_path(root, path, name)

    if os.path.splitext(file_path)[1].lower() not in FILE_EXTENSIONS:
        raise ProjectError("Not an image file.", 415)

    if can_trash(file_path):
        trash(file_path)
    else:
        os.unlink(file_path)

    return get_project(root, path)


def write_file_infotext(root: str, path: str, name: str, infotext: str) -> Dict[str, Any]:
    """Write the infotext into a PNG file of a project directory (Paste infotext); not in ib_project"""
    from .pnginfo import write_infotext

    if split_path(name)[:1] and split_path(name)[0].lower() == PROJECT_DIR:
        raise ProjectError("Files of ib_project cannot be changed.")

    file_path = project_file_path(root, path, name)

    try:
        info = write_infotext(file_path, infotext)
    except ValueError as e:
        raise ProjectError(str(e), 415)

    return {**info, "project": get_project(root, path)}


def reveal(root: str, path: str) -> Dict[str, Any]:
    """
    Show a folder or project in Windows Explorer of the server computer (the popup offers it when it is local and
    runs on Windows). Other platforms would have to launch their file manager, which the registry scan flags; they
    copy the path
    """
    if os.name != "nt":
        raise ProjectError("Showing folders is supported only on Windows.", 501)

    target = resolve(root, path)

    if not os.path.isdir(target):
        raise ProjectError("The folder does not exist.", 404)

    os.startfile(target)

    return {}


# ---------- Current project ----------

def read_current(store_dir: str) -> Dict[str, Any]:
    data = read_json(os.path.join(store_dir, CURRENT_FILE), {})
    return data if isinstance(data, dict) else {}


def write_current(store_dir: str, data: Optional[Dict[str, Any]]) -> None:
    path = os.path.join(store_dir, CURRENT_FILE)

    if data:
        write_json(path, data)
    elif os.path.exists(path):
        os.unlink(path)


def update_current_path(store_dir: str, old: str, new: Optional[str]) -> None:
    """Follow a renamed, moved or deleted folder of the current project"""
    current = read_current(store_dir)
    current_path = current.get("path")

    if current_path is None:
        return

    old_parts, current_parts = split_path(old), split_path(current_path)

    if current_parts[:len(old_parts)] != old_parts:
        return

    if new is None:
        write_current(store_dir, None)
    else:
        current["path"] = join_path(split_path(new) + current_parts[len(old_parts):])
        write_current(store_dir, current)


def read_tray_store(store_dir: str, kind: str):
    """(content of the store file of a tray, its hash, its image count); the count is None if it is unreadable"""
    path = os.path.join(store_dir, TRAY_FILES[kind])

    try:
        with open(path, "rb") as file:
            content = file.read()
    except OSError:
        content = b""

    try:
        count = len(json.loads(content).get("images") or []) if content.strip() else 0
    except (ValueError, AttributeError):
        count = None

    return content, hashlib.sha1(content).hexdigest() if count else "", count


def read_tray_store_checked(store_dir: str, kind: str):
    """read_tray_store() for a save or merge, which must not take an unreadable store file for an empty tray"""
    content, tray_hash, count = read_tray_store(store_dir, kind)

    if count is None:
        raise ProjectError(f"The store file of the {kind.replace('_', ' ')} ({TRAY_FILES[kind]}) cannot be read; "
                           "nothing was changed.", 500)

    return content, tray_hash, count


def get_current(root: str, store_dir: str) -> Dict[str, Any]:
    """The current project with the tray changes since the last save or open"""
    current = read_current(store_dir)
    path = current.get("path")

    if path is None:
        return {"path": None}

    try:
        directory, data_dir = project_paths(root, path)
    except ProjectError:
        return {"path": path, "name": split_path(path)[-1] if split_path(path) else "", "exists": False}

    data = read_project_file(data_dir)
    saved = data.get("trays") or {}
    hashes = current.get("trays") or {}
    trays = {}

    for kind in TRAY_KINDS:
        _, tray_hash, count = read_tray_store(store_dir, kind)
        trays[kind] = {"workspace": count or 0, "saved": (saved.get(kind) or {}).get("count", 0),
                       "changed": tray_hash != hashes.get(kind, "")}

    return {"path": relative(root, directory), "name": os.path.basename(directory), "exists": True,
            "savedAt": data.get("savedAt"), "trays": trays, "changed": any(tray["changed"] for tray in trays.values())}


def set_current(root: str, store_dir: str, path: Optional[str]) -> Dict[str, Any]:
    """Make a project current as the workspace is (its trays count as saved), or forget the current project"""
    if path is None:
        write_current(store_dir, None)
        return {"path": None}

    project_paths(root, path)
    write_current(store_dir, {"path": path,
                              "trays": {kind: read_tray_store(store_dir, kind)[1] for kind in TRAY_KINDS}})
    return get_current(root, store_dir)


# ---------- Metadata ----------

def update_project(root: str, path: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    """
    Change the tags or notes of a project, saved at once (they are not part of the workspace);
    "name": true takes the folder name as the name of the project
    """
    directory, data_dir = project_paths(root, path)
    data = read_project_file(data_dir)

    if "tags" in changes:
        tags = []

        for tag in changes["tags"] or []:
            tag = re.sub(r"\s+", " ", str(tag)).strip().lstrip("#")

            if tag and tag.lower() not in (t.lower() for t in tags):
                tags.append(tag)

        data["tags"] = tags

    if "notes" in changes:
        data["notes"] = str(changes["notes"] or "")

    if changes.get("name"):
        data["name"] = os.path.basename(directory)

    write_json(os.path.join(data_dir, PROJECT_FILE), data)
    return get_project(root, path)


def set_final(root: str, path: str, name: Optional[str] = None, filename: Optional[str] = None,
              content: Optional[bytes] = None, kind: Optional[str] = None,
              member: Optional[str] = None) -> Dict[str, Any]:
    """
    Copy an image into the project as its final image: a file of the project directory (name), an image of a saved
    tray (kind and member of its folder) or uploaded content; none of them clears it
    """
    _, data_dir = project_paths(root, path)
    data = read_project_file(data_dir)

    if name:
        source = project_file_path(root, path, name)
        write_final(data_dir, data, os.path.splitext(source)[1], name, path=source)
    elif kind:
        source = read_tray_member(data_dir, kind, member)
        write_final(data_dir, data, os.path.splitext(source)[1], f"{kind}:{os.path.basename(source)}", path=source)
    elif content is not None:
        write_final(data_dir, data, os.path.splitext(filename or "")[1], filename, content=content)
    else:
        write_final(data_dir, data, None, None)

    write_json(os.path.join(data_dir, PROJECT_FILE), data)
    return get_project(root, path)


def write_final(data_dir: str, data: Dict[str, Any], ext: Optional[str], source_label: Optional[str],
                path: Optional[str] = None, content: Optional[bytes] = None) -> None:
    """
    Write the final image into ib_project as final.<ext> from a file or content, and record it in the project data;
    no extension removes it
    """
    ext = ext.lower() if ext else None

    if ext is not None and ext not in FILE_EXTENSIONS:
        raise ProjectError("Not an image file.", 415)

    for old in os.listdir(data_dir):
        old_path = os.path.join(data_dir, old)

        # The source may be the final image itself
        if os.path.splitext(old)[0] == "final" and os.path.isfile(old_path) \
                and (path is None or os.path.normcase(old_path) != os.path.normcase(path)):
            os.unlink(old_path)

    if ext is None:
        data["final"] = None
        data.pop("finalSource", None)
        return

    target = os.path.join(data_dir, "final" + ext)

    if path is not None:
        if os.path.normcase(target) != os.path.normcase(path):
            shutil.copy2(path, target)
    else:
        with open(target, "wb") as file:
            file.write(content)

    data["final"] = f"{PROJECT_DIR}/final{ext}"
    data["finalSource"] = source_label


# ---------- Saved trays ----------

def tray_dir(data_dir: str, kind: str) -> str:
    """Folder of a saved tray, in the layout of the tray download (see tray.download_image_tray)"""
    if kind not in TRAY_KINDS:
        raise ProjectError(f"Unknown tray: {kind}")

    return os.path.join(data_dir, TRAYS_DIR, kind)


def tray_file(directory: str) -> str:
    return os.path.join(directory, ARCHIVE_TRAY_FILE)


def read_saved_tray(directory: str) -> Dict[str, Any]:
    try:
        return read_json_file(tray_file(directory)) or {}
    except (OSError, ValueError):
        return {}


def tray_member_path(directory: str, member: Optional[str]) -> Optional[str]:
    """Path of an image of a saved tray by its member name (images/<name>), None if it is invalid or missing"""
    parts = (member or "").replace("\\", "/").split("/")

    if len(parts) != 2 or parts[0] != "images" or parts[1] in ("", ".", ".."):
        return None

    path = os.path.join(directory, "images", parts[1])
    return path if os.path.isfile(path) else None


def get_tray(root: str, path: str, kind: str) -> Dict[str, Any]:
    """
    Images of a saved tray of a project, in the tray order:
    {member, name, marking, comment, prompt, parameters, img2img, generationId, controlnet}
    (images whose files were missing when the tray was saved are left out)
    """
    _, data_dir = project_paths(root, path)
    directory = tray_dir(data_dir, kind)

    if not os.path.isfile(tray_file(directory)):
        return {"kind": kind, "images": [], "version": None}

    images = []

    for image in read_saved_tray(directory).get("images") or []:
        member = image.get("imagePath")

        if tray_member_path(directory, member):
            images.append({
                "member": member,
                "name": os.path.basename(member),
                "marking": image.get("marking"),
                "comment": image.get("comment"),
                "prompt": (image.get("parameters") or {}).get("prompt") or "",
                "parameters": image.get("parameters") or {},
                "img2img": image.get("img2img"),
                "generationId": image.get("generationId"),
                "controlnet": image.get("controlnet")
            })

    return {"kind": kind, "images": images, "version": os.stat(tray_file(directory)).st_mtime_ns}


def read_tray_member(data_dir: str, kind: str, member: Optional[str]) -> str:
    """Path of an image of a saved tray"""
    image_path = tray_member_path(tray_dir(data_dir, kind), member)

    if image_path is None:
        raise ProjectError("Image not found", 404)

    return image_path


def get_tray_image(root: str, path: str, kind: str, member: str, thumb: bool = False) -> FileResult:
    """An image of a saved tray, or its thumbnail (cached by the image modification time)"""
    _, data_dir = project_paths(root, path)
    image_path = read_tray_member(data_dir, kind, member)

    if thumb:
        version = os.stat(image_path).st_mtime_ns
        return cached_thumbnail(data_dir, f"{kind}|{member}|{version}", lambda: image_path,
                                video=media.media_kind(image_path) == "video")

    ext = os.path.splitext(member)[1].lower()

    if ext in BROWSER_EXTENSIONS:
        return FileResult(MEDIA_TYPES[ext], path=image_path)

    try:
        with Image.open(image_path) as image:
            buffer = io.BytesIO()
            to_rgb(image).save(buffer, format="PNG", compress_level=1)
    except Exception as e:
        raise ProjectError(f"Unable to read the image: {e}", 415)

    return FileResult("image/png", content=buffer.getvalue())


def marked_final(store_dir: str) -> Optional[Dict[str, Any]]:
    """The image marked as the final choice (🏁) in the image tray, else in the concept tray, of the workspace"""
    for kind in ("image_tray", "concept_tray"):
        content, _, count = read_tray_store(store_dir, kind)

        if not count:
            continue

        for image in json.loads(content).get("images") or []:
            if image.get("marking") == FINAL_MARKING and os.path.isfile(image.get("imagePath") or ""):
                return {"kind": kind, "path": image["imagePath"]}

    return None


def same_file(path: str, other: str) -> bool:
    """Files of the same size and modification time (copy2 keeps it), as an unchanged copy is"""
    try:
        a, b = os.stat(path), os.stat(other)
    except OSError:
        return False

    return a.st_size == b.st_size and int(a.st_mtime) == int(b.st_mtime)


def write_tray_dir(store_content: bytes, directory: str, image_bench_dir: str) -> int:
    """
    Write the tray content of a store file and its images into a tray folder in the layout of the tray download
    (see tray.download_image_tray): the tray file, images/ and controlnet/. The folder is built beside the old one
    and swapped in; the unchanged files of the old one are moved over instead of copied again.
    An image whose file is missing keeps its entry as it is. Returns the number of the images of the tray
    """
    tray_data = json.loads(store_content)
    images = []
    names = set()
    controlnet_inputs = set()
    temp = directory + ".tmp"
    old = directory + ".old"

    for leftover in (temp, old):
        shutil.rmtree(leftover, ignore_errors=True)

    os.makedirs(os.path.join(temp, "images"))

    def place(source: str, member: str) -> None:
        target = os.path.join(temp, *member.split("/"))
        existing = os.path.join(directory, *member.split("/"))

        if same_file(existing, source):
            os.replace(existing, target)
        else:
            shutil.copy2(source, target)

    for image in tray_data.get("images") or []:
        image_path = image.get("imagePath")

        if image.get("separator") or not image_path or not os.path.isfile(image_path):
            images.append(image)
            continue

        name = os.path.basename(image_path)
        stem, ext = os.path.splitext(name)
        counter = 1

        while name.lower() in names:
            name = f"{stem}_{counter:03d}{ext}"
            counter += 1

        names.add(name.lower())
        member = "images/" + name
        place(image_path, member)
        images.append({**image, "imagePath": member})
        controlnet_inputs |= image_hashes(image)

    # The stored ControlNet inputs of the images, as controlnet/<hash>.png (missing ones skipped)
    for value in sorted(controlnet_inputs):
        try:
            source = input_path(image_bench_dir, value)
        except FileNotFoundError:
            continue

        os.makedirs(os.path.join(temp, CONTROLNET_DIR), exist_ok=True)
        place(source, f"{CONTROLNET_DIR}/{value}.png")

    with open(tray_file(temp), "w", encoding="utf-8") as file:
        json.dump({**tray_data, "images": images}, file)

    if os.path.isdir(directory):
        os.replace(directory, old)

    os.replace(temp, directory)
    shutil.rmtree(old, ignore_errors=True)
    return len(images)


def extract_tray_dir(directory: str, image_bench_dir: str, kind: str, platform: str) -> List[Dict[str, Any]]:
    """
    Copy the images of a saved tray into the tray directory (image-bench/<kind>/), where they are kept by the
    tray. A file of the same name and content is reused, another one gets a new name.
    Returns the images of the tray with their new paths
    """
    if not os.path.isfile(tray_file(directory)):
        raise ProjectError(f"{os.path.basename(directory)} holds no tray.", 422)

    target_dir = os.path.join(image_bench_dir, kind)
    os.makedirs(target_dir, exist_ok=True)
    images = []

    for image in read_saved_tray(directory).get("images") or []:
        member = image.get("imagePath")
        source = tray_member_path(directory, member)

        # An image whose file was missing when it was saved keeps its entry
        if source is None:
            if member and not member.startswith("images/"):
                images.append(image)

            continue

        name = os.path.basename(source)
        target = os.path.join(target_dir, name)

        if not (os.path.isfile(target) and filecmp.cmp(target, source, shallow=False)):
            target = unique_file_path(target_dir, name)
            shutil.copy2(source, target)

        name = os.path.basename(target)
        image = {key: value for key, value in image.items() if key != "selected"}
        image["imagePath"] = target
        image["imageUrl"] = (f"/view?filename={quote(name)}&type=output&subfolder=image-bench/{kind}"
                             if platform == "comfyui" else f"/file={target.replace(os.sep, '/')}")
        image["_tray_processed"] = True
        images.append(image)

    # ControlNet inputs of the images, stored by hash
    controlnet_dir = os.path.join(directory, CONTROLNET_DIR)

    for name in os.listdir(controlnet_dir) if os.path.isdir(controlnet_dir) else []:
        value = name[:-4] if name.endswith(".png") else ""
        target = os.path.join(input_dir(image_bench_dir), name) if HASH.match(value) else None

        if target and not os.path.exists(target):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(os.path.join(controlnet_dir, name), target)

    return images


def image_key(image: Dict[str, Any]) -> str:
    """Identity of a tray image across workspaces: its original path, else its file name"""
    return os.path.normcase(image.get("sourcePath") or os.path.basename(image.get("imagePath") or ""))


# ---------- Save and open ----------

def read_prompt_history(store_dir: str) -> Dict[str, Any]:
    history = read_json(os.path.join(store_dir, PROMPT_HISTORY_FILE))
    return history if isinstance(history, dict) else {"version": 2}


def save_project(root: str, store_dir: str, image_bench_dir: str, platform: str, path: str,
                 snapshot: Dict[str, Any], files: Dict[str, bytes]) -> Dict[str, Any]:
    """
    Save the workspace into a project and make it current: the trays (only the folders of the changed ones are
    written again) and the parameter snapshot with its ControlNet images and ComfyUI workflow
    """
    directory, data_dir = project_paths(root, path)
    data = read_project_file(data_dir)
    saved_trays = data.get("trays") or {}
    trays = {}
    hashes = {}

    # All store files are read before anything is changed
    stores = {kind: read_tray_store_checked(store_dir, kind) for kind in TRAY_KINDS}
    os.makedirs(os.path.join(data_dir, TRAYS_DIR), exist_ok=True)

    for kind in TRAY_KINDS:
        content, tray_hash, count = stores[kind]
        directory_path = tray_dir(data_dir, kind)
        hashes[kind] = tray_hash

        if not count:
            shutil.rmtree(directory_path, ignore_errors=True)
            trays[kind] = {"count": 0, "hash": ""}
        elif (saved_trays.get(kind) or {}).get("hash") == tray_hash and os.path.isfile(tray_file(directory_path)):
            trays[kind] = saved_trays[kind]
        else:
            trays[kind] = {"count": write_tray_dir(content, directory_path, image_bench_dir), "hash": tray_hash}

    parameters = dict(snapshot.get("parameters") or {})
    controlnet_dir = os.path.join(data_dir, CONTROLNET_DIR)
    shutil.rmtree(controlnet_dir, ignore_errors=True)

    if files:
        os.makedirs(controlnet_dir)

        for name, content in files.items():
            with open(os.path.join(controlnet_dir, check_name(os.path.basename(name))), "wb") as file:
                file.write(content)

    workflow_path = os.path.join(data_dir, WORKFLOW_FILE)
    workflow = snapshot.get("workflow")

    if workflow:
        write_json(workflow_path, workflow)
        parameters["workflow"] = WORKFLOW_FILE
    elif os.path.exists(workflow_path):
        os.unlink(workflow_path)

    data.update({
        "version": 1,
        "host": host_name(platform),
        "savedAt": time.time(),
        "parameters": parameters,
        "trays": trays
    })
    data.setdefault("name", os.path.basename(directory))
    data.setdefault("tags", [])
    data.setdefault("notes", "")

    if not data.get("final"):
        marked = marked_final(store_dir)

        if marked:
            write_final(data_dir, data, os.path.splitext(marked["path"])[1],
                        f"{marked['kind']}:{os.path.basename(marked['path'])}", path=marked["path"])

    write_json(os.path.join(data_dir, PROJECT_FILE), data)
    write_json(os.path.join(data_dir, PROMPT_HISTORY_FILE), read_prompt_history(store_dir))

    write_current(store_dir, {"path": relative(root, directory), "trays": hashes})
    return {"project": get_project(root, path), "current": get_current(root, store_dir)}


def open_project(root: str, store_dir: str, image_bench_dir: str, platform: str, path: str,
                 restore_trays: bool = True, merge: bool = False) -> Dict[str, Any]:
    """
    Restore the trays of a project into the workspace and make it current; merged, the images of the project are
    added to the trays. The parameters are restored by the popup
    """
    _, data_dir = project_paths(root, path)
    counts = {}

    if restore_trays:
        # A merge keeps the workspace images, which must be readable before anything is changed
        stores = {kind: read_tray_store_checked(store_dir, kind) for kind in TRAY_KINDS} if merge else {}

        for kind in TRAY_KINDS:
            directory_path = tray_dir(data_dir, kind)
            images = extract_tray_dir(directory_path, image_bench_dir, kind, platform) \
                if os.path.isfile(tray_file(directory_path)) else []

            if merge:
                content, _, count = stores[kind]
                existing = (json.loads(content).get("images") or []) if count else []
                keys = {image_key(image) for image in existing}
                images = existing + [image for image in images if image_key(image) not in keys]

            counts[kind] = len(images)
            replace_file(os.path.join(store_dir, TRAY_FILES[kind]), json.dumps({"version": 1, "images": images}))

    # Merged trays or parameters only leave the workspace with the project it belongs to
    if restore_trays and not merge:
        # Projects saved before the prompt history keep the history of the workspace
        history = read_json(os.path.join(data_dir, PROMPT_HISTORY_FILE))

        if history is not None:
            write_json(os.path.join(store_dir, PROMPT_HISTORY_FILE), history)

        write_current(store_dir, {"path": path,
                                  "trays": {kind: read_tray_store(store_dir, kind)[1] for kind in TRAY_KINDS}})

    return {"project": get_project(root, path), "current": get_current(root, store_dir), "trays": counts}


# ---------- Dispatch ----------

# Actions that change nothing, the only ones allowed on GET (a GET may come from a page of another site)
READ_ACTIONS = {"docs_tree", "docs_check", "doc", "doc_asset", "tree", "check", "project", "file", "tray",
                "tray_image", "current"}


def dispatch(action: str, args: Dict[str, Any], files: Dict[str, Any], config: Dict[str, Any],
             store_dir: str, image_bench_dir: str, platform: str, method: str = "POST"):
    """
    Run an action of the /image-bench/projects/<action> endpoint.
    args: query or JSON body; files: uploaded files by field name as (file name, content).
    Returns a JSON-serializable dict or a FileResult; raises ProjectError
    """
    if method.upper() in ("GET", "HEAD") and action not in READ_ACTIONS:
        raise ProjectError(f"{action} needs a POST request", 405)

    root = get_root(config)
    path = args.get("path") or ""

    # The docs of the Library tab, under their own root
    if action.startswith("doc"):
        from . import docs
        docs_root = docs.get_root(config, store_dir)

        if action == "docs_tree":
            return docs.get_tree(docs_root, store_dir)
        if action == "docs_check":
            check = str(args.get("root") or "").strip()
            return docs.check_root(os.path.normpath(check) if check else docs.default_root(store_dir), store_dir)
        if action == "doc":
            return docs.get_doc(docs_root, path)
        if action == "doc_asset":
            return docs.get_asset(docs_root, path)

    if action == "tree":
        return get_tree(root, store_dir)
    if action == "check":
        return check_root(os.path.normpath(str(args.get("root") or "").strip()) if args.get("root") else "")
    if action == "project":
        return get_project(root, path)
    if action == "file":
        return get_file(root, path, args.get("name") or "", str(args.get("thumb")).lower() in ("1", "true"))
    if action == "tray":
        return get_tray(root, path, args.get("kind") or "")
    if action == "tray_image":
        return get_tray_image(root, path, args.get("kind") or "", args.get("member") or "",
                              str(args.get("thumb")).lower() in ("1", "true"))
    if action == "current":
        return get_current(root, store_dir)
    if action == "set_current":
        return set_current(root, store_dir, args.get("path"))
    if action == "create_folder":
        return create_folder(root, path, args.get("name"))
    if action == "create_project":
        return create_project(root, path, args.get("name"), platform)
    if action == "rename":
        return rename(root, store_dir, path, args.get("name"))
    if action == "move":
        return move(root, store_dir, path, args.get("to") or "")
    if action == "delete":
        return delete(root, store_dir, path)
    if action == "reveal":
        return reveal(root, path)
    if action == "update":
        return update_project(root, path, args.get("changes") or {})
    if action == "delete_file":
        return delete_file(root, path, args.get("name") or "")
    if action == "write_infotext":
        return write_file_infotext(root, path, args.get("name") or "", str(args.get("infotext") or ""))
    if action == "add_file":
        upload = files.get("file")
        return add_file(root, path, upload[0] if upload else None, upload[1] if upload else None)
    if action == "set_final":
        upload = files.get("file")
        return set_final(root, path, name=args.get("name"), kind=args.get("kind"), member=args.get("member"),
                         filename=upload[0] if upload else None, content=upload[1] if upload else None)
    if action == "save":
        snapshot = args.get("snapshot") or {}
        return save_project(root, store_dir, image_bench_dir, platform, path, snapshot,
                            {name: content for name, (_, content) in files.items()})
    if action == "open":
        return open_project(root, store_dir, image_bench_dir, platform, path,
                            restore_trays=args.get("trays", True) is not False, merge=bool(args.get("merge")))

    raise ProjectError(f"Unknown action: {action}", 404)


def parse_args(query: Dict[str, Any], form: Dict[str, Any], body: Optional[bytes],
               files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Arguments of a request: the query, a JSON body, or the "data" part (JSON) of a multipart form, which is taken
    out of the files if it was sent as a file (a ComfyUI workflow exceeds the size limit of form fields)
    """
    args = dict(query)
    data = files.pop("data", None) if files is not None else None

    if data:
        args.update(json.loads(data[1]))
    elif form and form.get("data"):
        args.update(json.loads(form["data"]))
    elif body and body.strip():
        try:
            parsed = json.loads(body)
        except ValueError:
            raise ProjectError("Invalid request")

        if isinstance(parsed, dict):
            args.update(parsed)

    return args
