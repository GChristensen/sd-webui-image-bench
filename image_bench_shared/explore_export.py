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
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

# A multiple of 3, so that base64 chunks concatenate without padding in between
READ_CHUNK_SIZE = 3 * 64 * 1024


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
    yield _page_head(title).encode("utf-8")

    if matrix:
        yield from _matrix_html(matrix, resolve_path)
    else:
        yield from _groups_html(groups, resolve_path)

    yield _PAGE_TAIL.encode("utf-8")


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


def _page_head(title: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="Image Bench">
<title>{_escape(title)}</title>
<style>{_PAGE_STYLE}</style>
</head>
<body>
<header class="page-header"><h1>{_escape(title)}</h1></header>
<main class="generated-images">
"""


_PAGE_STYLE = """
:root {
  --ib-bg: #111317;
  --ib-surface: #16191d;
  --ib-elev-2: #252930;
  --ib-border: #2a2e35;
  --ib-border-2: #3a3f48;
  --ib-text: #e3e6ea;
  --ib-text-2: #a7aeb8;
  --ib-muted: #7d8590;
  --ib-accent: #2cbf8a;
  color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--ib-bg);
  color: var(--ib-text);
  font-family: 'Segoe UI', Inter, -apple-system, BlinkMacSystemFont, Roboto, 'Helvetica Neue', sans-serif;
  font-size: 14px;
  line-height: 1.4;
}
.page-header { padding: 12px 16px 0; }
.page-header h1 { margin: 0; font-size: 15px; font-weight: 600; color: var(--ib-text-2); }
.generated-images { padding: 12px 16px; display: flex; flex-direction: column; gap: 12px; }
.model-group {
  display: flex; flex-direction: column; gap: 8px;
  padding: 8px 10px 10px;
  background: var(--ib-surface);
  border: 1px solid var(--ib-border);
  border-radius: 6px;
}
.model-group-header { display: flex; align-items: center; gap: 8px; min-width: 0; }
.model-name {
  margin: 0; font-size: 13.5px; font-weight: 600; color: var(--ib-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.model-group-count { font-size: 12px; color: var(--ib-muted); white-space: nowrap; }
.model-images { display: flex; flex-wrap: wrap; gap: 10px; }
.image-frame {
  position: relative; margin: 0; max-width: min(30%, 27vw);
  line-height: 0; border-radius: 4px; overflow: hidden;
}
.image-frame img { display: block; max-width: 100%; max-height: 70vh; cursor: pointer; }
.image-frame.missing {
  display: flex; align-items: center; justify-content: center;
  width: 160px; height: 160px; line-height: normal;
  border: 1px dashed var(--ib-border-2); color: var(--ib-muted); font-size: 12px;
}
.matrix {
  display: grid; gap: 10px; align-items: start;
  grid-template-columns: minmax(120px, 200px) repeat(var(--columns), minmax(200px, 1fr));
}
.matrix-corner, .matrix-column-header, .matrix-row-header {
  min-width: 0; font-size: 13px; font-weight: 600; color: var(--ib-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; background: var(--ib-bg);
}
.matrix-corner, .matrix-column-header { position: sticky; top: 0; z-index: 2; padding: 4px 2px; }
.matrix-row-header { padding: 8px 8px 0 2px; }
.matrix-cell { min-width: 0; }
.matrix-cell .image-frame { max-width: 100%; }
.matrix-empty { aspect-ratio: 1; border: 1px dashed var(--ib-border); border-radius: 6px; }
.params-btn, .lightbox button {
  font: 600 13px/1 Georgia, serif; color: var(--ib-text); cursor: pointer;
  background: rgba(17, 19, 23, 0.85); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 4px;
}
.params-btn { position: absolute; top: 6px; left: 6px; width: 24px; height: 24px; opacity: 0; transition: opacity 0.15s; }
.image-frame:hover .params-btn { opacity: 1; }
.params-btn:hover, .lightbox button:hover { background: var(--ib-elev-2); border-color: var(--ib-border-2); }
.lightbox {
  position: fixed; inset: 0; z-index: 10; display: none;
  align-items: center; justify-content: center; gap: 12px; padding: 16px;
  background: rgba(0, 0, 0, 0.88);
}
.lightbox.open { display: flex; }
.lightbox img { max-width: 100%; max-height: 100%; object-fit: contain; min-width: 0; }
.lightbox.with-params img { max-width: calc(100% - 432px); }
.lightbox pre {
  display: none; flex: 0 0 420px; max-height: 100%; overflow: auto; margin: 0; padding: 12px;
  white-space: pre-wrap; word-break: break-word; font: 12.5px/1.45 Consolas, monospace;
  background: var(--ib-surface); border: 1px solid var(--ib-border); border-radius: 6px;
}
.lightbox.with-params pre { display: block; }
.lightbox .lb-controls { position: fixed; top: 12px; right: 16px; display: flex; gap: 6px; }
.lightbox .lb-controls button { height: 28px; min-width: 28px; padding: 0 8px; font-family: inherit; font-weight: 400; }
.lightbox .lb-counter { position: fixed; bottom: 10px; left: 50%; transform: translateX(-50%); color: var(--ib-muted); font-size: 12px; }
"""


_PAGE_TAIL = """</main>
<div class="lightbox" id="lightbox">
  <img alt="">
  <pre></pre>
  <div class="lb-controls">
    <button data-act="prev" title="Previous (←)">←</button>
    <button data-act="next" title="Next (→)">→</button>
    <button data-act="params" title="Generation parameters (P)">Params</button>
    <button data-act="close" title="Close (Esc)">✕</button>
  </div>
  <span class="lb-counter"></span>
</div>
<script>
(() => {
  const frames = [...document.querySelectorAll(".image-frame:not(.missing)")];
  const box = document.getElementById("lightbox");
  const boxImage = box.querySelector("img");
  const boxParams = box.querySelector("pre");
  const counter = box.querySelector(".lb-counter");
  let index = -1;

  const capitalize = s => s.charAt(0).toUpperCase() + s.slice(1);

  // Mirrors createImageGenerationParams() of the Image Bench app
  function formatParams(params) {
    let text = `Prompt:\\n${params["prompt"] ?? ""}\\n\\nNegative prompt:\\n${params["negative prompt"] ?? ""}\\n\\n`;

    for (const [key, value] of Object.entries(params)) {
      if (key === "prompt" || key === "negative prompt")
        continue;

      if (value && typeof value === "object") {
        text += capitalize(key) + ":\\n";
        for (const [subKey, subValue] of Object.entries(value))
          text += "  " + capitalize(subKey) + ": " + subValue + "\\n";
      }
      else
        text += capitalize(key) + ": " + value + "\\n";
    }

    return text;
  }

  function show(i, withParams) {
    index = (i + frames.length) % frames.length;
    const frame = frames[index];
    boxImage.src = frame.querySelector("img").src;
    boxParams.textContent = formatParams(JSON.parse(frame.dataset.params || "{}"));
    counter.textContent = `${index + 1} / ${frames.length}`;
    if (withParams !== undefined)
      box.classList.toggle("with-params", withParams);
    box.classList.add("open");
  }

  function close() {
    box.classList.remove("open");
    boxImage.removeAttribute("src");
    index = -1;
  }

  frames.forEach((frame, i) => {
    frame.querySelector("img").addEventListener("click", () => show(i, false));
    frame.querySelector(".params-btn").addEventListener("click", () => show(i, true));
  });

  box.addEventListener("click", e => {
    const act = e.target.dataset.act;
    if (act === "prev") show(index - 1);
    else if (act === "next") show(index + 1);
    else if (act === "params") box.classList.toggle("with-params");
    else if (act === "close" || e.target === box) close();
  });

  document.addEventListener("keydown", e => {
    if (index < 0) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") show(index - 1);
    else if (e.key === "ArrowRight") show(index + 1);
    else if (e.key === "p" || e.key === "P") box.classList.toggle("with-params");
  });
})();
</script>
</body>
</html>
"""
