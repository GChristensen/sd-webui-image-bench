    /**
 * DOMAdapter Interface
 * Abstract interface for DOM manipulation operations
 * Implementations should be specific to each extension platform (SD WebUI, ComfyUI, etc.)
 */

export class DOMAdapter {
    /**
     * Get the value of an input element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {string|number|null} The input value
     */
    getInputValue(selectorKey) {
        throw new Error('getInputValue must be implemented');
    }

    /**
     * Set the value of an input element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {string|number} value - The value to set
     * @param {boolean} triggerEvents - Whether to trigger input/blur events
     */
    setInputValue(selectorKey, value, triggerEvents = true) {
        throw new Error('setInputValue must be implemented');
    }

    /**
     * Set the value of a checkbox element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {boolean} checked - Whether to check or uncheck
     */
    setCheckboxValue(selectorKey, checked) {
        throw new Error('setCheckboxValue must be implemented');
    }

    /**
     * Set the value of a dropdown element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {string} value - The value to select
     * @returns {Promise<void>}
     */
    async setDropdownValue(selectorKey, value) {
        throw new Error('setDropdownValue must be implemented');
    }

    /**
     * Click a button element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {boolean} Whether the button was clicked
     */
    clickButton(selectorKey) {
        throw new Error('clickButton must be implemented');
    }

    /**
     * Check if an element is visible
     * @param {HTMLElement} element - The element to check
     * @returns {boolean}
     */
    isElementVisible(element) {
        throw new Error('isElementVisible must be implemented');
    }

    /**
     * Get element by selector key
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {HTMLElement|null}
     */
    getElement(selectorKey) {
        throw new Error('getElement must be implemented');
    }

    /**
     * Get all elements matching selector key
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {NodeList|Array}
     */
    getAllElements(selectorKey) {
        throw new Error('getAllElements must be implemented');
    }

    /**
     * Toggle hires fix checkbox
     * @param {boolean} onlyEnable - Only enable, don't toggle off
     * @param {boolean} onlyDisable - Only disable, don't toggle on
     */
    toggleHiresFix(onlyEnable = false, onlyDisable = false) {
        throw new Error('toggleHiresFix must be implemented');
    }

    /**
     * Check if currently on img2img tab
     * @returns {boolean}
     */
    isImg2ImgTab() {
        throw new Error('isImg2ImgTab must be implemented');
    }

    /**
     * Switch to the inpaint upload tab of img2img
     */
    switchToInpaintUploadTab() {
        throw new Error('switchToInpaintUploadTab must be implemented');
    }

    /**
     * Put a file into an image component, replacing its current image
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {File} file - Image file
     * @returns {boolean} Whether the image component was found
     */
    setImageFile(selectorKey, file) {
        throw new Error('setImageFile must be implemented');
    }

    /**
     * Get current generation progress percentage
     * @returns {number|null} Progress from 0-100, or null if not available
     */
    getGenerationProgress() {
        throw new Error('getGenerationProgress must be implemented');
    }

    /**
     * Dispatch a mouse event on an element
     * @param {HTMLElement} element - Target element
     * @param {string} eventType - Event type (e.g., 'mousedown', 'click')
     */
    dispatchMouseEvent(element, eventType) {
        throw new Error('dispatchMouseEvent must be implemented');
    }

    /**
     * Sleep/wait for specified milliseconds
     * @param {number} ms - Milliseconds to wait
     * @returns {Promise<void>}
     */
    async sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    /**
     * Poll a condition
     * @param {() => any} condition
     * @param {number} timeout - Milliseconds
     * @returns {Promise<any>} The value of the condition once truthy, false if it did not become truthy in time
     */
    async waitFor(condition, timeout) {
        const deadline = Date.now() + timeout;
        let value;

        while (!(value = condition())) {
            if (Date.now() >= deadline)
                return false;

            await this.sleep(100);
        }

        return value;
    }
}
