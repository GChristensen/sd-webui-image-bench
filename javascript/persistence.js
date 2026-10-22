/**
 * Persistence of txt2img and img2img prompts and parameters across WebUI reloads
 */

const STORAGE_KEY = "image-bench-generation-params";

// From the scheduling of the restore at page load until it has finished
let restoring = false;

/**
 * Save the current txt2img and img2img prompts and parameters to local storage
 * @param {Object} params - Parameters captured by UIOperations.captureUiParams()
 */
export function saveUiParams(params) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(params));
    } catch (error) {
        console.error('[Image Bench] Failed to save generation parameters:', error);
    }
}

/**
 * Restore txt2img and img2img prompts and parameters from local storage
 * @param {UIOperations} uiOperations
 * @returns {Promise<void>}
 */
export async function restoreUiParams(uiOperations) {
    try {
        const params = JSON.parse(localStorage.getItem(STORAGE_KEY));

        if (params) {
            await uiOperations.applyUiParams(params);
        }
    } catch (error) {
        console.error('[Image Bench] Failed to restore generation parameters:', error);
    }
}

/**
 * Restore the saved prompts and parameters after a delay, which lets Gradio finish initializing its components.
 * Counts as restoring from now on, so the popup shows it while waiting too; nothing happens if nothing is saved
 * @param {UIOperations} uiOperations
 * @param {number} delay - Milliseconds
 */
export function scheduleUiParamsRestore(uiOperations, delay) {
    try {
        if (!localStorage.getItem(STORAGE_KEY))
            return;
    } catch {
        return;
    }

    restoring = true;

    setTimeout(async () => {
        try {
            await restoreUiParams(uiOperations);
        } finally {
            restoring = false;
        }
    }, delay);
}

/**
 * Whether the saved prompts and parameters are being restored at page load
 * @returns {boolean}
 */
export function isRestoringUiParams() {
    return restoring;
}
