"""
Shared tray management functions for image and concept trays.
Handles upload, download, import, and export operations.

This module is framework-agnostic and works with both FastAPI and aiohttp.
"""

import asyncio
import filecmp
import os
import json
import time
import zipfile
import re
import shutil
from typing import Dict, Any, Optional, Tuple, Union
from urllib.parse import quote
from PIL import Image

from .controlnet_inputs import image_hashes, input_path
from .persist import read_json_file, replace_file

# Store files of the persistent image collections by kind; the images are copied to image-bench/<kind>/
TRAY_FILES = {
    "image_tray": "image_tray.json",
    "concept_tray": "concept_tray.json",
    "upscaled": "upscaled.json",
    "compare": "compare.json"
}

# Kind of the images of the Compare tab, which are saved to image-bench/compare/ when uploaded or sent from Photoshop
COMPARE_KIND = "compare"


def parse_pnginfo(input_string: str) -> Dict[str, Any]:
    """
    Parse PNG metadata string into a dictionary.

    Args:
        input_string: PNG metadata string to parse

    Returns:
        Dictionary of parsed metadata
    """
    def tokenize(string):
        token_pattern = re.compile(r''':(?=(?:[^"]|"[^"]*")*$)|,(?=(?:[^"]|"[^"]*")*$)''')
        return token_pattern.split(string)

    def parse_tokens(tokens):
        result = {}
        i = 0
        while i < len(tokens):
            key_token = tokens[i].strip()
            if i + 1 < len(tokens):
                value_token = tokens[i+1].strip()

                if value_token.startswith('"') and value_token.endswith('"'):
                    nested_string = value_token[1:-1]
                    result[key_token.lower()] = parse_pnginfo(nested_string)
                    i += 2
                else:
                    result[key_token.lower()] = value_token
                    i += 2
            else:
                i += 1
        return result

    tokens = tokenize(input_string)
    parsed_result = parse_tokens(tokens)
    return parsed_result


def prompts_from_pnginfo(pnginfo: str) -> Tuple[str, str]:
    """
    Extract positive and negative prompts from PNG info string.

    Args:
        pnginfo: PNG metadata string

    Returns:
        Tuple of (positive_prompt, negative_prompt)
    """
    lines = pnginfo.split("\n")
    lines = lines[:-1]
    neg_start = len(lines)

    for i, line in enumerate(lines):
        if line.startswith("Negative prompt: "):
            neg_start = i

    p = "\n".join(lines[:neg_start])
    n = "\n".join(lines[neg_start:]).replace("Negative prompt: ", "")

    return p, n


def pnginfo_to_dict(prompt: str, negative_prompt: str, pnginfo: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert PNG info to a dictionary with prompts and parameters.

    Args:
        prompt: Positive prompt text
        negative_prompt: Negative prompt text
        pnginfo: PNG metadata dictionary

    Returns:
        Dictionary with prompt and parsed parameters
    """
    parts = pnginfo["parameters"].split("\n")
    result_dict = {
        "prompt": prompt,
        "negative prompt": negative_prompt,
    }

    return result_dict | parse_pnginfo(parts[-1])


async def save_image_to_tray(
    image_data: Dict[str, Any],
    kind: str,
    image_bench_dir: str,
    platform: str
) -> Dict[str, Any]:
    """
    Copy image file to tray directory and update paths.

    This function handles the physical copying of images when they are added to trays,
    ensuring they are stored in dedicated tray directories with platform-specific naming.

    Args:
        image_data: Dictionary containing image metadata with keys:
                    - imagePath: Source path of the image file
                    - imageUrl: Current URL for accessing the image
                    - parameters: Dict with generation parameters (must include prompt_id for ComfyUI)
        kind: Type of tray - "image_tray" or "concept_tray"
        image_bench_dir: Base directory for image bench files (e.g., outputs/image-bench/)
        platform: Platform identifier - "webui" or "comfyui"

    Returns:
        Updated image_data dictionary with new imagePath and imageUrl pointing to tray directory

    Raises:
        FileNotFoundError: If source image file doesn't exist
        KeyError: If required fields are missing from image_data
    """
    # Create tray directory if it doesn't exist
    tray_dir = os.path.join(image_bench_dir, kind)
    os.makedirs(tray_dir, exist_ok=True)

    # Get source image path
    source_path = image_data["imagePath"]

    # Check if source file exists
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"Source image not found: {source_path}")

    # Determine destination filename based on platform; ComfyUI images are named by their unique prompt_id,
    # images without one (e.g. uploaded) keep their file name like in WebUI
    prompt_id = (image_data.get("parameters") or {}).get("prompt_id") if platform == "comfyui" else None

    if prompt_id:
        # Extract file extension from source (usually .png)
        _, ext = os.path.splitext(source_path)
        new_filename = f"{prompt_id}{ext}"
    else:
        new_filename = os.path.basename(source_path)

    # Handle filename conflicts; a file of the prompt_id is the same image again unless its content differs
    # (several outputs of one prompt: images of a batch, a video and its audio)
    dest_path = os.path.join(tray_dir, new_filename)
    if os.path.exists(dest_path) and not (prompt_id and same_content(source_path, dest_path)):
        # Append counter if file exists
        base_name, ext = os.path.splitext(new_filename)
        counter = 1
        while os.path.exists(dest_path):
            new_filename = f"{base_name}_{counter:03d}{ext}"
            dest_path = os.path.join(tray_dir, new_filename)
            counter += 1

    # Copy file to tray directory (only if not already there)
    if os.path.abspath(source_path) != os.path.abspath(dest_path):
        shutil.copy2(source_path, dest_path)

    # Update image data with new paths, keeping the original path for duplicate detection
    image_data.setdefault("sourcePath", source_path)
    image_data["imagePath"] = dest_path

    if platform == "comfyui":
        # ComfyUI: Update URL to use subfolder format
        # Format: /view?filename=<filename>&type=output&subfolder=image-bench/<kind>
        subfolder = f"image-bench/{kind}"
        image_data["imageUrl"] = f"/view?filename={new_filename}&type=output&subfolder={subfolder}"
    else:
        # WebUI: Update URL to use /file= format
        image_data["imageUrl"] = f"/file={dest_path}"

    return image_data


def same_content(path: str, other: str) -> bool:
    try:
        return os.path.samefile(path, other) or filecmp.cmp(path, other, shallow=False)
    except OSError:
        return False


def safe_file_name(filename: Optional[str], default: str) -> str:
    """The name part of a file name sent by a client, without characters invalid in file names or URLs"""
    name = re.sub(r'[<>:"/\|?*&#%\x00-\x1f]', "_", os.path.basename((filename or "").replace("\\", "/"))).strip(" .")
    return name or default


def unique_file_path(directory: str, filename: str) -> str:
    """Path of a file in the directory that does not exist yet: the file name with a counter if it is taken"""
    path = os.path.join(directory, filename)
    base_name, ext = os.path.splitext(filename)
    counter = 1

    while os.path.exists(path):
        path = os.path.join(directory, f"{base_name}_{counter:03d}{ext}")
        counter += 1

    return path


def save_compare_file(filename: str, file_data: bytes, image_bench_dir: str, platform: str) -> Dict[str, Any]:
    """
    Save an image uploaded to the Compare tab or sent there from Photoshop to image-bench/compare/.
    Images without PNG info are accepted (their parameters are empty).

    Args:
        filename: Name of the image file
        file_data: File content
        image_bench_dir: Base directory for image bench files
        platform: Platform identifier - "webui" or "comfyui"

    Returns:
        Image data of the Compare tab, marked as already copied to its directory (see save_tray_images())

    Raises:
        ValueError: If the file is not an image
    """
    compare_dir = os.path.join(image_bench_dir, COMPARE_KIND)
    os.makedirs(compare_dir, exist_ok=True)

    path = unique_file_path(compare_dir, safe_file_name(filename, "image.png"))

    with open(path, "wb") as f:
        f.write(file_data)

    parameters = {}

    try:
        with Image.open(path) as image:
            text = getattr(image, "text", None) or {}

            if text.get("parameters"):
                p, n = prompts_from_pnginfo(text["parameters"])
                parameters = pnginfo_to_dict(p, n, text)
    except Exception as e:
        os.unlink(path)
        raise ValueError(f"Not an image: {filename}") from e

    new_filename = os.path.basename(path)

    if platform == "comfyui":
        image_url = f"/view?filename={quote(new_filename)}&type=output&subfolder=image-bench/{COMPARE_KIND}"
    else:
        image_url = f"/file={path.replace(os.sep, '/')}"

    return {
        "imagePath": path,
        "imageUrl": image_url,
        "fileName": new_filename,
        "parameters": parameters,
        "_tray_processed": True
    }


def append_tray_image(store_dir: str, kind: str, image: Dict[str, Any]) -> None:
    """Add an image to the store file of a tray, so that it is there even if the popup is closed"""
    path = os.path.join(store_dir, TRAY_FILES[kind])
    content = read_json_file(path) if os.path.exists(path) else None
    content = content or {"version": 1, "images": []}
    content.setdefault("images", []).append(image)

    replace_file(path, json.dumps(content))


async def save_tray_images(tray_data: Dict[str, Any], kind: str, image_bench_dir: str, platform: str) -> None:
    """
    Copy the images not copied yet to the directory of the tray (see save_image_to_tray())

    Args:
        tray_data: Tray content posted by the popup ({version, images})
        kind: Key of TRAY_FILES
        image_bench_dir: Base directory for image bench files
        platform: Platform identifier - "webui" or "comfyui"
    """
    for image in tray_data.get("images", []):
        if not image.get("_tray_processed"):
            try:
                await save_image_to_tray(image, kind, image_bench_dir, platform)
                # Mark as processed to avoid re-copying on subsequent saves
                image["_tray_processed"] = True
            except Exception as e:
                # Continue with other images even if one fails
                print(f"[Image Bench] Error copying image to tray: {e}")


# Seconds the file of an image removed from a tray is kept, so that the Undo of the removal (6 s) finds it
REMOVED_FILE_DELAY = 10

# Deletions waiting for their delay (asyncio keeps only weak references to tasks)
_deletion_tasks = set()


def tray_file_paths(images, image_bench_dir: str) -> set:
    """Normalized paths of the image files that are copies in a tray directory (image-bench/<kind>/)"""
    tray_dirs = {os.path.normcase(os.path.abspath(os.path.join(image_bench_dir, kind))) for kind in TRAY_FILES}
    paths = set()

    for image in images or []:
        path = image.get("imagePath") if isinstance(image, dict) else None

        if path:
            path = os.path.normcase(os.path.abspath(path))

            if os.path.dirname(path) in tray_dirs:
                paths.add(path)

    return paths


def read_tray_file_paths(store_path: str, image_bench_dir: str) -> Optional[set]:
    """The tray files a store file refers to; None if it exists but cannot be read"""
    if not os.path.exists(store_path):
        return set()

    content = read_json_file(store_path)
    return None if content is None else tray_file_paths(content.get("images"), image_bench_dir)


def removed_tray_files(store_path: str, tray_data: Dict[str, Any], image_bench_dir: str) -> set:
    """The tray files of the stored tray that the new content no longer has (call before the store file is written)"""
    stored = read_tray_file_paths(store_path, image_bench_dir) or set()
    return stored - tray_file_paths(tray_data.get("images"), image_bench_dir)


def delete_unreferenced_tray_files(paths: set, store_dir: str, image_bench_dir: str) -> None:
    """Delete the tray files that no tray store refers to (an image moved to another tray keeps its file)"""
    referenced = set()

    for filename in TRAY_FILES.values():
        paths_of_store = read_tray_file_paths(os.path.join(store_dir, filename), image_bench_dir)

        # An unreadable store may refer to any of them
        if paths_of_store is None:
            return

        referenced |= paths_of_store

    for path in paths - referenced:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"[Image Bench] Error deleting a removed tray image: {e}")


def schedule_tray_file_deletion(paths: set, store_dir: str, image_bench_dir: str) -> None:
    """
    Delete the files of removed tray images after REMOVED_FILE_DELAY, unless a tray store refers to them then
    (an undone removal brings the entry back)
    """
    if not paths:
        return

    async def delete_later():
        await asyncio.sleep(REMOVED_FILE_DELAY)
        delete_unreferenced_tray_files(paths, store_dir, image_bench_dir)

    task = asyncio.get_running_loop().create_task(delete_later())
    _deletion_tasks.add(task)
    task.add_done_callback(_deletion_tasks.discard)


async def image_tray_upload(
    filename: str,
    file_data: bytes,
    image_bench_dir: str,
    image_tray_file: str
) -> Dict[str, Any]:
    """
    Handle image tray upload (single image or zip archive).

    Args:
        filename: Name of the uploaded file
        file_data: File content as bytes
        image_bench_dir: Base directory for image bench files
        image_tray_file: Name of the image tray JSON file

    Returns:
        Dictionary with imported image data or error
    """
    imported_dir = os.path.join(image_bench_dir, "images")
    os.makedirs(imported_dir, exist_ok=True)
    # Only the name part of the client's file name, so that the file stays in the directory; a new name if it is taken
    imported_file = unique_file_path(imported_dir, safe_file_name(filename, "image.png"))

    with open(imported_file, "wb") as f:
        f.write(file_data)

    if imported_file.lower().endswith(".zip"):
        return import_image_tray(imported_file, image_bench_dir, image_tray_file)
    else:
        result = {"error": "No PNGINFO text found."}

        with Image.open(imported_file) as image:
            text = getattr(image, "text", None) or {}
            parameters = text.get("parameters")

            if parameters:
                p, n = prompts_from_pnginfo(parameters)
                result = {
                    "imagePath": imported_file,
                    "parameters": pnginfo_to_dict(p, n, text)
                }

        return result


def download_image_tray(
    kind: str,
    image_bench_dir: str,
    store_dir: str,
    image_tray_file: str
) -> Tuple[Optional[str], int]:
    """
    Download a tray or the upscaled images as a zip archive.

    Args:
        kind: Key of TRAY_FILES
        image_bench_dir: Base directory for image bench files
        store_dir: Directory containing tray JSON files
        image_tray_file: Name of the image tray JSON file, under which the archive holds the tray
                         content, so that any archive can be imported into a tray

    Returns:
        Tuple of (zip_file_path, status_code) where:
        - zip_file_path is the path to the generated zip file, or None if empty/not found
        - status_code is 200 (OK), 204 (No Content), or 404 (Not Found)
    """
    export_dir = os.path.join(image_bench_dir, "export")
    export_file = os.path.join(export_dir, str(round(time.time() * 1000)) + ".zip")
    os.makedirs(export_dir, exist_ok=True)

    tray_filename = TRAY_FILES.get(kind)
    tray_file_path = tray_filename and os.path.join(store_dir, tray_filename)

    if tray_file_path and os.path.exists(tray_file_path):
        image_tray = read_json_file(tray_file_path) or {}
        # Images whose file was deleted are left out, so that the others can still be downloaded
        images = [image for image in image_tray.get("images") or [] if os.path.isfile(image.get("imagePath") or "")]
        image_tray["images"] = images
        controlnet_inputs = set()

        if images:
            with zipfile.ZipFile(export_file, "w", zipfile.ZIP_DEFLATED) as zip_file:
                archive_names = set()

                for image in images:
                    # Images of different directories may have the same name
                    name = os.path.basename(image["imagePath"])
                    base_name, ext = os.path.splitext(name)
                    counter = 1

                    while name.lower() in archive_names:
                        name = f"{base_name}_{counter:03d}{ext}"
                        counter += 1

                    archive_names.add(name.lower())
                    archive_name = "images/" + name
                    zip_file.write(image["imagePath"], archive_name)
                    image["imagePath"] = archive_name
                    controlnet_inputs |= image_hashes(image)

                zip_file.writestr(image_tray_file, json.dumps(image_tray))
                write_controlnet_inputs(zip_file, controlnet_inputs, image_bench_dir)

            return (export_file, 200)  # OK
        else:
            return (None, 204)  # No Content
    else:
        return (None, 404)  # Not Found


def write_controlnet_inputs(archive: zipfile.ZipFile, hashes, image_bench_dir: str) -> None:
    """The stored ControlNet inputs of the images of an archive, as controlnet/<hash>.png (missing ones skipped)"""
    for value in sorted(hashes):
        try:
            archive.write(input_path(image_bench_dir, value), f"controlnet/{value}.png")
        except FileNotFoundError:
            pass


def import_image_tray(
    archive_path: str,
    image_bench_dir: str,
    image_tray_file: str
) -> Union[list, Dict[str, str]]:
    """
    Import image tray from a zip archive.

    Args:
        archive_path: Path to zip archive
        image_bench_dir: Base directory for image bench files
        image_tray_file: Name of the image tray JSON file

    Returns:
        List of imported images or dict with error message
    """
    tray_file_path = os.path.join(image_bench_dir, image_tray_file)
    image_tray = None

    try:
        with zipfile.ZipFile(archive_path, "r") as zip_file:
            if image_tray_file in zip_file.namelist():
                zip_file.extractall(image_bench_dir)

                image_tray = read_json_file(tray_file_path)

                if image_tray:
                    root = os.path.abspath(image_bench_dir)
                    images = []

                    # Only the files of the archive: a path of the tray file pointing elsewhere would let the tray
                    # copy any file of the server
                    for image in image_tray.get("images") or []:
                        path = os.path.abspath(os.path.join(root, str(image.get("imagePath") or "")))

                        try:
                            inside = path != root and os.path.commonpath([root, path]) == root
                        except ValueError:  # Another drive
                            inside = False

                        if inside:
                            image["imagePath"] = image_bench_dir + "/" + os.path.relpath(path, root).replace(os.sep, "/")
                            images.append(image)

                    return images
    finally:
        if image_tray:
            os.unlink(tray_file_path)
        os.unlink(archive_path)

    return {"error": "Error extracting archive."}