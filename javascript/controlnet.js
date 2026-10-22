/**
 * Two-way mirror of a Forge "ControlNet Integrated" unit for the ControlNet tab of the popup,
 * and the ControlNet targets of the editor plugin.
 * While the tab is shown, the unit chosen there is polled in the shown generation tab (txt2img or img2img)
 * and sent to the popup when it changes (CONTROLNET_STATE, CONTROLNET_IMAGES); edits made in the popup are applied here.
 * In img2img a unit uses the img2img image unless "Upload independent control image" is checked,
 * which an image set here checks first.
 */

import {SELECTORS} from "./adapters/selectors.js";
import {sendImageToEditor} from "./shared/editor-send.js";

const POLL_INTERVAL = 600;
// Lets WebUI process an applied value before it is read back
const APPLY_SETTLE_DELAY = 300;
// Gradio round trip of a ControlNet event (control type filter, independent image, Use Mask, Allow Preview)
const EVENT_DELAY = 500;
// A unit tab selected in WebUI may be rendered later
const UNIT_RENDER_TIMEOUT = 1000;
const IMAGE_TIMEOUT = 10000;
const PREPROCESS_TIMEOUT = 120000;
// A pose is rendered by the WebUI backend
const POSE_RENDER_TIMEOUT = 30000;
const POSE_URL_PREFIX = 'data:application/json;base64,';

// Parameters by the kind of their WebUI component (element names of SELECTORS.CONTROLNET_ELEMENT)
const CHECKBOX_PARAMS = ['enabled', 'pixelPerfect', 'allowPreview', 'useMask', 'independent'];
const RADIO_PARAMS = ['controlType', 'controlMode', 'resizeMode'];
const DROPDOWN_PARAMS = ['preprocessor', 'model'];
// Preprocessor sliders: Resolution (hidden with Pixel Perfect) and the two thresholds of the preprocessor
const SLIDER_PARAMS = ['processorRes', 'thresholdA', 'thresholdB'];
// Checked when the popup or the editor first uses a unit
const DEFAULT_CHECKED = ['pixelPerfect', 'allowPreview'];

/**
 * @param {UIOperations} uiOperations - WebUI operations facade
 * @param {SDWebuiAdapter} adapter - DOM adapter
 * @param {Object} popup - {sendMessage: (msg) => boolean, isOpen: () => boolean}
 * @param {(message: string) => void} showAlert - Shows errors in the popup or in the WebUI window
 */
export function createControlNet(uiOperations, adapter, popup, showAlert) {
    let timer = null;
    // Unit shown in the popup, also the one that receives images from the editor
    let unit = 0;
    let lastState = null;
    let lastImages = null;
    let running = false;
    let applying = Promise.resolve();
    // Defaults applied once per page: `${tab}:${unit}:${name}`
    const initialized = new Set();

    /**
     * @returns {'txt2img'|'img2img'} The shown generation tab
     */
    function getTab() {
        return uiOperations.getGenerationMode() === 'txt2img' ? 'txt2img' : 'img2img';
    }

    /**
     * @param {'txt2img'|'img2img'} tab
     * @param {number} index - Unit index
     * @param {string} name - Element name (see SELECTORS.CONTROLNET_ELEMENT)
     * @returns {HTMLElement|null}
     */
    function element(tab, index, name) {
        return document.getElementById(SELECTORS.CONTROLNET_ELEMENT(tab, index, name));
    }

    function getCanvasImage(tab, index, name) {
        return adapter.getImageSourceOf(element(tab, index, name)?.querySelector(SELECTORS.FORGE_CANVAS_IMAGE));
    }

    /**
     * Hidden OpenPose elements of the preview group: the JSON link that an openpose preprocessor fills,
     * and the textbox and button that render an edited pose into the preview
     * @returns {{link: HTMLAnchorElement|null, textbox: HTMLTextAreaElement|null, render: HTMLElement|null}}
     */
    function poseElements(tab, index) {
        const group = element(tab, index, 'preview')?.closest(SELECTORS.CONTROLNET_PREVIEW_GROUP);

        return {
            link: group?.querySelector(SELECTORS.CONTROLNET_POSE_LINK) ?? null,
            textbox: group?.querySelector(SELECTORS.CONTROLNET_POSE_TEXTBOX) ?? null,
            render: group?.querySelector(SELECTORS.CONTROLNET_POSE_RENDER) ?? null
        };
    }

    /**
     * @returns {string|null} The pose JSON of the preview as a data URL, null if the preprocessor made none
     */
    function getPose(tab, index) {
        const url = poseElements(tab, index).link?.getAttribute('href') || '';
        return url.startsWith(POSE_URL_PREFIX) && url.length > POSE_URL_PREFIX.length ? url : null;
    }

    /**
     * Select the tab of a unit in WebUI, so that the user sees what the popup edits
     * @returns {Promise<boolean>} Whether the unit exists
     */
    async function showUnit(tab, index) {
        adapter.selectTabIn(document.getElementById(SELECTORS.CONTROLNET_TABS(tab)), index);
        return !!await adapter.waitFor(() => element(tab, index, 'enabled'), UNIT_RENDER_TIMEOUT);
    }

    /**
     * Run an edit after the previous ones; edits are serialized, since they wait for Gradio
     * @param {() => Promise<void>} edit
     * @returns {Promise<void>}
     */
    function enqueue(edit) {
        applying = applying.then(edit).catch(e => console.error('[Image Bench] ControlNet edit failed:', e));
        return applying;
    }

    // ---------- Mirror ----------

    /**
     * Start or stop sending the state of a unit (the ControlNet tab is shown or hidden, or another unit is chosen)
     * @param {boolean} active
     * @param {number} unitIndex
     * @param {boolean} defaults - Check Pixel Perfect and Allow Preview of a unit used for the first time
     */
    function subscribe(active, unitIndex = unit, defaults = true) {
        clearInterval(timer);
        timer = null;
        unit = unitIndex;

        if (active) {
            lastState = null;
            lastImages = null;
            timer = setInterval(poll, POLL_INTERVAL);

            enqueue(async () => {
                const tab = getTab();

                if (await showUnit(tab, unit) && defaults)
                    await applyDefaults(tab, unit);

                pollIfActive();
            });
        }
    }

    function poll() {
        if (!popup.isOpen()) {
            subscribe(false);
            return;
        }

        const state = captureState();
        const json = JSON.stringify(state);

        if (json !== lastState) {
            lastState = json;
            popup.sendMessage({type: "CONTROLNET_STATE", ...state});
        }

        sendImages(state.tab);
    }

    function pollIfActive() {
        if (timer)
            poll();
    }

    function captureState() {
        const tab = getTab();
        const tabs = document.getElementById(SELECTORS.CONTROLNET_TABS(tab));
        const units = Array.from({length: adapter.getTabCountIn(tabs)},
            (_, index) => ({enabled: adapter.isCheckedIn(element(tab, index, 'enabled')) ?? false}));
        const get = name => element(tab, unit, name);

        if (!get('enabled'))
            return {tab, unit, units, available: false, running};

        return {tab, unit, units, available: true, ...readUnit(tab, unit), running};
    }

    /**
     * Parameters of a unit, the choices of its radio groups and its preprocessor sliders
     * @returns {{params: Object, options: Object, sliders: Object}}
     */
    function readUnit(tab, index) {
        const get = name => element(tab, index, name);
        const toNumber = value => value === null || value === undefined || value === '' ? null : Number(value);
        const range = get('timestepRange');
        const params = {
            weight: toNumber(get('weight')?.querySelector(SELECTORS.NUMBER_INPUT)?.value),
            guidanceStart: toNumber(range?.querySelector(SELECTORS.RANGE_SLIDER_MIN)?.value),
            guidanceEnd: toNumber(range?.querySelector(SELECTORS.RANGE_SLIDER_MAX)?.value)
        };
        const options = {};

        // independent is null in txt2img, which has no such checkbox
        for (const name of CHECKBOX_PARAMS)
            params[name] = adapter.isCheckedIn(get(name));

        for (const name of RADIO_PARAMS) {
            params[name] = adapter.getRadioValueIn(get(name));
            options[name] = adapter.getRadioChoicesIn(get(name));
        }

        for (const name of DROPDOWN_PARAMS)
            params[name] = get(name)?.querySelector(SELECTORS.DROPDOWN_INPUT)?.value ?? null;

        // Forge relabels the preprocessor sliders and sets their ranges for each preprocessor
        const sliders = {};

        for (const name of SLIDER_PARAMS) {
            const slider = describeSlider(get(name));

            params[name] = slider ? toNumber(get(name).querySelector(SELECTORS.NUMBER_INPUT)?.value) : null;
            sliders[name] = slider;
        }

        return {params, options, sliders};
    }

    /**
     * @param {HTMLElement|null} block - Gradio slider
     * @returns {{label: string, min: number, max: number, step: number, visible: boolean}|null} null if it is absent
     */
    function describeSlider(block) {
        const input = block?.querySelector(SELECTORS.RANGE_INPUT) ?? block?.querySelector(SELECTORS.NUMBER_INPUT);

        if (!input)
            return null;

        const label = block.querySelector(SELECTORS.BLOCK_LABEL) ?? block.querySelector('label');
        const attribute = (name, fallback) => {
            const value = parseFloat(input.getAttribute(name));
            return Number.isFinite(value) ? value : fallback;
        };

        return {
            label: label?.textContent.trim() ?? '',
            min: attribute('min', 0),
            max: attribute('max', 100),
            step: attribute('step', 1),
            visible: getComputedStyle(block).display !== 'none'
        };
    }

    /**
     * Images of the unit, sent apart from the state, since the canvas images are data URLs.
     * Sources are compared by their length and ends, which is enough to tell a new image
     * @param {'txt2img'|'img2img'} tab
     */
    function sendImages(tab) {
        const preview = getCanvasImage(tab, unit, 'preview');
        const images = {
            image: getCanvasImage(tab, unit, 'image'),
            mask: getCanvasImage(tab, unit, 'mask'),
            preview,
            // OpenPose JSON of the preview, edited in the OpenPose editor of the popup
            pose: preview ? getPose(tab, unit) : null
        };
        const signature = [tab, unit, images.image, images.mask, images.preview, images.pose]
            .map(source => typeof source === 'string' ? `${source.length}:${source.slice(0, 64)}:${source.slice(-64)}` : source)
            .join('|');

        if (signature !== lastImages) {
            lastImages = signature;
            popup.sendMessage({type: "CONTROLNET_IMAGES", tab, unit, ...images});
        }
    }

    function setRunning(value) {
        running = value;
        pollIfActive();
    }

    // ---------- Edits ----------

    /**
     * Apply parameters edited in the popup to a unit of the shown generation tab
     * @param {number} unitIndex
     * @param {Object} params - Subset of the parameters sent in CONTROLNET_STATE
     * @returns {Promise<void>}
     */
    function applyParams(unitIndex, params) {
        return enqueue(async () => {
            const tab = getTab();
            const get = name => element(tab, unitIndex, name);

            if (!await showUnit(tab, unitIndex))
                return;

            for (const [name, value] of Object.entries(params)) {
                if (value === undefined || value === null)
                    continue;

                if (name === 'independent' && value)
                    await useIndependentImage(tab, unitIndex);
                else if (CHECKBOX_PARAMS.includes(name)) {
                    if (adapter.setCheckedIn(get(name), value))
                        await adapter.sleep(EVENT_DELAY);
                }
                else if (RADIO_PARAMS.includes(name))
                    adapter.setRadioValueIn(get(name), value);
                else if (DROPDOWN_PARAMS.includes(name)) {
                    const input = get(name)?.querySelector(SELECTORS.DROPDOWN_INPUT);

                    if (input)
                        await adapter.setDropdownElementValue(input, value, true);
                }
                else if (name === 'weight' || SLIDER_PARAMS.includes(name))
                    setNumber(get(name)?.querySelector(SELECTORS.NUMBER_INPUT), value);
                else if (name === 'guidanceStart')
                    setNumber(get('timestepRange')?.querySelector(SELECTORS.RANGE_SLIDER_MIN), value);
                else if (name === 'guidanceEnd')
                    setNumber(get('timestepRange')?.querySelector(SELECTORS.RANGE_SLIDER_MAX), value);
            }

            setTimeout(pollIfActive, APPLY_SETTLE_DELAY);
        });
    }

    /**
     * Parameters of a unit of the shown generation tab
     * @param {number} unitIndex
     * @returns {Object|null} As in CONTROLNET_STATE, null if the unit is absent
     */
    function readParams(unitIndex) {
        const tab = getTab();
        return element(tab, unitIndex, 'enabled') ? readUnit(tab, unitIndex).params : null;
    }

    function setNumber(input, value) {
        if (input)
            adapter.setInputElementValue(input, value);
    }

    /**
     * Run an action of a unit
     * @param {number} unitIndex
     * @param {'run'|'refresh'|'clearImage'|'clearMask'|'clearPreview'} action
     * @returns {Promise<void>}
     */
    function runAction(unitIndex, action) {
        return enqueue(async () => {
            const tab = getTab();

            if (!await showUnit(tab, unitIndex))
                return;

            if (action === 'run')
                await runPreprocessor(tab, unitIndex);
            else if (action === 'refresh')
                element(tab, unitIndex, 'refreshModels')?.click();
            else if (action === 'clearImage')
                element(tab, unitIndex, 'image')?.querySelector(SELECTORS.FORGE_CANVAS_REMOVE)?.click();
            else if (action === 'clearMask')
                element(tab, unitIndex, 'mask')?.querySelector(SELECTORS.FORGE_CANVAS_REMOVE)?.click();
            else if (action === 'clearPreview')
                await clearPreview(tab, unitIndex);

            setTimeout(pollIfActive, APPLY_SETTLE_DELAY);
        });
    }

    /**
     * Put an image chosen in the popup into a unit
     * @param {number} unitIndex
     * @param {'image'|'mask'} kind
     * @param {File} file
     * @returns {Promise<void>}
     */
    function setUnitImage(unitIndex, kind, file) {
        return enqueue(async () => {
            const tab = getTab();

            if (!await showUnit(tab, unitIndex))
                return;

            if (kind === 'mask')
                await loadMask(tab, unitIndex, file);
            else
                await loadImage(tab, unitIndex, file);

            pollIfActive();
        });
    }

    /**
     * Render a pose edited in the OpenPose editor into the preview of a unit, which then becomes the control image
     * (WebUI checks "use preview as input"), as the editor of sd-webui-controlnet did
     * @param {number} unitIndex
     * @param {string} pose - Pose JSON as a data URL
     * @returns {Promise<void>}
     */
    function setPose(unitIndex, pose) {
        return enqueue(async () => {
            const tab = getTab();

            if (!await showUnit(tab, unitIndex))
                return;

            if (!await renderPose(tab, unitIndex, pose))
                showAlert('The edited pose cannot be passed to ControlNet: its OpenPose elements are not found in WebUI.');
        });
    }

    /**
     * Render a pose (JSON data URL) into the preview of a unit
     * @returns {Promise<boolean>} Whether the unit has the OpenPose elements
     */
    async function renderPose(tab, unitIndex, pose) {
        const {textbox, render} = poseElements(tab, unitIndex);

        if (!textbox || !render || typeof pose !== 'string' || !pose.startsWith(POSE_URL_PREFIX))
            return false;

        const previous = getCanvasImage(tab, unitIndex, 'preview');

        if (adapter.setCheckedIn(element(tab, unitIndex, 'allowPreview'), true))
            await adapter.sleep(EVENT_DELAY);

        setRunning(true);

        try {
            adapter.setInputElementValue(textbox, pose);
            render.click();
            await adapter.waitFor(() => {
                const source = getCanvasImage(tab, unitIndex, 'preview');
                return source && source !== previous;
            }, POSE_RENDER_TIMEOUT);
        } finally {
            setRunning(false);
        }

        return true;
    }

    /**
     * Show the generation tab whose ControlNet the popup mirrors
     * @param {'txt2img'|'img2img'} tab
     * @returns {Promise<void>}
     */
    function setTab(tab) {
        return enqueue(async () => {
            await uiOperations.showGenerationTab(tab);

            if (await showUnit(tab, unit))
                await applyDefaults(tab, unit);

            setTimeout(pollIfActive, APPLY_SETTLE_DELAY);
        });
    }

    /**
     * Put an image sent from the editor into the unit shown in the popup (the first one if it was not opened):
     * cn_preprocess runs the preprocessor and sends the preview back to the editor, cn_image is used as the control
     * image without a preprocessor, cn_mask becomes the mask of the unit
     * @param {'cn_preprocess'|'cn_image'|'cn_mask'} target
     * @param {File} file
     * @returns {Promise<void>}
     */
    function onEditorImage(target, file) {
        return enqueue(async () => {
            const tab = getTab();
            const index = unit;

            if (!await showUnit(tab, index)) {
                showAlert(`ControlNet unit ${index + 1} is not found in the ${tab} tab of WebUI.`);
                return;
            }

            if (target === 'cn_mask')
                await loadMask(tab, index, file);
            else if (await loadImage(tab, index, file)) {
                if (target === 'cn_image') {
                    const input = element(tab, index, 'preprocessor')?.querySelector(SELECTORS.DROPDOWN_INPUT);

                    if (input)
                        await adapter.setDropdownElementValue(input, 'None', true);

                    await clearPreview(tab, index);
                }
                else if (target === 'cn_preprocess')
                    await preprocessToEditor(tab, index);
            }

            pollIfActive();
        });
    }

    async function preprocessToEditor(tab, index) {
        const preview = await runPreprocessor(tab, index);

        if (!preview) {
            showAlert('The ControlNet preprocessor produced no preview.');
            return;
        }

        const preprocessor = element(tab, index, 'preprocessor')?.querySelector(SELECTORS.DROPDOWN_INPUT)?.value;
        const error = await sendImageToEditor(preview, `ControlNet ${index + 1} ${preprocessor || ''} preview`);

        if (error)
            showAlert(error);
    }

    // ---------- Unit operations ----------

    /**
     * Check Pixel Perfect and Allow Preview the first time a unit is used; in img2img Allow Preview exists
     * only with an independent image
     */
    async function applyDefaults(tab, index) {
        const independent = tab === 'txt2img' || adapter.isCheckedIn(element(tab, index, 'independent'));

        for (const name of DEFAULT_CHECKED) {
            const key = `${tab}:${index}:${name}`;

            if (initialized.has(key) || name === 'allowPreview' && !independent || !element(tab, index, name))
                continue;

            initialized.add(key);

            if (adapter.setCheckedIn(element(tab, index, name), true))
                await adapter.sleep(EVENT_DELAY);
        }
    }

    /**
     * In img2img, make the unit use its own image instead of the img2img image
     */
    async function useIndependentImage(tab, index) {
        if (tab !== 'img2img' || !adapter.setCheckedIn(element(tab, index, 'independent'), true))
            return;

        // WebUI clears the image of the unit and unchecks Allow Preview
        await adapter.sleep(EVENT_DELAY);
        initialized.delete(`${tab}:${index}:allowPreview`);
        await applyDefaults(tab, index);
    }

    /**
     * Load a file into a canvas of a unit and wait until it shows it
     * @returns {Promise<boolean>} Whether the canvas was found
     */
    async function loadCanvas(tab, index, name, file) {
        const fileInput = element(tab, index, name)?.querySelector(SELECTORS.FORGE_CANVAS_FILE_INPUT);
        const previous = getCanvasImage(tab, index, name);
        const started = Date.now();

        if (!adapter.setCanvasFileIn(fileInput, file))
            return false;

        // The same image keeps the source
        await adapter.waitFor(() => {
            const source = getCanvasImage(tab, index, name);
            return source && (source !== previous || Date.now() - started > EVENT_DELAY * 2);
        }, IMAGE_TIMEOUT);

        // Let the canvas pass the image to Gradio
        await adapter.sleep(EVENT_DELAY);
        return true;
    }

    /**
     * Put the control image into a unit and enable it
     * @returns {Promise<boolean>} Whether the unit has its image canvas
     */
    async function loadImage(tab, index, file) {
        await useIndependentImage(tab, index);

        if (!await loadCanvas(tab, index, 'image', file))
            return false;

        adapter.setCheckedIn(element(tab, index, 'enabled'), true);
        await applyDefaults(tab, index);
        return true;
    }

    async function loadMask(tab, index, file) {
        await useIndependentImage(tab, index);

        // Checking Use Mask puts an empty mask into the canvas, which would replace the loaded one
        if (adapter.setCheckedIn(element(tab, index, 'useMask'), true)) {
            await adapter.waitFor(() => getCanvasImage(tab, index, 'mask'), IMAGE_TIMEOUT);
            await adapter.sleep(EVENT_DELAY);
        }

        return loadCanvas(tab, index, 'mask', file);
    }

    /**
     * Run the preprocessor on the control image of a unit
     * @returns {Promise<string|null>} Source of the preview, null if there is none
     */
    async function runPreprocessor(tab, index) {
        if (tab === 'img2img' && !adapter.isCheckedIn(element(tab, index, 'independent')))
            return null;

        if (!getCanvasImage(tab, index, 'image'))
            return null;

        // The previous preview is cleared, so that the new one is told from it;
        // the preprocessor checks Allow Preview again
        await clearPreview(tab, index, false);
        setRunning(true);

        try {
            element(tab, index, 'runPreprocessor')?.click();
            return await adapter.waitFor(() => getCanvasImage(tab, index, 'preview'), PREPROCESS_TIMEOUT) || null;
        } finally {
            setRunning(false);
        }
    }

    /**
     * Clear the preview of a unit: WebUI clears it when Allow Preview is unchecked
     * @param {boolean} reopen - Check Allow Preview again
     */
    async function clearPreview(tab, index, reopen = true) {
        const allowPreview = element(tab, index, 'allowPreview');

        if (!adapter.setCheckedIn(allowPreview, false))
            return;

        await adapter.sleep(EVENT_DELAY);

        if (reopen) {
            adapter.setCheckedIn(allowPreview, true);
            await adapter.sleep(EVENT_DELAY);
        }
    }

    // ---------- Projects ----------

    /**
     * The enabled units of a generation tab for a project: their parameters, images and edited poses
     * @param {'txt2img'|'img2img'} tab
     * @returns {Promise<{index: number, params: Object, image: Blob|null, mask: Blob|null, pose: string|null}[]>}
     */
    async function captureUnits(tab) {
        await applying;

        const count = adapter.getTabCountIn(document.getElementById(SELECTORS.CONTROLNET_TABS(tab)));
        const units = [];

        for (let index = 0; index < count; index++) {
            if (!adapter.isCheckedIn(element(tab, index, 'enabled')))
                continue;

            const params = readUnit(tab, index).params;
            const preview = getCanvasImage(tab, index, 'preview');

            units.push({
                index,
                params,
                image: await toBlob(getCanvasImage(tab, index, 'image')),
                mask: params.useMask ? await toBlob(getCanvasImage(tab, index, 'mask')) : null,
                pose: preview ? getPose(tab, index) : null
            });
        }

        return units;
    }

    /**
     * The enabled units of a generation tab as they are now, read synchronously: their parameters and the sources
     * of their images (for the ControlNet record of a generation, see controlnetRecorder.js)
     * @param {'txt2img'|'img2img'} tab
     * @returns {{index: number, params: Object, image: string|null, mask: string|null, preview: string|null}[]}
     */
    function readEnabledUnits(tab) {
        const count = adapter.getTabCountIn(document.getElementById(SELECTORS.CONTROLNET_TABS(tab)));
        const units = [];

        for (let index = 0; index < count; index++) {
            if (!adapter.isCheckedIn(element(tab, index, 'enabled')))
                continue;

            const params = readUnit(tab, index).params;

            units.push({
                index,
                params,
                image: getCanvasImage(tab, index, 'image'),
                mask: params.useMask ? getCanvasImage(tab, index, 'mask') : null,
                preview: getCanvasImage(tab, index, 'preview')
            });
        }

        return units;
    }

    async function toBlob(source) {
        if (!source)
            return null;

        try {
            return await (await fetch(source)).blob();
        } catch (error) {
            console.warn('[Image Bench] Unable to read a ControlNet image:', error);
            return null;
        }
    }

    /**
     * Restore the units of a project in a generation tab; the other units are disabled
     * @param {'txt2img'|'img2img'} tab
     * @param {Object[]} units - As captured by captureUnits(), with the images as files
     * @returns {Promise<number[]>} Indexes of the units not found in WebUI
     */
    async function restoreUnits(tab, units) {
        const missing = [];

        await enqueue(async () => {
            const count = adapter.getTabCountIn(document.getElementById(SELECTORS.CONTROLNET_TABS(tab)));
            const indexes = new Set(units.map(entry => entry.index));

            for (let index = 0; index < count; index++)
                if (!indexes.has(index) && adapter.isCheckedIn(element(tab, index, 'enabled')))
                    adapter.setCheckedIn(element(tab, index, 'enabled'), false);

            for (const entry of units) {
                if (entry.index < count && await showUnit(tab, entry.index))
                    await restoreUnit(tab, entry);
                else
                    missing.push(entry.index);
            }

            // Back to the unit shown in the popup
            await showUnit(tab, unit);
            setTimeout(pollIfActive, APPLY_SETTLE_DELAY);
        });

        return missing;
    }

    async function restoreUnit(tab, {index, params, image, mask, pose}) {
        const get = name => element(tab, index, name);
        const isSet = value => value !== null && value !== undefined;
        const setChecked = async (name, value) => {
            if (isSet(value) && adapter.setCheckedIn(get(name), value))
                await adapter.sleep(EVENT_DELAY);
        };

        // An independent image clears the image of the unit
        if (tab === 'img2img')
            await setChecked('independent', !!params.independent);

        // The control type filters the preprocessors and models
        if (params.controlType && adapter.getRadioValueIn(get('controlType')) !== params.controlType) {
            adapter.setRadioValueIn(get('controlType'), params.controlType);
            await adapter.sleep(EVENT_DELAY);
        }

        for (const name of DROPDOWN_PARAMS) {
            const input = get(name)?.querySelector(SELECTORS.DROPDOWN_INPUT);

            if (input && params[name] && input.value !== params[name])
                await adapter.setDropdownElementValue(input, params[name], true);
        }

        await setChecked('pixelPerfect', params.pixelPerfect);
        await setChecked('allowPreview', params.allowPreview);

        for (const name of ['controlMode', 'resizeMode'])
            if (params[name])
                adapter.setRadioValueIn(get(name), params[name]);

        for (const name of ['weight', ...SLIDER_PARAMS])
            if (isSet(params[name]))
                setNumber(get(name)?.querySelector(SELECTORS.NUMBER_INPUT), params[name]);

        if (isSet(params.guidanceStart))
            setNumber(get('timestepRange')?.querySelector(SELECTORS.RANGE_SLIDER_MIN), params.guidanceStart);

        if (isSet(params.guidanceEnd))
            setNumber(get('timestepRange')?.querySelector(SELECTORS.RANGE_SLIDER_MAX), params.guidanceEnd);

        if (image)
            await loadCanvas(tab, index, 'image', image);
        else
            get('image')?.querySelector(SELECTORS.FORGE_CANVAS_REMOVE)?.click();

        // Checking Use Mask puts an empty mask into the canvas, which the mask then replaces
        if (mask) {
            if (adapter.setCheckedIn(get('useMask'), true)) {
                await adapter.waitFor(() => getCanvasImage(tab, index, 'mask'), IMAGE_TIMEOUT);
                await adapter.sleep(EVENT_DELAY);
            }

            await loadCanvas(tab, index, 'mask', mask);
        }
        else
            await setChecked('useMask', false);

        if (pose)
            await renderPose(tab, index, pose);

        adapter.setCheckedIn(get('enabled'), params.enabled ?? true);
    }

    return {subscribe, applyParams, readParams, runAction, setUnitImage, setPose, setTab, onEditorImage,
            readEnabledUnits, captureUnits, restoreUnits};
}
