"""
Docs of the Library tab: a read-only view of the Markdown files and tag lists (CSV files of tag autocompletion:
tag, category, post count, aliases) under the docs root (the docsRoot setting of the
extension config, a local or UNC path as the server sees it; <extension>/model_docs by default).

The requests go through the /image-bench/projects/<action> endpoint (see projects.dispatch). All paths are relative
to the root ('/'-separated) and must stay inside it.
"""

import os
from typing import Any, Dict, List

from .projects import (BROWSER_EXTENSIONS, MAX_TREE_DEPTH, MEDIA_TYPES, SKIPPED_DIRS, FileResult, ProjectError,
                       relative, split_path)

DOCS_DIR = "model_docs"
DOC_EXTENSIONS = {".md", ".markdown"}
# Tag lists, served raw (through get_asset) and searched by the popup
TAG_EXTENSIONS = {".csv"}
# Images referenced by the docs, and the tag lists
ASSET_TYPES = {**{ext: MEDIA_TYPES[ext] for ext in BROWSER_EXTENSIONS}, ".svg": "image/svg+xml",
               ".csv": "text/csv; charset=utf-8"}

MAX_DOCS = 5000
MAX_DOC_SIZE = 2 * 1024 * 1024


def default_root(store_dir: str) -> str:
    """The docs folder of the extension (the parent of its store directory)"""
    return os.path.join(os.path.dirname(os.path.normpath(store_dir)), DOCS_DIR)


def get_root(config: Dict[str, Any], store_dir: str) -> str:
    root = ((config or {}).get("docsRoot") or "").strip()
    return os.path.normpath(root) if root else default_root(store_dir)


def resolve(root: str, path: str) -> str:
    """Absolute path of a path relative to the root, which must stay inside it"""
    if not os.path.isdir(root):
        raise ProjectError("The docs folder does not exist (Settings › Library).", 409)

    absolute = os.path.normpath(os.path.join(root, *split_path(path)))

    if os.path.normcase(os.path.commonpath([root, absolute])) != os.path.normcase(root):
        raise ProjectError("Invalid path")

    return absolute


def is_doc(name: str) -> bool:
    return os.path.splitext(name)[1].lower() in DOC_EXTENSIONS


def doc_kind(name: str):
    """'markdown', 'tags' or None"""
    ext = os.path.splitext(name)[1].lower()
    return "markdown" if ext in DOC_EXTENSIONS else "tags" if ext in TAG_EXTENSIONS else None


def scan_dir(root: str, directory: str, depth: int, count: List[int]) -> List[Dict[str, Any]]:
    """Folders (those holding docs) and docs of a directory: folders first, by name"""
    try:
        entries = sorted((entry for entry in os.scandir(directory) if not entry.name.startswith(".")),
                         key=lambda entry: entry.name.lower())
    except OSError:
        return []

    folders, docs = [], []

    for entry in entries:
        if count[0] >= MAX_DOCS:
            break

        try:
            if entry.is_dir():
                if depth < MAX_TREE_DEPTH and entry.name.lower() not in SKIPPED_DIRS:
                    children = scan_dir(root, entry.path, depth + 1, count)

                    if children:
                        folders.append({"type": "folder", "name": entry.name, "path": relative(root, entry.path),
                                        "children": children})
            elif doc_kind(entry.name):
                stat = entry.stat()
                count[0] += 1
                docs.append({"type": "doc", "kind": doc_kind(entry.name), "name": entry.name,
                             "path": relative(root, entry.path), "size": stat.st_size, "modified": stat.st_mtime})
        except OSError:
            continue

    return folders + docs


def get_tree(root: str, store_dir: str) -> Dict[str, Any]:
    result = {"root": root, "default": default_root(store_dir)}

    if not os.path.isdir(root):
        return {**result, "exists": False, "nodes": []}

    return {**result, "exists": True, "nodes": scan_dir(root, root, 0, [0])}


def check_root(root: str, store_dir: str) -> Dict[str, Any]:
    """Whether a root directory exists, and the number of docs under it"""
    tree = get_tree(root, store_dir)

    if not tree["exists"]:
        return {"exists": False, "docs": 0, "default": tree["default"], "error": "The directory does not exist"}

    def count(nodes):
        return sum(count(node["children"]) if node["type"] == "folder" else 1 for node in nodes)

    return {"exists": True, "docs": count(tree["nodes"]), "default": tree["default"]}


def get_doc(root: str, path: str) -> Dict[str, Any]:
    file_path = resolve(root, path)

    if not is_doc(file_path) or not os.path.isfile(file_path):
        raise ProjectError("Document not found", 404)

    stat = os.stat(file_path)

    if stat.st_size > MAX_DOC_SIZE:
        raise ProjectError("The document is too large.", 413)

    with open(file_path, "r", encoding="utf-8-sig", errors="replace") as file:
        text = file.read()

    return {"path": relative(root, file_path), "name": os.path.basename(file_path), "text": text,
            "modified": stat.st_mtime}


def get_asset(root: str, path: str) -> FileResult:
    """An image referenced by a doc, or a tag list"""
    file_path = resolve(root, path)
    media_type = ASSET_TYPES.get(os.path.splitext(file_path)[1].lower())

    if not media_type or not os.path.isfile(file_path):
        raise ProjectError("File not found", 404)

    return FileResult(media_type, path=file_path)
