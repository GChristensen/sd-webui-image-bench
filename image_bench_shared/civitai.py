"""
Civitai model lookup by file hash, shared by the SD WebUI and ComfyUI backends.

The lookup is synchronous (urllib); aiohttp handlers run it in an executor.
Found model versions are stored as raw Civitai responses in <store>/civitai/<HASH>.json,
so they are not requested again; delete a file to refresh its info.
"""

import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from .persist import read_json_file

CIVITAI_API = "https://civitai.com/api/v1/model-versions/by-hash/"
CIVITAI_DOMAINS = ("com", "red")  # civitai.red also shows mature content
CIVITAI_TIMEOUT = 10
USER_AGENT = "image-bench"

CACHE_SUBDIR = "civitai"

# hash -> normalized lookup result (not-found results too, network errors are not cached)
_lookup_cache: Dict[str, Dict[str, Any]] = {}

_re_hash = re.compile(r"[0-9A-F]{8,64}")
_hash_cache_lock = threading.Lock()


def site_url(domain: str = "com") -> str:
    """Base URL of the Civitai site pages for a domain from CIVITAI_DOMAINS (the API always uses civitai.com)"""
    return f"https://civitai.{domain if domain in CIVITAI_DOMAINS else 'com'}"


def search_url(name: str, domain: str = "com") -> str:
    """Civitai model search by the file name without folders and extension"""
    query = os.path.basename(name.replace("\\", "/"))
    query = re.sub(r"\.(safetensors|ckpt|pt|pth|bin|gguf)$", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\s*\[[0-9a-fA-F]+]$", "", query)  # WebUI title hash suffix
    return site_url(domain) + "/search/models?" + urllib.parse.urlencode({"query": query})


def _normalize(data: Dict[str, Any], hash_value: str) -> Dict[str, Any]:
    model = data.get("model") or {}
    images = data.get("images") or []
    preview = next((image.get("url") for image in images if image.get("type", "image") == "image"), None)

    return {
        "found": True,
        "hash": hash_value,
        "url": f"/models/{data.get('modelId')}?modelVersionId={data.get('id')}",  # site_url() is prepended by model_info()
        "modelName": model.get("name") or "",
        "versionName": data.get("name") or "",
        "type": model.get("type") or "",
        "baseModel": data.get("baseModel") or "",
        "trainedWords": [w.strip() for w in data.get("trainedWords") or [] if w and w.strip()],
        "previewUrl": preview,
    }


def _read_stored(hash_value: str, store_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    if not store_dir:
        return None

    path = os.path.join(store_dir, CACHE_SUBDIR, f"{hash_value}.json")
    return read_json_file(path) if os.path.isfile(path) else None


def _write_stored(hash_value: str, store_dir: Optional[str], data: Dict[str, Any]):
    if not store_dir:
        return

    try:
        directory = os.path.join(store_dir, CACHE_SUBDIR)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, f"{hash_value}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError as e:
        print(f"[Image Bench] Unable to store Civitai info of {hash_value}: {e}")


def lookup(hash_value: str, store_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Find a model version on Civitai by any hash Civitai indexes (SHA256, AutoV2, AutoV3, ...).

    Args:
        hash_value: Model hash
        store_dir: Extension store directory; found versions are read from and saved to its civitai/ subdirectory

    Returns:
        Normalized result with found=True, {found: False} if Civitai does not know the hash,
        or {found: False, error} on a network error
    """
    hash_value = hash_value.strip().upper()

    # The hash names the stored file, so only hexadecimal hashes are accepted
    if not _re_hash.fullmatch(hash_value):
        return {"found": False, "error": f"Invalid model hash: {hash_value}"}

    if hash_value in _lookup_cache:
        return _lookup_cache[hash_value]

    stored = _read_stored(hash_value, store_dir)

    if stored:
        result = _lookup_cache[hash_value] = _normalize(stored, hash_value)
        return result

    request = urllib.request.Request(CIVITAI_API + hash_value, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=CIVITAI_TIMEOUT) as response:
            data = json.loads(response.read())
            result = _normalize(data, hash_value)
            _write_stored(hash_value, store_dir, data)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return {"found": False, "error": f"Civitai request failed: {e.code} {e.reason}"}
        result = {"found": False}
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {"found": False, "error": f"Civitai request failed: {e}"}

    _lookup_cache[hash_value] = result
    return result


def file_sha256(path: str, cache_path: str) -> str:
    """
    SHA256 of a file, cached in a JSON file by path, modification time and size

    Args:
        path: Model file
        cache_path: JSON cache file, created if missing
    """
    stat = os.stat(path)
    key = os.path.normcase(os.path.abspath(path))

    with _hash_cache_lock:
        cache = (read_json_file(cache_path) if os.path.isfile(cache_path) else None) or {}
        entry = cache.get(key)

        if entry and entry.get("mtime") == stat.st_mtime and entry.get("size") == stat.st_size:
            return entry["sha256"]

    print(f"[Image Bench] Calculating sha256 for {path}")
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    sha256 = digest.hexdigest()

    with _hash_cache_lock:
        cache = (read_json_file(cache_path) if os.path.isfile(cache_path) else None) or {}
        cache[key] = {"mtime": stat.st_mtime, "size": stat.st_size, "sha256": sha256}
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=1)

    return sha256


def model_info(name: str = "", hash_value: str = "", file_hash=None, store_dir: Optional[str] = None,
               domain: str = "com") -> Dict[str, Any]:
    """
    Endpoint payload: the Civitai lookup result plus a search URL to fall back on.

    The given hash is tried first (e.g. a hash from image metadata). If Civitai does not know it,
    and file_hash is given, the full SHA256 of the local file is tried.

    Args:
        name: Model name or file name, used for the search URL
        hash_value: Known hash of the model, may be empty
        file_hash: Callable returning the SHA256 of the local model file, or None if the model is not found
        store_dir: Extension store directory for the stored Civitai info, see lookup()
        domain: Civitai domain of the page URLs, see CIVITAI_DOMAINS
    """
    result: Optional[Dict[str, Any]] = None

    if hash_value:
        result = lookup(hash_value, store_dir)

    if (not result or not result["found"] and "error" not in result) and file_hash:
        sha256 = file_hash()

        if sha256 and sha256.upper() != hash_value.upper():
            result = lookup(sha256, store_dir)
        elif not result:
            result = {"found": False, "error": "The model file is not found or hashing is disabled."}

    if not result:
        result = {"found": False, "error": "The model is not found."}

    result = {**result, "name": name, "searchUrl": search_url(name, domain) if name else None}

    if result.get("url"):
        result["url"] = site_url(domain) + result["url"]

    return result
