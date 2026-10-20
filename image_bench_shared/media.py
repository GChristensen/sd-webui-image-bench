"""
Video and audio files among the generated images: their kinds, a frame of a video for its thumbnail and the
generation parameters kept in the container metadata.

Frames and metadata are read with PyAV where it is installed (ComfyUI ships it), else with the ffmpeg / ffprobe
binaries (on PATH, as Forge Neo calls them, or of imageio-ffmpeg). Without either a video has no thumbnail and the
popup shows the video itself.

Forge Neo writes the infotext into the "description" tag; ComfyUI's SaveVideo writes the executed prompt into
"prompt" and VideoHelperSuite its metadata as JSON into "comment".
"""

import hashlib
import io
import json
import os
import shutil
import subprocess
from typing import Any, Callable, Dict, Optional

from PIL import Image

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

MEDIA_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
               ".m4v": "video/mp4", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
               ".ogg": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4", ".aac": "audio/aac"}

THUMBS_DIR = "thumbs"
CARD_THUMB_SIZE = 640
TIMEOUT = 20

# The frame of the thumbnail: at a tenth of the video, at most a second in
FRAME_POSITION = 0.1
MAX_FRAME_TIME = 1.0


class MediaError(Exception):
    pass


def media_kind(name: str) -> str:
    """"video", "audio" or "image", by the file extension"""
    ext = os.path.splitext(name or "")[1].lower()
    return "video" if ext in VIDEO_EXTENSIONS else "audio" if ext in AUDIO_EXTENSIONS else "image"


def media_type(name: str) -> Optional[str]:
    return MEDIA_TYPES.get(os.path.splitext(name or "")[1].lower())


def find_binary(name: str) -> Optional[str]:
    path = shutil.which(name)

    if path or name != "ffmpeg":
        return path

    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def run(command, timeout: int = TIMEOUT) -> bytes:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(command, capture_output=True, timeout=timeout, creationflags=flags)

    if result.returncode != 0:
        raise MediaError(result.stderr.decode("utf8", errors="ignore").strip() or "ffmpeg failed")

    return result.stdout


def video_frame(path: str) -> Image.Image:
    """A frame near the start of a video, as an RGB image"""
    try:
        import av
    except ImportError:
        av = None

    if av is not None:
        try:
            with av.open(path) as container:
                stream = container.streams.video[0]
                duration = container.duration / av.time_base if container.duration else 0
                position = min(MAX_FRAME_TIME, duration * FRAME_POSITION)

                if position > 0:
                    container.seek(int(position * av.time_base), any_frame=False)

                for frame in container.decode(stream):
                    return frame.to_image().convert("RGB")
        except Exception as e:
            print(f"[Image Bench] PyAV could not read a frame of {path}: {e}")

    ffmpeg = find_binary("ffmpeg")

    if not ffmpeg:
        raise MediaError("Neither PyAV nor ffmpeg is available")

    for position in (0.5, 0):
        content = run([ffmpeg, "-v", "error", "-ss", str(position), "-i", path, "-frames:v", "1",
                       "-f", "image2pipe", "-vcodec", "png", "-"])

        if content:
            return Image.open(io.BytesIO(content)).convert("RGB")

    raise MediaError("The video has no frames")


def metadata_tags(path: str) -> Dict[str, str]:
    """The container tags of a video or audio file (lowercase keys), empty if they cannot be read"""
    try:
        import av

        with av.open(path) as container:
            return {key.lower(): value for key, value in (container.metadata or {}).items()}
    except ImportError:
        pass
    except Exception:
        return {}

    ffprobe = find_binary("ffprobe")

    if not ffprobe:
        return {}

    try:
        output = run([ffprobe, "-v", "error", "-show_entries", "format_tags", "-of", "json", path])
        tags = (json.loads(output).get("format") or {}).get("tags") or {}
        return {key.lower(): value for key, value in tags.items()}
    except Exception:
        return {}


def read_media_infotext(path: str) -> Optional[str]:
    """Infotext of a video or audio file: the description of Forge Neo, else the ComfyUI prompt turned into one"""
    from .comfy_prompt import read_comfy_infotext

    tags = metadata_tags(path)

    for key in ("description", "parameters"):
        if (tags.get(key) or "").strip():
            return tags[key]

    if tags.get("prompt"):
        return read_comfy_infotext({"prompt": tags["prompt"]})

    # VideoHelperSuite: {"prompt": "...", "workflow": "..."} in the comment
    try:
        comment = json.loads(tags.get("comment") or "")
    except ValueError:
        comment = None

    if isinstance(comment, dict) and comment.get("prompt"):
        prompt = comment["prompt"]
        return read_comfy_infotext({"prompt": prompt if isinstance(prompt, str) else json.dumps(prompt)})

    comment = tags.get("comment") or ""
    return comment if comment.strip() and not comment.strip().startswith("{") else None


def media_info(path: str) -> Dict[str, Any]:
    """{infotext, parameters} of a video or audio file, as pnginfo.image_info() gives them for an image"""
    from .pnginfo import parse_infotext

    infotext = read_media_infotext(path) or ""
    return {"infotext": infotext, "parameters": parse_infotext(infotext) if infotext.strip() else {}}


def thumbnail_jpeg(open_image: Callable[[], Image.Image], size: int) -> bytes:
    """JPEG of an image opened by open_image(), fit into size × size, transparency on the dark background"""
    image = open_image()

    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (22, 25, 29))
        background.paste(image, mask=image.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")

    image.thumbnail((size, size))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=82)
    return buffer.getvalue()


def video_thumbnail(image_bench_dir: str, path: str, size: int = CARD_THUMB_SIZE) -> str:
    """
    Path of the JPEG thumbnail of a video, cached in <image_bench_dir>/thumbs by its path, size and modification
    time; MediaError if no frame can be read
    """
    if media_kind(path) != "video" or not os.path.isfile(path):
        raise MediaError("Not a video file")

    stat = os.stat(path)
    key = f"{os.path.normcase(os.path.abspath(path))}|{stat.st_size}|{stat.st_mtime_ns}|{size}"
    thumb_path = os.path.join(image_bench_dir, THUMBS_DIR, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".jpg")

    if not os.path.isfile(thumb_path):
        content = thumbnail_jpeg(lambda: video_frame(path), size)
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)

        with open(thumb_path, "wb") as file:
            file.write(content)

    return thumb_path
