"""
The GIMP side: pixels of an image and its selection, received images as layers or new images.
GIMP API calls only on the main thread.
"""
import os
import shutil
import tempfile

import gi

gi.require_version("Gimp", "3.0")
gi.require_version("Gegl", "0.4")
from gi.repository import Gegl, Gimp, Gio  # noqa: E402

# babl formats of the uploaded pixels: 8-bit sRGB (perceptual) RGBA and 8-bit gray, whatever the image's mode
IMAGE_FORMAT = "R'G'B'A u8"
MASK_FORMAT = "Y u8"


class DocumentError(Exception):
    pass


def find_image(image_id):
    """The open image with this id, or None"""
    return Gimp.Image.get_by_id(image_id) if image_id is not None else None


def _read_buffer(drawable, width, height, babl_format):
    return bytes(drawable.get_buffer().get(Gegl.Rectangle.new(0, 0, width, height), 1.0, babl_format,
                                           Gegl.AbyssPolicy.NONE))


def read_image(image):
    """
    The visible layers of the image merged on its canvas, converted to 8-bit sRGB whatever its mode
    :return: (data, width, height, 4) with R,G,B,A bytes
    """
    width, height = image.get_width(), image.get_height()
    duplicate = image.duplicate()

    try:
        merged = duplicate.merge_visible_layers(Gimp.MergeType.CLIP_TO_IMAGE)

        if merged is None:
            raise DocumentError("The image has no visible layers")

        return _read_buffer(merged, width, height, IMAGE_FORMAT), width, height, 4
    finally:
        duplicate.delete()


def read_mask(image):
    """
    The selection of the image as a mask (255 is selected)
    :return: (data, width, height, 1)
    """
    if Gimp.Selection.is_empty(image):
        raise DocumentError("There is no selection")

    width, height = image.get_width(), image.get_height()
    return _read_buffer(image.get_selection(), width, height, MASK_FORMAT), width, height, 1


def read_document(image):
    """The image as a layered PSD file, exported from a duplicate, so that the image keeps its file and export state"""
    directory = tempfile.mkdtemp(prefix="image_bench_")
    path = os.path.join(directory, "document.psd")
    duplicate = image.duplicate()

    try:
        if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, duplicate, Gio.File.new_for_path(path), None):
            raise DocumentError("Unable to save the image as PSD")

        with open(path, "rb") as file:
            return file.read()
    except Exception as e:
        if isinstance(e, DocumentError):
            raise

        raise DocumentError(f"Unable to save the image as PSD: {e}") from None
    finally:
        duplicate.delete()
        shutil.rmtree(directory, ignore_errors=True)


class _TempFile:
    """The received data in a temporary file named like the image, which GIMP loads by its path"""

    def __init__(self, data, name):
        self._dir = tempfile.mkdtemp(prefix="image_bench_")
        self.path = os.path.join(self._dir, os.path.basename(name) or "image.png")

        with open(self.path, "wb") as file:
            file.write(data)

    def __enter__(self):
        return Gio.File.new_for_path(self.path)

    def __exit__(self, *_):
        shutil.rmtree(self._dir, ignore_errors=True)


def _with_extension(name):
    return name if os.path.splitext(name)[1] else name + ".png"


def _load_layer(image, data, name):
    """A layer of the image holding the image file, not inserted yet"""
    try:
        with _TempFile(data, _with_extension(name)) as file:
            layer = Gimp.file_load_layer(Gimp.RunMode.NONINTERACTIVE, image, file)
    except Exception as e:
        raise DocumentError(f"Unable to read {name}: {e}") from None

    # GIMP returns None for a file it cannot read
    if layer is None:
        raise DocumentError(f"Unable to read {name}")

    return layer


def place_layer(image, data, name):
    """Place an image file as a new layer above the selected one, centered on the canvas, named after the file"""
    layer = _load_layer(image, data, name)
    image.undo_group_start()

    try:
        layer.set_name(os.path.splitext(name)[0])
        selected = image.get_selected_layers()

        if selected:
            image.insert_layer(layer, selected[0].get_parent(), image.get_item_position(selected[0]))
        else:
            image.insert_layer(layer, None, 0)

        layer.set_offsets((image.get_width() - layer.get_width()) // 2,
                          (image.get_height() - layer.get_height()) // 2)
        image.set_selected_layers([layer])
    finally:
        image.undo_group_end()

    Gimp.displays_flush()


def open_image(data, name):
    """
    Open an image file as a new, unsaved image in its own window; returns the image.
    Not loaded with file_load, which would tie the image to the temporary file as its import source.
    """
    image = Gimp.Image.new(1, 1, Gimp.ImageBaseType.RGB)
    image.undo_disable()

    try:
        layer = _load_layer(image, data, name)
    except DocumentError:
        image.delete()
        raise

    layer.set_name(os.path.splitext(name)[0])
    image.insert_layer(layer, None, 0)
    image.resize(layer.get_width(), layer.get_height(), 0, 0)
    image.undo_enable()
    Gimp.Display.new(image)
    Gimp.displays_flush()
    return image
