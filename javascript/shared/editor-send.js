/**
 * Send an image to the connected editor plugin (Photoshop, Krita) from a host page (SD WebUI or ComfyUI)
 * @param {string} src - Image source (URL, data URL or blob URL)
 * @param {string} name - Layer or document name
 * @param {boolean} newDocument - Open the image as a new document even if there is an active one
 * @returns {Promise<string|null>} Error message, or null on success
 */
export async function sendImageToEditor(src, name, newDocument = false) {
    try {
        const blob = await (await fetch(src)).blob();
        const response = await fetch(`/image-bench/editor/send?name=${encodeURIComponent(name)}`
            + `&new_document=${newDocument}`, {
            method: "POST",
            headers: {"Content-Type": blob.type},
            body: blob
        });

        if (!response.ok)
            return `Unable to send the image: ${await response.text()}`;

        const {clients, editor, error} = await response.json();

        if (!clients)
            return "No editor is connected. Please open the Image Bench panel in Photoshop or the Image Bench docker in Krita.";

        return error ? `${editor}: ${error}` : null;
    } catch (error) {
        return `Unable to send the image: ${error.message}`;
    }
}
