/**
 * SDWebuiAdapter
 * SD WebUI/Forge-specific implementation of DOMAdapter
 */

import { DOMAdapter } from './DOMAdapter.js';
import { SELECTORS, getElementById, querySelector, querySelectorAll } from './selectors.js';

export class SDWebuiAdapter extends DOMAdapter {
    /**
     * Get the value of an input element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {string|number|null} The input value
     */
    getInputValue(selectorKey) {
        const selector = SELECTORS[selectorKey];
        const element = document.querySelector(selector);
        return element?.value ?? null;
    }

    /**
     * Set the value of an input element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {string|number} value - The value to set
     * @param {boolean} triggerEvents - Whether to trigger input/blur events
     */
    setInputValue(selectorKey, value, triggerEvents = true) {
        const selector = SELECTORS[selectorKey];
        const element = document.querySelector(selector);

        if (!element) {
            console.log(`Input element ${selector} not found.`);
            return;
        }

        this.setInputElementValue(element, value, triggerEvents);
    }

    /**
     * Set the value of an input element given by itself
     * @param {HTMLInputElement} element
     * @param {string|number} value
     * @param {boolean} triggerEvents - Whether to trigger input/blur events
     */
    setInputElementValue(element, value, triggerEvents = true) {
        element.value = value;

        if (triggerEvents) {
            const inputEvent = new Event('input', { bubbles: true, cancelable: true });
            element.dispatchEvent(inputEvent);

            const blurEvent = new Event('blur', { bubbles: true, cancelable: true });
            element.dispatchEvent(blurEvent);
        }
    }

    /**
     * Check or uncheck the checkbox of a Gradio checkbox component by clicking it, as the user does
     * @param {HTMLElement|null} container - The checkbox component
     * @param {boolean} checked
     * @returns {boolean} Whether the checkbox was clicked
     */
    setCheckedIn(container, checked) {
        const checkbox = container?.querySelector(SELECTORS.CHECKBOX_INPUT);

        if (!checkbox || checkbox.checked === checked)
            return false;

        checkbox.click();
        return true;
    }

    /**
     * @param {HTMLElement|null} container - A Gradio checkbox component
     * @returns {boolean|null} Whether it is checked, null if it is absent
     */
    isCheckedIn(container) {
        return container?.querySelector(SELECTORS.CHECKBOX_INPUT)?.checked ?? null;
    }

    /**
     * Set the value of a checkbox element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {boolean} checked - Whether to check or uncheck
     */
    setCheckboxValue(selectorKey, checked) {
        const selector = SELECTORS[selectorKey];
        const element = document.querySelector(selector);
        
        if (!element) {
            console.log(`Checkbox element ${selector} not found.`);
            return;
        }

        if (element.checked !== checked) {
            const inputEvent = new Event('input', { bubbles: true, cancelable: true });
            element.dispatchEvent(inputEvent);

            const changeEvent = new Event('change', { bubbles: true, cancelable: true });
            element.dispatchEvent(changeEvent);

            const clickEvent = new MouseEvent('click', {
                view: window,
                bubbles: true,
                cancelable: true,
                buttons: 1
            });

            element.dispatchEvent(clickEvent);
        }
    }

    /**
     * Set the value of a dropdown element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {string} value - The value to select
     * @param {boolean} exact - Match the current value and options exactly instead of by substring
     * @returns {Promise<void>}
     */
    async setDropdownValue(selectorKey, value, exact = false) {
        const selector = SELECTORS[selectorKey];
        const element = document.querySelector(selector);

        if (!element) {
            console.log(`Dropdown element ${selector} not found.`);
            return;
        }

        await this.setDropdownElementValue(element, value, exact);
    }

    /**
     * Set the value of a dropdown given by its input element
     * @param {HTMLInputElement} element
     * @param {string} value - The value to select; options may have it with or without a model hash
     * @param {boolean} exact - Match the current value and options exactly instead of by substring
     * @returns {Promise<void>}
     */
    async setDropdownElementValue(element, value, exact = false) {
        if (exact ? element.value === value : element.value.includes(value)) {
            return;
        }

        // A dropdown in a collapsed accordion (e.g. Hires. fix) cannot be focused, so its option list never opens
        const opened = element.getClientRects().length ? [] : this.openEnclosingAccordions(element);

        if (opened.length) {
            await this.sleep(100);
        }

        try {
            await this.selectDropdownOption(element, value, exact);
        } finally {
            if (opened.length) {
                // Let Gradio take the chosen option before the accordion is collapsed again
                await this.sleep(100);
                opened.reverse().forEach(labelWrap => labelWrap.click());
            }
        }
    }

    /**
     * Expand the collapsed accordions that hide an element.
     * Expanding the InputAccordion of Hires. fix also checks it while it is linked to its checkbox;
     * collapsing it again unchecks it, so the state is kept
     * @param {HTMLElement} element
     * @returns {HTMLElement[]} Headers of the expanded accordions, innermost first, to collapse them again
     */
    openEnclosingAccordions(element) {
        const opened = [];

        for (let node = element.parentElement; node; node = node.parentElement) {
            const labelWrap = Array.from(node.children).find(child =>
                child.matches(SELECTORS.ACCORDION_LABEL_WRAP) && !child.contains(element));

            if (labelWrap && !labelWrap.classList.contains(SELECTORS.ACCORDION_OPEN_CLASS)) {
                labelWrap.click();
                opened.push(labelWrap);
            }
        }

        return opened;
    }

    /**
     * Open the option list of a dropdown and choose the option of a value
     * @param {HTMLInputElement} element
     * @param {string} value
     * @param {boolean} exact
     * @returns {Promise<void>}
     */
    async selectDropdownOption(element, value, exact) {
        element.value = value;

        const focusEvent = new Event('focus', { bubbles: true, cancelable: true });
        element.dispatchEvent(focusEvent);
        element.focus();

        await this.sleep(333);

        const optionList = element.closest(SELECTORS.DROPDOWN_BLOCK)?.querySelector(SELECTORS.DROPDOWN_LIST);

        if (optionList) {
            // Strip hash from model names
            const name = value.replace(/ \[[^\]]+\]$/, '');

            const options = Array.from(optionList.querySelectorAll(SELECTORS.DROPDOWN_OPTION));

            for (const optionElement of options) {
                const optionName = optionElement.getAttribute('data-value')
                    || optionElement.getAttribute('aria-label');

                if (exact ? optionName === value || optionName === name : optionName?.includes(name)) {
                    const mousedownEvent = new MouseEvent('mousedown', {
                        bubbles: true,
                        cancelable: true,
                        view: window,
                        button: 0
                    });

                    optionElement.dispatchEvent(mousedownEvent);
                    return;
                }
            }
        }
    }

    /**
     * Chosen values of a Gradio multiselect dropdown
     * @param {string} elemId - Element id of the dropdown block
     * @returns {string[]|null} Null if the dropdown is absent
     */
    getMultiselectValues(elemId) {
        const block = getElementById(elemId);

        if (!block)
            return null;

        return Array.from(block.querySelectorAll(SELECTORS.MULTISELECT_TOKEN))
            .map(token => token.querySelector('span')?.textContent.trim())
            .filter(Boolean);
    }

    /**
     * Choose exactly the given values in a Gradio multiselect dropdown, as the user does: the remove buttons
     * of the other tokens are clicked, then the missing options. A value matches an option with or without
     * its file extension (infotext names modules without it). Nothing changes if a value has no option
     * @param {string} elemId - Element id of the dropdown block
     * @param {string[]} values
     * @returns {Promise<boolean>} Whether all values are chosen
     */
    async setMultiselectValues(elemId, values) {
        const block = getElementById(elemId);
        const input = block?.querySelector(SELECTORS.DROPDOWN_INPUT);

        if (!input)
            return false;

        // Only model file extensions: names like qwen_2.5_vl have dots
        const matches = (option, value) => option === value || option.replace(/\.(safetensors|sft|gguf|ckpt|pt|pth|bin)$/i, '') === value;
        const missing = () => {
            const current = this.getMultiselectValues(elemId);
            return values.filter(value => !current.some(option => matches(option, value)));
        };

        const listOptions = () =>
            Array.from(block.querySelector(SELECTORS.DROPDOWN_LIST)?.querySelectorAll(SELECTORS.DROPDOWN_OPTION) ?? []);

        // The options are listed only while the input is focused
        const openOptions = async () => {
            input.dispatchEvent(new Event('focus', {bubbles: true, cancelable: true}));
            input.focus();
            await this.sleep(200);
            return listOptions();
        };
        const optionName = option => option.getAttribute('data-value') || option.getAttribute('aria-label') || '';

        if (missing().length) {
            const options = await openOptions();
            input.blur();

            if (!missing().every(value => options.some(option => matches(optionName(option), value)))) {
                console.log(`Some of ${values.join(', ')} are not available in ${elemId}.`);
                return false;
            }
        }

        for (const token of Array.from(block.querySelectorAll(SELECTORS.MULTISELECT_TOKEN))) {
            const name = token.querySelector('span')?.textContent.trim() ?? '';

            if (!values.some(value => matches(name, value))) {
                token.querySelector(SELECTORS.MULTISELECT_TOKEN_REMOVE)?.click();
                await this.sleep(50);
            }
        }

        const toAdd = missing();

        if (toAdd.length) {
            await openOptions();

            // The list is rendered again after each choice
            for (const value of toAdd) {
                const option = listOptions().find(option => matches(optionName(option), value));

                option?.dispatchEvent(new MouseEvent('mousedown', {bubbles: true, cancelable: true, view: window, button: 0}));
                await this.sleep(50);
            }

            input.blur();
        }

        return !missing().length;
    }

    /**
     * Click a button element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {boolean} Whether the button was clicked
     */
    clickButton(selectorKey) {
        const element = this.getElement(selectorKey);
        
        if (element && this.isElementVisible(element)) {
            element.click();
            return true;
        }
        
        return false;
    }

    /**
     * Check if an element is visible
     * @param {HTMLElement} element - The element to check
     * @returns {boolean}
     */
    isElementVisible(element) {
        return element?.style?.display !== 'none';
    }

    /**
     * Get element by selector key
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {HTMLElement|null}
     */
    getElement(selectorKey) {
        const selector = SELECTORS[selectorKey];
        
        // Handle both ID selectors (no #) and CSS selectors (with #)
        if (typeof selector === 'string' && !selector.startsWith('#') && !selector.startsWith('.')) {
            return getElementById(selector);
        }
        
        return querySelector(selector);
    }

    /**
     * Get all elements matching selector key
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {NodeList|Array}
     */
    getAllElements(selectorKey) {
        const selector = SELECTORS[selectorKey];
        return querySelectorAll(selector);
    }

    /**
     * Toggle hires fix checkbox
     * @param {boolean} onlyEnable - Only enable, don't toggle off
     * @param {boolean} onlyDisable - Only disable, don't toggle on
     */
    toggleHiresFix(onlyEnable = false, onlyDisable = false) {
        const hrFixCheckbox = getElementById(SELECTORS.HIRES_CHECKBOX);
        
        if (!hrFixCheckbox) {
            return;
        }
        
        let toggle = true;

        if (onlyEnable) {
            toggle = !hrFixCheckbox.checked;
        }

        if (onlyDisable) {
            toggle = hrFixCheckbox.checked;
        }

        if (toggle) {
            const inputEvent = new Event('input', {
                bubbles: true,
                cancelable: true
            });

            const clickEvent = new MouseEvent('click', {
                view: window,
                bubbles: true,
                cancelable: true,
                buttons: 1
            });

            hrFixCheckbox.dispatchEvent(clickEvent);
            hrFixCheckbox.dispatchEvent(inputEvent);
        }
    }

    /**
     * Check if currently on img2img tab
     * @returns {boolean}
     */
    isImg2ImgTab() {
        const txt2ImgButton = getElementById(SELECTORS.TXT2IMG_GENERATE);
        return txt2ImgButton?.offsetParent === null;
    }

    /**
     * Switch to the inpaint upload tab of img2img using the WebUI's own tab switcher
     */
    switchToInpaintUploadTab() {
        // Inpaint upload is the fifth tab: img2img, Sketch, Inpaint, Inpaint sketch, Inpaint upload
        this.switchToImg2ImgModeTab(SELECTORS.IMG2IMG_INPAINT_UPLOAD_TAB, 4);
    }

    /**
     * Switch to a mode tab of img2img (img2img, Sketch, Inpaint, ...) using the WebUI's own tab switcher
     * @param {string} tabId - Element id of the tab
     * @param {number} fallbackIndex - Index of the tab if it is not found
     */
    switchToImg2ImgModeTab(tabId, fallbackIndex) {
        const index = this.getImg2ImgModeTabs().findIndex(tab => tab.id === tabId);
        window.switch_to_img2img_tab?.(index >= 0 ? index : fallbackIndex);
    }

    /**
     * Element id of the selected img2img mode tab, also while the img2img tab itself is hidden
     * @returns {string|null}
     */
    getImg2ImgModeTab() {
        return this.getImg2ImgModeTabs().find(tab => tab.style.display !== 'none')?.id ?? null;
    }

    getImg2ImgModeTabs() {
        const modeTabs = getElementById(SELECTORS.IMG2IMG_MODE_TABS);
        return Array.from(modeTabs?.querySelectorAll(':scope > .tabitem') ?? []);
    }

    /**
     * Select the first tab of a Gradio tab set (e.g. "Resize to" of the img2img size) if it is not selected
     * @param {string} selectorKey - Key of the tab set element id
     */
    selectFirstTab(selectorKey) {
        this.selectTabIn(this.getElement(selectorKey), 0);
    }

    /**
     * Select a tab of a Gradio tab set by its index if it is not selected
     * @param {HTMLElement|null} tabs - The tab set element
     * @param {number} index
     */
    selectTabIn(tabs, index) {
        const button = tabs?.querySelectorAll(SELECTORS.TAB_BUTTONS)[index];

        if (button && !button.classList.contains('selected'))
            button.click();
    }

    /**
     * @param {HTMLElement|null} tabs - A Gradio tab set element
     * @returns {number} Number of its tabs
     */
    getTabCountIn(tabs) {
        return tabs?.querySelectorAll(SELECTORS.TAB_BUTTONS).length ?? 0;
    }

    /**
     * Label of the checked choice of a Gradio radio group
     * @param {string} selectorKey - Key of the radio group element id
     * @returns {string|null}
     */
    getRadioValue(selectorKey) {
        return this.getRadioValueIn(this.getElement(selectorKey));
    }

    /**
     * Choice labels of a Gradio radio group
     * @param {string} selectorKey - Key of the radio group element id
     * @returns {string[]}
     */
    getRadioChoices(selectorKey) {
        return this.getRadioChoicesIn(this.getElement(selectorKey));
    }

    /**
     * Check a choice of a Gradio radio group by its label
     * @param {string} selectorKey - Key of the radio group element id
     * @param {string} value - Choice label
     */
    setRadioValue(selectorKey, value) {
        this.setRadioValueIn(this.getElement(selectorKey), value);
    }

    /**
     * @param {HTMLElement|null} group - A Gradio radio group
     * @returns {string|null} Label of its checked choice
     */
    getRadioValueIn(group) {
        return group?.querySelector('input[type="radio"]:checked')?.value ?? null;
    }

    /**
     * @param {HTMLElement|null} group - A Gradio radio group
     * @returns {string[]} Its choice labels
     */
    getRadioChoicesIn(group) {
        return Array.from(group?.querySelectorAll('input[type="radio"]') ?? []).map(input => input.value);
    }

    /**
     * @param {HTMLElement|null} group - A Gradio radio group
     * @param {string} value - Choice label to check
     */
    setRadioValueIn(group, value) {
        const input = Array.from(group?.querySelectorAll('input[type="radio"]') ?? [])
            .find(input => input.value === value);

        if (input && !input.checked)
            input.click();
    }

    /**
     * Load a file into a Forge canvas (the img2img image) through its own file input
     * @param {string} selectorKey - Key of the canvas file input
     * @param {File} file - Image file
     * @returns {boolean} Whether the canvas was found
     */
    setCanvasFile(selectorKey, file) {
        return this.setCanvasFileIn(this.getElement(selectorKey), file);
    }

    /**
     * Load a file into a Forge canvas through its file input given by itself
     * @param {HTMLInputElement|null} fileInput
     * @param {File} file - Image file
     * @returns {boolean} Whether the file input was found
     */
    setCanvasFileIn(fileInput, file) {
        if (!fileInput)
            return false;

        const files = new DataTransfer();
        files.items.add(file);
        fileInput.files = files.files;
        fileInput.dispatchEvent(new Event('change'));
        return true;
    }

    /**
     * Source of a shown image, null if there is none (a hidden image keeps its last or an empty source)
     * @param {string} selectorKey - Key of the image element
     * @returns {string|null}
     */
    getImageSource(selectorKey) {
        return this.getImageSourceOf(this.getElement(selectorKey));
    }

    /**
     * @param {HTMLImageElement|null} image
     * @returns {string|null} Its source if it is shown, else null
     */
    getImageSourceOf(image) {
        const source = image?.getAttribute('src');

        return source && image.style.display !== 'none' ? image.src : null;
    }

    /**
     * Put a file into an image component, replacing its current image
     * Reuses the WebUI's drag-and-drop handler, which clears the existing image first
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {File} file - Image file
     * @returns {boolean} Whether the image component was found
     */
    setImageFile(selectorKey, file) {
        const container = this.getElement(selectorKey);

        if (!container) {
            console.log(`Image component ${SELECTORS[selectorKey]} not found.`);
            return false;
        }

        return this.setImageFileIn(container, file);
    }

    /**
     * Put a file into an image component given by its element, replacing its current image
     * @param {HTMLElement} container - The image component or its block
     * @param {File} file - Image file
     * @returns {boolean} Whether the file input was found
     */
    setImageFileIn(container, file) {
        const files = new DataTransfer();
        files.items.add(file);

        if (typeof window.dropReplaceImage === 'function') {
            window.dropReplaceImage(container.querySelector(SELECTORS.IMAGE_COMPONENT) ?? container, files.files);
        }
        else {
            const fileInput = container.querySelector(SELECTORS.FILE_INPUT);

            if (!fileInput)
                return false;

            fileInput.files = files.files;
            fileInput.dispatchEvent(new Event('change'));
        }

        return true;
    }

    /**
     * Get current generation progress percentage
     * @returns {number|null} Progress from 0-100, or null if not available
     */
    getGenerationProgress() {
        const progressBar = querySelector(SELECTORS.PROGRESS_BAR);
        const progressBarText = progressBar?.textContent;
        const matches = progressBarText?.match(/(\d+)%/);

        if (matches) {
            return parseInt(matches[1]);
        }

        return null;
    }

    /**
     * Dispatch a mouse event on an element
     * @param {HTMLElement} element - Target element
     * @param {string} eventType - Event type (e.g., 'mousedown', 'click')
     */
    dispatchMouseEvent(element, eventType) {
        const mouseEvent = new MouseEvent(eventType, {
            bubbles: true,
            cancelable: true,
            view: window,
            button: 0
        });

        element.dispatchEvent(mouseEvent);
    }

    /**
     * Check if Forge is being used (vs standard SD WebUI)
     * @returns {boolean}
     */
    isForge() {
        return !!querySelector(SELECTORS.FORGE_INDICATOR);
    }
}
