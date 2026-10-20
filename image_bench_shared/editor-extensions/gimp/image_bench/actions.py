"""
The send actions of the Tools › Image Bench menu and of the panel. Each one is split in two steps: read_pixels() calls the
GIMP API, so it runs on the main thread; upload() only talks to the server, so the panel runs it in a thread.
"""
import document

# (id, menu text, panel button text, uploads as (kind, target) in their order, result text),
# in the order of the panel groups. Kind "document" saves the image as PSD into the current project of Image Bench,
# target "file" or "final" (with the merged image); the server names the files and the result text
SEND_ACTIONS = [
    ("send_image", "Send _Image", "Image", (("image", "input"),), "Image sent to the input image"),
    ("send_mask", "Send _Mask", "Mask", (("mask", "input"),), "Mask sent to the input mask"),
    ("send_image_and_mask", "Send Image _and Mask", "Image + Mask", (("image", "input"), ("mask", "input")),
     "Image and mask sent to the input"),
    ("send_cn_preprocess", "Send to ControlNet _Preprocessor", "Preprocess", (("image", "cn_preprocess"),),
     "Image sent to the ControlNet preprocessor"),
    ("send_cn_image", "Send ControlNet Imag_e", "Image", (("image", "cn_image"),),
     "Image sent as the ControlNet control image"),
    ("send_cn_mask", "Send ControlNet Mas_k", "Mask", (("mask", "cn_mask"),), "Mask sent to ControlNet"),
    ("send_compare", "Send to _Compare", "Compare", (("image", "compare"),), "Image added to the Compare tab"),
    ("save_file", "Save to Project as _File", "File", (("document", "file"),),
     "Image saved as <project>-NNN.psd in the current project"),
    ("save_final", "Save to Project as F_inal", "Final", (("document", "final"),),
     "Image saved as final PSD, PNG and JPEG in the current project, the project's final image"),
]

ACTIONS = {action[0]: action for action in SEND_ACTIONS}

READERS = {"image": document.read_image, "mask": document.read_mask, "document": document.read_document}


def read_pixels(action_id, image):
    """
    The pixels of each upload of the action
    :raises document.DocumentError: if the image has no selection for a mask, or nothing visible
    """
    uploads = ACTIONS[action_id][3]
    # The selection is read first, so nothing is sent if there is no selection
    kinds = sorted({kind for kind, _ in uploads}, key=lambda kind: kind != "mask")
    pixels = {kind: READERS[kind](image) for kind in kinds}
    return [(kind, (pixels[kind], document.read_image(image)) if target == "final" else pixels[kind], target)
            for kind, target in uploads]


def upload(client, action_id, reads):
    """
    Upload what read_pixels() returned; returns the result text
    :raises client.ClientError: if the server is not reached or no host page is open
    """
    result = ACTIONS[action_id][4]

    for kind, pixels, target in reads:
        if kind == "document":
            psd, merged = pixels if target == "final" else (pixels, None)
            saved = client.save_document(target, psd, merged)
            result = f"Saved {', '.join(saved['files'])} in {saved['project']}"
        else:
            client.upload(kind, pixels, target)

    return result
