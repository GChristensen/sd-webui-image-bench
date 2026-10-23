"""
Export of model exploration results as a single self-contained HTML page.

The page is generated as a stream of chunks: images are base64-encoded piece by piece
straight from disk, so neither a whole image nor the whole page is ever held in memory.

This module is framework-agnostic and works with both FastAPI and aiohttp.
"""

import base64
import html
import json
import os
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# A multiple of 3, so that base64 chunks concatenate without padding in between
READ_CHUNK_SIZE = 3 * 64 * 1024

# The page with its style and lightbox script; the images go in place of the marker, {{title}} is the page title
PAGE_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "explore_export.html")
IMAGES_MARKER = "<!-- images -->\n"

_page_template: Optional[str] = None


def is_allowed_image(path: Optional[str], roots: Iterable[str]) -> bool:
    """Check that the path is an existing image file located under one of the given directories"""
    if not path or os.path.splitext(path)[1].lower() not in IMAGE_MEDIA_TYPES:
        return False

    real_path = os.path.normcase(os.path.realpath(path))

    if not os.path.isfile(real_path):
        return False

    for root in roots:
        if not root:
            continue

        real_root = os.path.normcase(os.path.realpath(root))

        try:
            if os.path.commonpath([real_path, real_root]) == real_root:
                return True
        except ValueError:  # Different drives
            pass

    return False


def export_file_name() -> str:
    return time.strftime("explore-%Y%m%d-%H%M%S.html")


def content_disposition() -> str:
    return f'attachment; filename="{export_file_name()}"'


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _encode_file(path: str) -> Iterator[bytes]:
    with open(path, "rb") as file:
        while chunk := file.read(READ_CHUNK_SIZE):
            yield base64.b64encode(chunk)


def generate_explore_html(
    groups: List[Dict[str, Any]],
    resolve_path: Callable[[Dict[str, Any]], Optional[str]],
    title: str = "Image Bench exploration",
    matrix: Optional[Dict[str, Any]] = None
) -> Iterator[bytes]:
    """
    Generate the exploration page chunk by chunk.

    Args:
        groups: List of {name, images: [{parameters, ...}]} in display order
        resolve_path: Returns the validated file path of an image, or None if it can not be embedded
        title: Page title
        matrix: {columns: [label], rows: [{name, images: [image | None]}]} of a matrix exploration,
                laid out as a grid instead of the groups
    """
    head, tail = _page_parts(title)
    yield head.encode("utf-8")

    if matrix:
        yield from _matrix_html(matrix, resolve_path)
    else:
        yield from _groups_html(groups, resolve_path)

    yield tail.encode("utf-8")


def _groups_html(groups: List[Dict[str, Any]],
                 resolve_path: Callable[[Dict[str, Any]], Optional[str]]) -> Iterator[bytes]:
    for group in groups:
        images = group.get("images") or []
        count = len(images)

        yield (f'<section class="model-group">'
               f'<div class="model-group-header"><h3 class="model-name" title="{_escape(group.get("name", ""))}">'
               f'{_escape(group.get("name", ""))}</h3>'
               f'<span class="model-group-count">{count} image{"" if count == 1 else "s"}</span></div>'
               f'<div class="model-images">').encode("utf-8")

        for image in images:
            yield from _image_html(image, resolve_path)

        yield b"</div></section>\n"


def _matrix_html(matrix: Dict[str, Any],
                 resolve_path: Callable[[Dict[str, Any]], Optional[str]]) -> Iterator[bytes]:
    """A grid with a row per model and a column per LoRA"""
    columns = matrix.get("columns") or []

    yield f'<div class="matrix" style="--columns: {len(columns)}"><div class="matrix-corner"></div>'.encode("utf-8")

    for label in columns:
        yield f'<div class="matrix-column-header" title="{_escape(label)}">{_escape(label)}</div>'.encode("utf-8")

    for row in matrix.get("rows") or []:
        name = _escape(row.get("name", ""))
        yield f'<div class="matrix-row-header" title="{name}">{name}</div>'.encode("utf-8")

        images = row.get("images") or []

        for i in range(len(columns)):
            image = images[i] if i < len(images) else None
            yield b'<div class="matrix-cell">'

            if image:
                yield from _image_html(image, resolve_path)
            else:
                yield b'<div class="matrix-empty"></div>'

            yield b'</div>'

        yield b"\n"

    yield b"</div>\n"


def _image_html(image: Dict[str, Any],
                resolve_path: Callable[[Dict[str, Any]], Optional[str]]) -> Iterator[bytes]:
    params = _escape(json.dumps(image.get("parameters") or {}, ensure_ascii=False))

    try:
        path = resolve_path(image)
    except Exception:
        path = None

    if not path:
        yield f'<figure class="image-frame missing" data-params="{params}"><span>Image not found</span></figure>'.encode("utf-8")
        return

    media_type = IMAGE_MEDIA_TYPES[os.path.splitext(path)[1].lower()]
    yield (f'<figure class="image-frame" data-params="{params}">'
           f'<button class="params-btn" title="Generation parameters">i</button>'
           f'<img src="data:{media_type};base64,').encode("utf-8")

    try:
        yield from _encode_file(path)
    except OSError:
        # The data URI is already open: leave it broken rather than the markup
        pass

    yield b'"></figure>'


def _page_parts(title: str) -> Tuple[str, str]:
    """The page around the images: the template explore_export.html split at its images marker"""
    global _page_template

    if _page_template is None:
        with open(PAGE_TEMPLATE, encoding="utf-8") as file:
            _page_template = file.read()

    head, tail = _page_template.split(IMAGES_MARKER, 1)
    return head.replace("{{title}}", _escape(title)), tail
