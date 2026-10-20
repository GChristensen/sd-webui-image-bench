"""
The Krita side: pixels of the active document and its selection, received images as layers or documents
"""
import os
import shutil
import tempfile

from krita import InfoObject, Krita
from PyQt5.QtGui import QImage

# The color space of the pixel data exchanged with setPixelData: 8-bit RGBA, stored as B,G,R,A
TRANSFER_MODEL, TRANSFER_DEPTH, TRANSFER_PROFILE = "RGBA", "U8", "sRGB-elle-V2-srgbtrc.icc"


class DocumentError(Exception):
    pass


def active_document():
    doc = Krita.instance().activeDocument()

    if doc is None:
        raise DocumentError("No document is open")

    return doc


def _image_bytes(image):
    """Bytes of a QImage in a format without row padding"""
    pointer = image.constBits()
    pointer.setsize(image.sizeInBytes() if hasattr(image, "sizeInBytes") else image.byteCount())
    return bytes(pointer)


def read_image(doc):
    """
    The merged image of the document, converted to 8-bit sRGB whatever its color space
    :return: (data, width, height, 4) with R,G,B,A bytes
    """
    width, height = doc.width(), doc.height()
    image = doc.projection(0, 0, width, height).convertToFormat(QImage.Format_RGBA8888)
    return _image_bytes(image), width, height, 4


def read_mask(doc):
    """
    The selection of the document as a mask (255 is selected)
    :return: (data, width, height, 1)
    """
    selection = doc.selection()

    if selection is None:
        raise DocumentError("There is no selection")

    width, height = doc.width(), doc.height()
    return bytes(selection.pixelData(0, 0, width, height)), width, height, 1


def read_document(doc):
    """The document as a layered PSD file, exported without dialogs; the document keeps its file name"""
    directory = tempfile.mkdtemp(prefix="image_bench_")
    path = os.path.join(directory, "document.psd")
    batch = doc.batchmode()
    doc.setBatchmode(True)

    try:
        if not doc.exportImage(path, InfoObject()):
            raise DocumentError("Unable to save the document as PSD")

        with open(path, "rb") as file:
            return file.read()
    except OSError as e:
        raise DocumentError(f"Unable to save the document as PSD: {e}") from None
    finally:
        doc.setBatchmode(batch)
        shutil.rmtree(directory, ignore_errors=True)


def _decode(data, name):
    image = QImage.fromData(data)

    if image.isNull():
        raise DocumentError(f"Unable to read {name}")

    # B,G,R,A bytes on little-endian machines, the layout of 8-bit RGBA layers
    return image.convertToFormat(QImage.Format_ARGB32)


def _add_layer(doc, image, name, above=None):
    """Add a paint layer holding the image, centered on the canvas, above the given node (or on top)"""
    node = doc.createNode(name, "paintlayer")

    # Masks are children of layers, which hold no layers
    while above is not None and above.type().endswith("mask"):
        above = above.parentNode()

    if above is not None and above.parentNode() is not None:
        above.parentNode().addChildNode(node, above)
    else:
        doc.rootNode().addChildNode(node, None)

    color_space = (doc.colorModel(), doc.colorDepth(), doc.colorProfile())
    converted = color_space[:2] != (TRANSFER_MODEL, TRANSFER_DEPTH)

    if converted:
        node.setColorSpace(TRANSFER_MODEL, TRANSFER_DEPTH, TRANSFER_PROFILE)

    width, height = image.width(), image.height()
    node.setPixelData(_image_bytes(image), (doc.width() - width) // 2, (doc.height() - height) // 2, width, height)

    if converted:
        node.setColorSpace(*color_space)

    return node


def place_layer(doc, data, name):
    """Place an image file as a new layer above the active one, named after the file"""
    node = _add_layer(doc, _decode(data, name), name, doc.activeNode())
    doc.setActiveNode(node)
    doc.refreshProjection()


def open_document(data, name):
    """Open an image file as a new, unsaved document"""
    image = _decode(data, name)
    app = Krita.instance()
    doc = app.createDocument(image.width(), image.height(), name, TRANSFER_MODEL, TRANSFER_DEPTH, TRANSFER_PROFILE,
                             300.0)
    initial_layers = doc.topLevelNodes()
    node = _add_layer(doc, image, name)

    for layer in initial_layers:
        layer.remove()

    doc.setActiveNode(node)
    doc.refreshProjection()

    window = app.activeWindow()

    if window is not None:
        window.addView(doc)
