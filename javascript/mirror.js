/**
 * Two-way mirror of the generation parameters for the Generate tab of the popup.
 * While the tab is shown, the parameters of the shown generation mode (txt2img, img2img or Inpaint upload)
 * are polled and sent to the popup when they change, so that edits made in WebUI appear in the popup;
 * edits made in the popup are applied here.
 * The poll also reports the progress and the live preview of a running generation,
 * and the input images of img2img and inpaint.
 */

import {SELECTORS} from "./adapters/selectors.js";
import {createReferences} from "./references.js";
import {isRestoringUiParams} from "./persistence.js";

const POLL_INTERVAL = 600;
// The prompts are unlocked when the popup closes, checked also while the Generate tab is not shown
const LOCK_CHECK_INTERVAL = 1000;
// Lets WebUI process an applied value (e.g. recount the tokens) before it is read back
const APPLY_SETTLE_DELAY = 300;

// Parameters of both generation tabs set by typing into an input: name -> selector key suffix
const TAB_INPUT_PARAMS = {
    prompt: 'PROMPT',
    negativePrompt: 'NEG_PROMPT',
    width: 'WIDTH',
    height: 'HEIGHT',
    steps: 'STEPS',
    cfg: 'CFG_SCALE',
    seed: 'SEED',
    subseed: 'SUBSEED',
    subseedStrength: 'SUBSEED_STRENGTH',
    denoising: 'DENOISING'
};

// Parameters of both generation tabs set by choosing a dropdown option: name -> selector key suffix
const TAB_DROPDOWN_PARAMS = {
    sampler: 'SAMPLING',
    scheduler: 'SCHEDULER'
};

// Hires. fix of txt2img: name -> selector key
const HIRES_INPUT_PARAMS = {
    hiresScale: 'HIRES_SCALE',
    hiresSteps: 'HIRES_STEPS'
};

const HIRES_DROPDOWN_PARAMS = {
    hiresUpscaler: 'HIRES_UPSCALER'
};

// Radio groups of img2img: name -> selector key; their choices are sent as options
const IMG2IMG_RADIO_PARAMS = {
    resizeMode: 'IMG2IMG_RESIZE_MODE_ID',
    maskMode: 'IMG2IMG_MASK_MODE_ID',
    inpaintArea: 'IMG2IMG_INPAINT_AREA_ID',
    maskedContent: 'IMG2IMG_MASKED_CONTENT_ID'
};

// Applied before the others: UI preset, checkpoint and VAE / Text Encoder
const MODEL_PARAMS = ['uiPreset', 'checkpoint', 'modules'];

const stripHash = title => String(title ?? '').replace(/ \[[^\]]+\]$/, '');

/**
 * @param {UIOperations} uiOperations - WebUI operations facade
 * @param {SDWebuiAdapter} adapter - DOM adapter
 * @param {Object} popup - {sendMessage: (msg) => boolean, isOpen: () => boolean}
 */
export function createWebUIMirror(uiOperations, adapter, popup) {
    const references = createReferences(adapter);
    let timer = null;
    let lastParams = null;
    let lastLive = null;
    let lastInputs = null;
    let locked = false;
    let lockCheckTimer = null;
    let applying = Promise.resolve();

    /**
     * Start or stop sending the parameters (the Generate tab is shown or hidden)
     * @param {boolean} active
     */
    function subscribe(active) {
        clearInterval(timer);
        timer = null;

        if (active) {
            // The tab is (re)shown: send the current state even if it did not change;
            // the live progress too, since the popup may keep it from a generation that ended meanwhile
            lastParams = null;
            lastInputs = null;
            lastLive = {active: true};
            timer = setInterval(poll, POLL_INTERVAL);
            poll();
        }
    }

    function poll() {
        if (!popup.isOpen()) {
            subscribe(false);
            setPromptsLocked(false);
            return;
        }

        const state = captureState();
        const json = JSON.stringify(state);

        if (json !== lastParams) {
            lastParams = json;
            popup.sendMessage({type: "WEBUI_PARAMS", ...state});
        }

        sendInputImages(state.mode);
        sendLiveProgress(state.busy, state.mode);
    }

    /**
     * @param {string} mode - Generation mode
     * @returns {'TXT2IMG'|'IMG2IMG'} Selector key prefix of its tab
     */
    function tabOf(mode) {
        return mode === 'txt2img' ? 'TXT2IMG' : 'IMG2IMG';
    }

    /**
     * Progress and live preview of the running generation; one final message when it ends
     * @param {boolean} busy
     * @param {string} mode
     */
    function sendLiveProgress(busy, mode) {
        if (!busy && !lastLive?.active)
            return;

        const previews = adapter.getAllElements(`${tabOf(mode)}_LIVE_PREVIEW`);
        const live = busy
            ? {active: true, progress: uiOperations.getGenerationProgress() ?? 0,
               preview: previews.length ? previews[previews.length - 1].src : null}
            : {active: false, progress: 100, preview: null};

        if (live.active !== lastLive?.active || live.progress !== lastLive.progress || live.preview !== lastLive.preview) {
            lastLive = live;
            popup.sendMessage({type: "LIVE_PROGRESS", ...live});
        }
    }

    /**
     * Input images of img2img and inpaint, sent apart from the parameters, since the canvas image is a data URL.
     * Sources are compared by their length and ends, which is enough to tell a new image
     * @param {string} mode
     */
    function sendInputImages(mode) {
        const inputs = uiOperations.getInputImages(mode);
        const signature = [mode, inputs.image, inputs.mask]
            .map(source => source ? `${source.length}:${source.slice(0, 64)}:${source.slice(-64)}` : source)
            .join('|');

        if (signature !== lastInputs) {
            lastInputs = signature;
            popup.sendMessage({type: "INPUT_IMAGES", mode, ...inputs});
        }
    }

    function captureState() {
        const mode = uiOperations.getGenerationMode();
        const tab = tabOf(mode);
        const params = {};

        for (const [name, suffix] of [...Object.entries(TAB_INPUT_PARAMS), ...Object.entries(TAB_DROPDOWN_PARAMS)])
            params[name] = adapter.getInputValue(`${tab}_${suffix}`);

        if (tab === 'TXT2IMG') {
            for (const [name, key] of [...Object.entries(HIRES_INPUT_PARAMS), ...Object.entries(HIRES_DROPDOWN_PARAMS)])
                params[name] = adapter.getInputValue(key);

            params.hiresFix = adapter.getElement('HIRES_CHECKBOX')?.checked ?? null;
        }
        else {
            for (const [name, key] of Object.entries(IMG2IMG_RADIO_PARAMS))
                params[name] = adapter.getRadioValue(key);
        }

        // Forge relabels the distilled CFG slider as Shift for flow models, or hides it
        const sliderKind = uiOperations.getDistilledCfgSliderKind(tab);
        params.shift = sliderKind ? adapter.getInputValue(`${tab}_DISTILLED_CFG`) : null;
        params.uiPreset = adapter.getInputValue('FORGE_UI_PRESET');
        params.checkpoint = adapter.getInputValue('MODEL_CHECKPOINT');
        // Null without the Forge Neo modules dropdown
        params.modules = uiOperations.getModules();

        const options = {
            uiPresets: params.uiPreset === null ? [] : uiOperations.getUiPresetChoices(),
            upscalers: getChoices(SELECTORS.HIRES_UPSCALER_ID)
        };

        for (const [name, key] of Object.entries(IMG2IMG_RADIO_PARAMS))
            options[name] = adapter.getRadioChoices(key);

        return {
            mode,
            params,
            sliderKind,
            tokens: {
                prompt: getTokenCount(`${tab}_TOKEN_COUNTER`),
                negativePrompt: getTokenCount(`${tab}_NEG_TOKEN_COUNTER`)
            },
            options,
            references: references.captureState(tab.toLowerCase(), params.uiPreset),
            busy: !uiOperations.isReadyToGenerate(),
            switchingUiPreset: uiOperations.isSwitchingUiPreset(),
            restoringParams: isRestoringUiParams(),
            locked
        };
    }

    /**
     * Text of a WebUI token counter ("41/75"), null if counters are disabled
     * @param {string} key - Selector key of the counter
     * @returns {string|null}
     */
    function getTokenCount(key) {
        const counter = adapter.getElement(key);

        if (!counter || counter.style.display === 'none')
            return null;

        return counter.textContent.trim() || null;
    }

    /**
     * Choices of a Gradio dropdown, as configured when WebUI was loaded
     * @param {string} elemId
     * @returns {string[]}
     */
    function getChoices(elemId) {
        const components = window.gradio_config?.components ?? [];
        const component = components.find(c => c.props?.elem_id === elemId);

        return component?.props?.choices?.map(c => Array.isArray(c) ? c[1] : c) ?? [];
    }

    /**
     * Run an edit after the previous ones; edits are serialized, since dropdowns are set asynchronously
     * @param {() => Promise<void>} edit
     * @returns {Promise<void>}
     */
    function enqueue(edit) {
        applying = applying.then(edit).catch(e => console.error(e));
        return applying;
    }

    /**
     * Apply parameters edited in the popup to the shown generation mode
     * @param {Object} params - Subset of the parameters sent in WEBUI_PARAMS
     * @returns {Promise<void>}
     */
    function applyParams(params) {
        return enqueue(() => doApplyParams(params));
    }

    /**
     * Show the WebUI tab of a generation mode, then apply the parameters remembered by the popup for it
     * @param {'txt2img'|'img2img'|'inpaint'} mode
     * @param {Object|null} params
     * @returns {Promise<void>}
     */
    function setMode(mode, params) {
        return enqueue(async () => {
            await uiOperations.setGenerationMode(mode);

            if (params)
                await doApplyParams(params);
            else
                setTimeout(pollIfActive, APPLY_SETTLE_DELAY);
        });
    }

    async function doApplyParams(params) {
        const tab = tabOf(uiOperations.getGenerationMode());
        // The UI preset resets the sampling parameters, which may come with it
        const entries = Object.entries(params)
            .sort(([a], [b]) => MODEL_PARAMS.includes(b) - MODEL_PARAMS.includes(a));

        for (const [name, value] of entries) {
            if (value === undefined || value === null)
                continue;

            if (name === 'uiPreset')
                await uiOperations.setUiPreset(value);
            else if (name === 'checkpoint') {
                // Another checkpoint brings its UI preset, unless the preset is set too
                if (!('uiPreset' in params) && stripHash(adapter.getInputValue('MODEL_CHECKPOINT')) !== stripHash(value))
                    await uiOperations.applyUiPresetForModel(value);

                await uiOperations.restoreModel(value);
            }
            else if (name === 'hiresFix') {
                if (tab === 'TXT2IMG')
                    adapter.toggleHiresFix(value, !value);
            }
            else if (name === 'modules')
                await uiOperations.setModules(value);
            else if (name in TAB_DROPDOWN_PARAMS)
                await adapter.setDropdownValue(`${tab}_${TAB_DROPDOWN_PARAMS[name]}`, value, true);
            else if (name in HIRES_DROPDOWN_PARAMS) {
                if (tab === 'TXT2IMG')
                    await adapter.setDropdownValue(HIRES_DROPDOWN_PARAMS[name], value, true);
            }
            else if (name in HIRES_INPUT_PARAMS) {
                if (tab === 'TXT2IMG')
                    adapter.setInputValue(HIRES_INPUT_PARAMS[name], value);
            }
            else if (name in IMG2IMG_RADIO_PARAMS) {
                if (tab === 'IMG2IMG')
                    adapter.setRadioValue(IMG2IMG_RADIO_PARAMS[name], value);
            }
            else if (name === 'shift') {
                if (uiOperations.getDistilledCfgSliderKind(tab))
                    adapter.setInputValue(`${tab}_DISTILLED_CFG`, value);
            }
            else if (name in TAB_INPUT_PARAMS) {
                adapter.setInputValue(`${tab}_${TAB_INPUT_PARAMS[name]}`, value);

                // WebUI applies the variation seed only if its "Extra" checkbox is checked
                if (name === 'subseedStrength' && Number(value) > 0)
                    adapter.setCheckboxValue(`${tab}_SUBSEED_SHOW`, true);

                // The img2img size applies only on the "Resize to" tab
                if (tab === 'IMG2IMG' && (name === 'width' || name === 'height'))
                    adapter.selectFirstTab('IMG2IMG_RESIZE_TABS');
            }
            else if (name === 'referencesEnabled')
                references.setEnabled(tab.toLowerCase(), value);
            else if (name === 'referenceMaxSize')
                references.setMaxSize(tab.toLowerCase(), value);
            else if (name === 'edit')
                await references.setEdit(adapter.getInputValue('FORGE_UI_PRESET'), value);
        }

        setTimeout(pollIfActive, APPLY_SETTLE_DELAY);
    }

    /**
     * Put an image chosen in the popup into the input of a mode (img2img canvas or inpaint upload),
     * by default the shown one
     * @param {'image'|'mask'} kind
     * @param {File} file
     * @param {'img2img'|'inpaint'} [mode]
     */
    function setInputImage(kind, file, mode) {
        return enqueue(async () => {
            mode ??= uiOperations.getGenerationMode() === 'img2img' ? 'img2img' : 'inpaint';
            await uiOperations.setInputImage(mode, kind, file);
            setTimeout(pollIfActive, APPLY_SETTLE_DELAY);
        });
    }

    /**
     * Edit the reference images of the shown generation tab
     * @param {Object} edit - {add: File[]} | {remove: number} | {clear: true}
     */
    async function editReferences(edit) {
        await applying;

        const tab = tabOf(uiOperations.getGenerationMode()).toLowerCase();

        if (edit.add)
            await references.addImages(tab, edit.add);
        else if (edit.remove !== undefined)
            await references.removeImage(tab, edit.remove);
        else if (edit.clear)
            await references.clearImages(tab);

        pollIfActive();
    }

    /**
     * Wait for the parameters sent before a generation request to be applied
     * @returns {Promise<void>}
     */
    function settled() {
        return applying;
    }

    /**
     * Parameters of the shown generation mode for a project (with the Hires. fix checkbox of txt2img)
     * @returns {{mode: string, params: Object}}
     */
    function captureSnapshot() {
        const {mode, params} = captureState();
        return {mode, params};
    }

    /**
     * Restore the parameters of a project: show the WebUI tab of its mode (another img2img mode tab is kept)
     * and apply them
     * @param {string} mode
     * @param {Object} params
     * @returns {Promise<void>}
     */
    function restoreSnapshot(mode, params) {
        if (['txt2img', 'img2img', 'inpaint'].includes(mode))
            return setMode(mode, params);

        return applyParams(params);
    }

    function pollIfActive() {
        if (timer)
            poll();
    }

    /**
     * Click the WebUI button that reuses the seed of the last generation
     * @param {'seed'|'subseed'} which
     */
    function reuseSeed(which) {
        const tab = tabOf(uiOperations.getGenerationMode());

        adapter.getElement(which === 'subseed' ? `${tab}_REUSE_SUBSEED` : `${tab}_REUSE_SEED`)?.click();
        setTimeout(pollIfActive, APPLY_SETTLE_DELAY);
    }

    /**
     * Cover the prompts of both generation tabs with an overlay, so that they are edited only in the popup.
     * The popup remembers the lock and locks again when it is reopened
     * @param {boolean} lock
     */
    function setPromptsLocked(lock) {
        if (lock === locked)
            return;

        locked = lock;

        clearInterval(lockCheckTimer);
        lockCheckTimer = lock
            ? setInterval(() => popup.isOpen() || setPromptsLocked(false), LOCK_CHECK_INTERVAL)
            : null;

        for (const [id, key] of [[SELECTORS.TXT2IMG_PROMPT_ID, 'TXT2IMG_PROMPT'],
                                 [SELECTORS.TXT2IMG_NEG_PROMPT_ID, 'TXT2IMG_NEG_PROMPT'],
                                 [SELECTORS.IMG2IMG_PROMPT_ID, 'IMG2IMG_PROMPT'],
                                 [SELECTORS.IMG2IMG_NEG_PROMPT_ID, 'IMG2IMG_NEG_PROMPT']]) {
            const container = document.getElementById(id);
            const textarea = adapter.getElement(key);

            if (!container)
                continue;

            if (textarea)
                textarea.readOnly = lock;

            container.querySelector(':scope > .image-bench-lock')?.remove();
            container.classList.toggle('image-bench-locked', lock);

            if (lock)
                container.appendChild(createLockOverlay());
        }

        pollIfActive();
    }

    function createLockOverlay() {
        const overlay = document.createElement('div');
        overlay.className = 'image-bench-lock';

        const label = document.createElement('span');
        label.textContent = '🔒 Edited in Image Bench';

        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Unlock';
        // Unlocked by the user: the popup forgets the lock
        button.addEventListener('click', () => {
            setPromptsLocked(false);
            popup.sendMessage({type: "WEBUI_PROMPTS_UNLOCKED"});
        });

        overlay.append(label, button);
        return overlay;
    }

    return {subscribe, applyParams, setMode, setInputImage, editReferences, settled, reuseSeed, setPromptsLocked,
            captureSnapshot, restoreSnapshot};
}
