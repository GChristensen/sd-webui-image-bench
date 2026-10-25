"""
Generation parameters (infotext) of an image file, shown by the PNG Info dialog of the Generate tab and the images of
the project folders. WebUI reads the infotext with its own reader (PNG text, JPEG/WebP EXIF, NovelAI); ComfyUI with
read_infotext(). An image saved by ComfyUI has no infotext: its prompt is turned into one (comfy_prompt.py).
Both parse it into the parameters of the image trays (tray.pnginfo_to_dict(): lowercase keys, "size": "WxH").
"""

import io
import re
from typing import Any, Callable, Dict, Optional

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from .comfy_prompt import read_comfy_infotext
from .persist import replace_file
from .tray import pnginfo_to_dict, prompts_from_pnginfo

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# A "key: value" pair of the parameter line, as WebUI matches it (modules/infotext_utils.py)
RE_PARAM = re.compile(r'\s*(\w[\w \-/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')

EXIF_IFD = 0x8769
EXIF_USER_COMMENT = 0x9286


def decode_user_comment(value: Any) -> Optional[str]:
    """Text of an EXIF UserComment: an 8 byte character code, then the text (WebUI writes UTF-16BE)"""
    if isinstance(value, str):
        return value

    if not isinstance(value, bytes):
        return None

    code, content = value[:8], value[8:]

    if code == b"UNICODE\x00":
        return content.decode("utf_16_be", errors="ignore")

    if code in (b"ASCII\x00\x00\x00", b"\x00" * 8):
        return content.decode("utf8", errors="ignore")

    return value.decode("utf8", errors="ignore")


def read_infotext(image: Image.Image) -> Optional[str]:
    """Infotext of an image: PNG text, EXIF UserComment (JPEG, WebP) or comment (GIF)"""
    info = image.info or {}

    if info.get("parameters"):
        return info["parameters"]

    try:
        comment = image.getexif().get_ifd(EXIF_IFD).get(EXIF_USER_COMMENT)
        text = decode_user_comment(comment)

        if text and text.strip("\x00 "):
            return text.strip("\x00")
    except Exception:
        pass

    comment = info.get("comment")

    if isinstance(comment, bytes):
        comment = comment.decode("utf8", errors="ignore")

    return comment or None


def parse_infotext(infotext: str) -> Dict[str, Any]:
    """
    Parameters of an infotext; text without a parameter line (fewer than 3 parameters in its last line,
    as WebUI decides) is all prompt
    """
    text = infotext.strip()

    if len(RE_PARAM.findall(text.split("\n")[-1])) < 3:
        text += "\n"

    p, n = prompts_from_pnginfo(text)
    parameters = pnginfo_to_dict(p, n, {"parameters": text})

    # An infotext without a negative prompt has no "negative prompt" parameter, as in the trays
    if not n:
        parameters.pop("negative prompt", None)

    return parameters


def image_info(file_data: bytes, reader: Callable[[Image.Image], Optional[str]] = read_infotext) -> Dict[str, Any]:
    """
    Infotext and parameters of an image file

    Args:
        file_data: Content of the image file
        reader: Reads the infotext of the opened image

    Returns:
        {infotext, parameters, width, height} (an image without infotext has empty ones) or {error}
    """
    try:
        with Image.open(io.BytesIO(file_data)) as image:
            infotext = reader(image) or read_comfy_infotext(image.info or {}) or ""
            width, height = image.size
    except Exception as e:
        return {"error": f"Not an image: {e}"}

    return {
        "infotext": infotext,
        "parameters": parse_infotext(infotext) if infotext.strip() else {},
        "width": width,
        "height": height
    }


def write_infotext(path: str, infotext: str) -> Dict[str, Any]:
    """
    Write the infotext into the "parameters" text chunk of a PNG file (Paste infotext of the image context menu), e.g.
    of an image exported by an editor without it. The other text chunks (the prompt and workflow of ComfyUI), the color
    profile, the resolution and EXIF are kept; the pixels are encoded again losslessly. Chunks are tEXt, as WebUI and
    ComfyUI write them (iTXt for text outside Latin-1). An empty infotext removes the chunk.

    Returns:
        {infotext, parameters}

    Raises:
        ValueError: If the file is not a PNG image
    """
    with open(path, "rb") as f:
        if f.read(len(PNG_SIGNATURE)) != PNG_SIGNATURE:
            raise ValueError("Infotext can be written only into PNG images.")

    infotext = (infotext or "").strip()

    with Image.open(path) as image:
        image.load()
        chunks = PngInfo()

        for key, value in (getattr(image, "text", None) or {}).items():
            if key != "parameters":
                chunks.add_text(key, str(value))

        if infotext:
            chunks.add_text("parameters", infotext)

        options = {"pnginfo": chunks}

        for key in ("icc_profile", "dpi", "exif", "transparency"):
            if image.info.get(key) is not None:
                options[key] = image.info[key]

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", **options)

    replace_file(path, buffer.getvalue())

    return {"infotext": infotext, "parameters": parse_infotext(infotext) if infotext else {}}
