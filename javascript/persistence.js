/**
 * Persistence of txt2img and img2img prompts and parameters across WebUI reloads
 */

const STORAGE_KEY = "image-bench-generation-params";

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
