/**
 * Reference images of the edit models for the Generate tab of the popup.
 * Forge passes them through the "ImageStitch Integrated" accordion of each generation tab, whose gallery
 * is edited with its own buttons: the upload image and Append / Delete Selected / Clear All.
 * Whether a model uses the references is a WebUI setting per model family ("Settings in UI" may show it
 * in a generation tab, where it overrides the global value).
 */

import {SELECTORS} from "./adapters/selectors.js";

// Setting that enables the references of a model family, by Forge UI preset;
// inverted: the setting disables them. A new edit model is added here
const EDIT_OPTIONS = {
    klein: {name: 'klein_no_reference', inverted: true},
    anima: {name: 'anima_do_reference'},
    krea: {name: 'krea2_do_reference'}
};

// Wait for the upload image to be loaded before appending it, and for a selection before deleting
const UPLOAD_TIMEOUT = 10000;
const SETTLE_DELAY = 250;

/**
 * @param {SDWebuiAdapter} adapter - DOM adapter
 */
export function createReferences(adapter) {
    // Global values of the edit settings, read from the backend
    const globalOptions = {};
    let editing = Promise.resolve();

    loadGlobalOptions();

    async function loadGlobalOptions() {
        const names = Object.values(EDIT_OPTIONS).map(option => option.name);

        try {
            const response = await fetch(`/image-bench/webui_options?names=${names.join(',')}`);

            if (response.ok)
                Object.assign(globalOptions, await response.json());
        } catch (e) {
            console.error('[Image Bench] Unable to read the edit settings:', e);
        }
    }

    /**
     * @param {'txt2img'|'img2img'} tab
     * @returns {HTMLElement|null} The ImageStitch accordion of the tab
     */
    function getAccordion(tab) {
        return document.getElementById(SELECTORS.IMAGE_STITCH_GALLERY(tab))?.closest('.input-accordion') ?? null;
    }

    function findButton(accordion, label) {
        return Array.from(accordion.querySelectorAll('button')).find(button => button.textContent.trim() === label);
    }

    /**
     * Edit setting of the current model family, null if it has none
     * @param {string|null} uiPreset
     */
    function getEditOption(uiPreset) {
        return EDIT_OPTIONS[uiPreset] ?? null;
    }

    /**
     * Value of a setting in a tab: its "Settings in UI" checkbox if the tab shows it, else the global value
     * @returns {boolean|null}
     */
    function getOptionValue(tab, name) {
        const checkbox = document.getElementById(SELECTORS.EXTRA_OPTIONS(tab))
            ?.querySelector(SELECTORS.SETTING_CHECKBOX(name));

        return checkbox ? checkbox.checked : globalOptions[name] ?? null;
    }

    /**
     * State of the references in a tab
     * @param {'txt2img'|'img2img'} tab
     * @param {string|null} uiPreset
     * @returns {Object|null} {enabled, images: [src], maxSize, edit: true|false|null (no switch)}, null if absent
     */
    function captureState(tab, uiPreset) {
        const accordion = getAccordion(tab);

        if (!accordion)
            return null;

        const gallery = document.getElementById(SELECTORS.IMAGE_STITCH_GALLERY(tab));
        const images = Array.from(gallery.querySelectorAll(`${SELECTORS.IMAGE_STITCH_THUMBNAIL} img`))
            .map(image => image.src);
        const option = getEditOption(uiPreset);
        const value = option ? getOptionValue(tab, option.name) : null;

        return {
            enabled: accordion.visibleCheckbox?.checked ?? false,
            images,
            maxSize: accordion.querySelector('input[type="number"]')?.value ?? null,
            edit: value === null ? null : option.inverted ? !value : value
        };
    }

    /**
     * Edits are serialized, since each one waits for Gradio
     * @param {() => Promise<void>} edit
     */
    function enqueue(edit) {
        editing = editing.then(edit).catch(e => console.error('[Image Bench] Reference edit failed:', e));
        return editing;
    }

    function setEnabled(tab, enabled) {
        const accordion = getAccordion(tab);

        if (accordion && accordion.visibleCheckbox?.checked !== enabled)
            window.inputAccordionChecked?.(accordion.id, enabled);
    }

    function setMaxSize(tab, value) {
        const input = getAccordion(tab)?.querySelector('input[type="number"]');

        if (input) {
            input.value = value;
            input.dispatchEvent(new Event('input', {bubbles: true}));
            input.dispatchEvent(new Event('blur', {bubbles: true}));
        }
    }

    /**
     * Append images: each is put into the upload image and appended with its button
     * @param {'txt2img'|'img2img'} tab
     * @param {File[]} files
     */
    function addImages(tab, files) {
        return enqueue(async () => {
            const accordion = getAccordion(tab);

            if (!accordion)
                return;

            setEnabled(tab, true);

            for (const file of files) {
                const upload = accordion.querySelector(SELECTORS.IMAGE_COMPONENT)?.closest('.block');

                if (!upload || !adapter.setImageFileIn(upload, file))
                    return;

                if (!await adapter.waitFor(() => upload.querySelector('img'), UPLOAD_TIMEOUT))
                    return;

                findButton(accordion, 'Append Pasted Image')?.click();
                await adapter.waitFor(() => !upload.querySelector('img'), UPLOAD_TIMEOUT);
            }
        });
    }

    /**
     * Delete an image: it is selected in the gallery, then deleted with its button
     * @param {'txt2img'|'img2img'} tab
     * @param {number} index
     */
    function removeImage(tab, index) {
        return enqueue(async () => {
            const accordion = getAccordion(tab);
            const gallery = document.getElementById(SELECTORS.IMAGE_STITCH_GALLERY(tab));
            const thumbnail = gallery?.querySelectorAll(SELECTORS.IMAGE_STITCH_THUMBNAIL)[index];

            if (!thumbnail)
                return;

            thumbnail.click();
            await adapter.sleep(SETTLE_DELAY);
            findButton(accordion, 'Delete Selected Image')?.click();
            await adapter.sleep(SETTLE_DELAY);
        });
    }

    function clearImages(tab) {
        return enqueue(async () => {
            const accordion = getAccordion(tab);

            findButton(accordion ?? document.createElement('div'), 'Clear All References')?.click();
            await adapter.sleep(SETTLE_DELAY);
        });
    }

    /**
     * Turn the references of the current model family on or off: in the global settings
     * and in the "Settings in UI" checkboxes of both tabs, which would override them
     * @param {string|null} uiPreset
     * @param {boolean} edit
     */
    async function setEdit(uiPreset, edit) {
        const option = getEditOption(uiPreset);

        if (!option)
            return;

        const value = option.inverted ? !edit : edit;

        for (const tab of ['txt2img', 'img2img']) {
            const checkbox = document.getElementById(SELECTORS.EXTRA_OPTIONS(tab))
                ?.querySelector(SELECTORS.SETTING_CHECKBOX(option.name));

            if (checkbox && checkbox.checked !== value)
                checkbox.click();
        }

        try {
            const response = await fetch('/image-bench/webui_options', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({[option.name]: value})
            });

            if (response.ok)
                globalOptions[option.name] = value;
        } catch (e) {
            console.error('[Image Bench] Unable to change the edit setting:', e);
        }
    }

    return {captureState, setEnabled, setMaxSize, addImages, removeImage, clearImages, setEdit};
}

