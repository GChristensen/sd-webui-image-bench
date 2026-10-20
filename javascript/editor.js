/**
 * Receives images sent by the editor plugin (Photoshop, Krita) and passes them to core.js, which puts them
 * into img2img (the inpaint upload by default) or a ControlNet unit. The connection is kept regardless of the popup state.
 */

import {createWebSocket} from "./shared/websocket.js";
import {sendImageToEditor} from "./shared/editor-send.js";

const ENDPOINT = '/image-bench/editor/host-websocket';
const RECONNECT_DELAY = 5000;

/**
 * Connect to the backend and keep reconnecting if the connection is lost (e.g. WebUI restarts)
 * @param {(kind: 'image'|'mask', file: File, target: string) => Promise<void>} onImage - Inserts a received image;
 *   target: 'input' (img2img) or a ControlNet target ('cn_preprocess', 'cn_image', 'cn_mask')
 * @param {(image: Object) => void} onCompareImage - Receives the image data of an image the backend has added
 *   to the Compare tab (target 'compare')
 */
export function initEditorBridge(onImage, onCompareImage) {
    createWebSocket({
        endpoint: ENDPOINT,
        onMessage: (e) => onEditorMessage(onImage, onCompareImage, e),
        onClose: () => setTimeout(() => initEditorBridge(onImage, onCompareImage), RECONNECT_DELAY)
    });
}

/**
 * Add an "Editor" link next to Download/Close under ControlNet preprocessor previews, which sends
 * the preview to the connected editor as a new document. The preview elements have random uuid ids, so they are
 * located by class; the observer covers units that Gradio renders later.
 * @param {(message: string) => void} showAlert - Shows errors in the popup or in the WebUI window
 */
export function initControlNetPreviewButtons(showAlert) {
    let scheduled = false;

    const addButtons = () => {
        scheduled = false;

        for (const closeBlock of document.querySelectorAll(
                ".cnet-generated-image-control-group > * > .cnet-close-preview:not([data-image-bench])")) {
            closeBlock.dataset.imageBench = "";
            closeBlock.before(createSendBlock(closeBlock, showAlert));
        }
    };

    addButtons();

    new MutationObserver(() => {
        if (!scheduled) {
            scheduled = true;
            requestAnimationFrame(addButtons);
        }
    }).observe(document.body, {childList: true, subtree: true});
}

/**
 * Clone the Close block. ControlNet styles the links by class, cnet-download-preview keeps the style
 * without matching the Close selector above.
 */
function createSendBlock(closeBlock, showAlert) {
    const block = closeBlock.cloneNode(true);
    block.removeAttribute("id");
    delete block.dataset.imageBench;

    for (const element of [block, ...block.querySelectorAll(".cnet-close-preview")]) {
        element.classList.replace("cnet-close-preview", "cnet-download-preview");
        element.classList.add("image-bench-send-preview");
    }

    const link = block.querySelector("a");
    link.removeAttribute("onclick");
    link.title = "Send to the connected editor (Photoshop, Krita) as a new document";
    link.textContent = "Editor";
    link.addEventListener("click", () => sendControlNetPreview(link, showAlert));

    return block;
}

async function sendControlNetPreview(link, showAlert) {
    const container = link.closest(".cnet-generated-image-group")
        ?.querySelector("[id$='_generated_image']");
    const image = container?.querySelector("img.forge-image");

    if (!image?.getAttribute("src") || !image.complete || image.naturalWidth === 0)
        return;

    // txt2img_controlnet_ControlNet-0_generated_image -> txt2img ControlNet-0 preview
    const unit = container.id.replace(/_generated_image$/, "").replace("_controlnet_", " ");
    const error = await sendImageToEditor(image.src, `${unit} preview`, true);

    if (error)
        showAlert(error);
}

async function onEditorMessage(onImage, onCompareImage, e) {
    const msg = JSON.parse(e.data);

    if (msg.type !== "EDITOR_IMAGE")
        return;

    if (msg.target === "compare") {
        onCompareImage(msg.image);
        return;
    }

    try {
        const response = await fetch(msg.imageUrl);

        if (!response.ok)
            throw new Error(`HTTP ${response.status}`);

        const file = new File([await response.blob()], `editor-${msg.kind}.png`, {type: "image/png"});
        await onImage(msg.kind, file, msg.target ?? "input");
    } catch (error) {
        console.error(`[Image Bench] Unable to insert ${msg.kind} from the editor:`, error);
    }
}
