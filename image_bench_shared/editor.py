"""
The bridge to the editor plugins (editor-extensions/: Photoshop, Krita, GIMP), which follow editor-extensions/PROTOCOL.md.
One editor is connected at a time (EditorConnection); the backend never branches on which one it is.
"""
import asyncio
import io
import json
import os
import re
import uuid

from PIL import Image

# Image kinds sent by the editor plugin
EDITOR_IMAGE_KINDS = ("image", "mask")

# Where an image sent by the editor plugin goes, with the image kinds it accepts: the input of the generation
# (img2img or inpaint upload in WebUI, the nodes marked ib:img and ib:mask in ComfyUI) or a ControlNet unit
# (the unit shown in the ControlNet tab; ComfyUI: the node marked ib:cn:<unit>): its image to preprocess,
# its control image used without a preprocessor, or its mask; or the Compare tab, where the backend saves the image
EDITOR_TARGET_KINDS = {
    "input": ("image", "mask"),
    "cn_preprocess": ("image",),
    "cn_image": ("image",),
    "cn_mask": ("mask",),
    "compare": ("image",)
}

# Target of the images added to the Compare tab
COMPARE_TARGET = "compare"

# Key of the image sent from the Image Bench window to the editor plugin
OUTGOING_IMAGE_KIND = "outgoing"

# Image types that the editors are able to place, by their file extensions
SENDABLE_MEDIA_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}

# Seconds to wait for the plugin to report that an image sent to it is opened or placed
PLUGIN_RESULT_TIMEOUT = 60

# PIL modes by the number of 8-bit components per pixel
COMPONENT_MODES = {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}

# Files written to the ComfyUI input directory for the images sent from the editor, by target and image kind
# (named after Photoshop, the first editor, since saved workflows refer to them)
COMFYUI_INPUT_FILES = {
    "input": {"image": "image_bench_photoshop_image.png", "mask": "image_bench_photoshop_mask.png"},
    "cn_preprocess": {"image": "image_bench_photoshop_cn_image.png"},
    "cn_image": {"image": "image_bench_photoshop_cn_image.png"},
    "cn_mask": {"mask": "image_bench_photoshop_cn_mask.png"}
}

# Display name of a plugin whose HELLO does not name its editor (Photoshop plugins before the editor bridge)
DEFAULT_EDITOR_NAME = "Photoshop"

# WebSocket close code of a plugin connection replaced by another one: the plugin does not reconnect on its own,
# so that two running editors do not take the connection from each other in turn
REPLACED_CLOSE_CODE = 4000


class EditorConnection:
    """
    The connected editor plugin: one at a time, a new connection replaces (closes) the previous one.
    The host keeps the socket and passes callables to send and close it, so this works with FastAPI and aiohttp alike.
    """

    def __init__(self):
        self._send = None
        self._close = None
        self._token = None
        # Display name from HELLO, and whether the plugin reports when a sent image is opened (OPEN_IMAGE_DONE)
        self.name = None
        self.acks = False
        # Images sent to the plugin that wait for its result: {request id: future}
        self._pending_sends = {}

    async def attach(self, send_text, close):
        """
        Make a newly connected plugin the editor, closing the previous one
        :param send_text: async callable sending a text message to the plugin
        :param close: async callable closing its socket with a close code (REPLACED_CLOSE_CODE)
        :return: token identifying this connection in handle_message() and detach()
        """
        previous = self._close
        token = object()
        self._send, self._close, self._token = send_text, close, token
        self.name, self.acks = DEFAULT_EDITOR_NAME, False

        if previous:
            try:
                await previous(REPLACED_CLOSE_CODE)
            except Exception:
                pass

        return token

    def detach(self, token):
        """Forget a closed connection, unless it was already replaced"""
        if token is self._token:
            self._send = self._close = self._token = None
            self.name, self.acks = None, False

    def handle_message(self, token, text: str):
        """
        Handle a message of the plugin: HELLO ({editor?, acks?}) names the editor; OPEN_IMAGE_DONE
        ({requestId, error?}) resolves a pending send
        """
        if token is not self._token:
            return

        try:
            msg = json.loads(text)
        except ValueError:
            return

        if msg.get("type") == "HELLO":
            self.name = str(msg.get("editor") or DEFAULT_EDITOR_NAME)
            self.acks = bool(msg.get("acks"))

        elif msg.get("type") == "OPEN_IMAGE_DONE":
            future = self._pending_sends.get(msg.get("requestId"))

            if future and not future.done():
                future.set_result(msg.get("error"))

    def status(self) -> dict:
        return {"editor": self.name}

    async def send_open_image(self, name: str, image_url: str, new_document: bool) -> dict:
        """
        Ask the plugin to open an image (OPEN_IMAGE) and wait for it to report the result
        :return: {"clients": 0|1, "editor": name, plus "done": True, "error": message or "timeout": True}
        """
        if not self._send:
            return {"clients": 0, "editor": None}

        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending_sends[request_id] = future
        editor = self.name

        try:
            await self._send(json.dumps({
                "type": "OPEN_IMAGE",
                "requestId": request_id,
                "name": name,
                "imageUrl": image_url,
                "newDocument": new_document
            }))
        except Exception:
            self._pending_sends.pop(request_id, None)
            return {"clients": 0, "editor": None}

        try:
            if not self.acks:
                return {"clients": 1, "editor": editor, "timeout": True}

            error = await asyncio.wait_for(future, PLUGIN_RESULT_TIMEOUT)
            return {"clients": 1, "editor": editor, **({"error": error} if error else {"done": True})}
        except asyncio.TimeoutError:
            return {"clients": 1, "editor": editor, "timeout": True}
        finally:
            self._pending_sends.pop(request_id, None)


def raw_pixels_to_image(data: bytes, width: int, height: int, components: int) -> Image.Image:
    """
    Decode raw interleaved 8-bit pixel data.

    Args:
        data: Pixel data, row by row, `components` bytes per pixel
        width: Image width in pixels
        height: Image height in pixels
        components: Number of components per pixel (1-4)

    Raises:
        ValueError: If the dimensions do not match the data
    """
    mode = COMPONENT_MODES.get(components)

    if not mode:
        raise ValueError(f"Unsupported number of components: {components}")

    if width <= 0 or height <= 0 or len(data) != width * height * components:
        raise ValueError(f"Pixel data size {len(data)} does not match {width}x{height}x{components}")

    return Image.frombytes(mode, (width, height), data)


def image_to_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


def raw_pixels_to_png(data: bytes, width: int, height: int, components: int) -> bytes:
    """Encode raw interleaved 8-bit pixel data (see raw_pixels_to_image) into a PNG image"""
    return image_to_png(raw_pixels_to_image(data, width, height, components))


def split_project_upload(data: bytes, psd_size: int, width: int = 0, height: int = 0,
                         components: int = 0) -> tuple:
    """
    The parts of a document saved into the current project (/image-bench/editor/project, Keep › File / Final):
    the body is the PSD file, followed by the raw pixels of the merged document for Final

    Returns:
        (PSD bytes, merged image or None without pixels)

    Raises:
        ValueError: If the sizes do not match the data
    """
    if not 0 < psd_size <= len(data):
        raise ValueError(f"PSD size {psd_size} does not match the data size {len(data)}")

    psd, pixels = data[:psd_size], data[psd_size:]
    return psd, raw_pixels_to_image(pixels, width, height, components) if pixels else None


def mask_to_png(mask: Image.Image) -> bytes:
    """
    Encode a mask (white is masked) into an RGBA PNG image readable as a mask by any ComfyUI loader:
    the color channels hold the mask and the alpha channel holds its inverse, since LoadImage and the alpha channel
    of LoadImageMask take the mask as 1 - alpha
    """
    mask = mask.convert("L")
    image = Image.merge("RGBA", (mask, mask, mask, mask.point(lambda value: 255 - value)))
    return image_to_png(image)


def raw_mask_to_png(data: bytes, width: int, height: int, components: int) -> bytes:
    """Encode a raw selection mask (white is selected) into a mask PNG image (see mask_to_png)"""
    return mask_to_png(raw_pixels_to_image(data, width, height, components))


def image_file_to_mask_png(data: bytes) -> bytes:
    """
    Encode a mask image file into a mask PNG image (see mask_to_png): an image with transparency is masked
    where it is transparent (as the ComfyUI mask editor saves masks), any other image where it is white
    """
    image = Image.open(io.BytesIO(data))

    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        alpha = image.convert("RGBA").getchannel("A")

        if alpha.getextrema()[0] < 255:
            return mask_to_png(alpha.point(lambda value: 255 - value))

    return mask_to_png(image.convert("L"))


def get_image_file_name(name: str, media_type: str) -> str:
    """
    Make a safe file name for an image sent to the editor, with the extension matching its type.
    The editor names the placed layer after the file.
    """
    stem = os.path.splitext(os.path.basename(name.replace("\\", "/")))[0]
    stem = re.sub(r'[<>:"/\|?*\x00-\x1f]', "_", stem).strip(" .") or "image"
    return stem[:100] + SENDABLE_MEDIA_TYPES[media_type]
