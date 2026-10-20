/**
 * UIOperations - Facade for WebUI interactions
 * Provides high-level operations that encapsulate multiple adapter calls
 * Strategies depend on this facade instead of directly using the adapter
 */

import { SELECTORS } from '../adapters/selectors.js';

// Fallback if the preset choices can't be read from the Gradio config
const DEFAULT_UI_PRESETS = ['sd', 'xl', 'flux', 'klein', 'qwen', 'lumina', 'zit', 'wan', 'anima', 'ernie', 'pid', 'krea'];

// Presets whose value is searched in the model name by a different term
/**
 * VAE / Text Encoder modules of image parameters: the "Module 1", "Module 2", ... infotext entries
 * (file names without the extension), in their order
 * @param {Object} parameters - Image parameters, with lowercase keys
 * @returns {string[]}
 */
export function getImageModules(parameters) {
    return Object.keys(parameters ?? {})
        .map(key => key.match(/^module (\d+)$/))
        .filter(Boolean)
        .sort((a, b) => a[1] - b[1])
        .map(match => String(parameters[match[0]]));
}

// Extensions of the module files; infotext names modules without them
const MODULE_EXTENSION = /\.(safetensors|sft|gguf|ckpt|pt|pth|bin)$/i;

const UI_PRESET_SEARCH_TERMS = {
    sd: 'sd/',
    xl: 'sdxl',
    zit: 'z-image'
};

// Parameters remembered across WebUI reloads for both tabs, by selector key suffix
const TAB_PARAM_SELECTORS = {
    prompt: 'PROMPT',
    negativePrompt: 'NEG_PROMPT',
    sampler: 'SAMPLING',
    scheduler: 'SCHEDULER',
    steps: 'STEPS',
    cfg: 'CFG_SCALE',
    width: 'WIDTH',
    height: 'HEIGHT',
    seed: 'SEED',
    subseed: 'SUBSEED',
    subseedStrength: 'SUBSEED_STRENGTH',
    denoising: 'DENOISING'
};

const TAB_DROPDOWN_PARAMS = ['sampler', 'scheduler'];

// Captured tab parameters not remembered across WebUI reloads: the seed and the variation seed
const NOT_REMEMBERED_PARAMS = ['seed', 'subseed'];

/**
 * @param {Object|undefined} params - Tab parameters captured by captureTabParams()
 * @returns {Object|undefined} The parameters without those not remembered across reloads
 */
const withoutUnremembered = params => params && Object.fromEntries(Object.entries(params)
    .filter(([name]) => !NOT_REMEMBERED_PARAMS.includes(name)));

const isSet = value => value !== undefined && value !== null;

// Controls Forge sets for a UI preset; it has applied the preset when they stop changing
const UI_PRESET_DEPENDENT_KEYS = ['MODEL_CHECKPOINT', 'TXT2IMG_STEPS', 'TXT2IMG_SAMPLING', 'TXT2IMG_SCHEDULER',
    'IMG2IMG_STEPS', 'IMG2IMG_SAMPLING', 'IMG2IMG_SCHEDULER'];
// Waiting for the preset: time without changes that ends it, time for the first change, and the limit
const UI_PRESET_SETTLE_TIME = 700;
const UI_PRESET_FIRST_CHANGE_TIME = 1500;
const UI_PRESET_TIMEOUT = 30000;

export class UIOperations {
    /**
     * @param {Object} adapter - DOM adapter instance
     */
    constructor(adapter) {
        this.adapter = adapter;
        // UI preset switches in progress
        this.uiPresetSwitches = 0;
    }

    // ==================== HIGH-LEVEL OPERATIONS ====================

    /**
     * Apply a preset with proper toggle logic
     * If the preset is already selected, toggle to 'None' first to force re-application
     * @param {string} presetName - Name of the preset to apply
     * @returns {Promise<void>}
     */
    async applyPreset(presetName) {
        const presetDropdown = this.adapter.getElement('CONFIG_PRESET_TXT2IMG_DROPDOWN');

        if (presetDropdown) {
            // If already selected, toggle to 'None' first
            if (presetDropdown.value === presetName) {
                await this.adapter.setDropdownValue('CONFIG_PRESET_TXT2IMG_DROPDOWN', 'None');
                await this.adapter.sleep(333);
            }

            await this.adapter.setDropdownValue('CONFIG_PRESET_TXT2IMG_DROPDOWN', presetName);
        }
    }

    /**
     * Enable variation generation (subseed variations)
     * @param {number} strength - Variation strength (0-1)
     * @returns {Promise<void>}
     */
    async enableVariations(strength) {
        const tab = this.getTabPrefix();

        await this.adapter.setCheckboxValue(`${tab}_SUBSEED_SHOW`, true);
        await this.adapter.setInputValue(`${tab}_SUBSEED`, -1);
        await this.adapter.setInputValue(`${tab}_SUBSEED_STRENGTH`, strength);
    }

    /**
     * Disable variation generation and reset settings
     * @returns {Promise<void>}
     */
    async disableVariations() {
        const tab = this.getTabPrefix();

        await this.adapter.setInputValue(`${tab}_SUBSEED_STRENGTH`, 0);
        await this.adapter.setCheckboxValue(`${tab}_SUBSEED_SHOW`, false);
    }

    /**
     * Selector key prefix of the shown generation tab
     * @returns {'TXT2IMG'|'IMG2IMG'}
     */
    getTabPrefix() {
        return this.adapter.isImg2ImgTab() ? 'IMG2IMG' : 'TXT2IMG';
    }

    // ==================== GENERATION MODES (Generate tab of the popup) ====================

    /**
     * Generation mode shown in WebUI: txt2img, img2img (its img2img mode tab), inpaint (Inpaint upload)
     * or other (another img2img mode tab, e.g. Sketch)
     * @returns {'txt2img'|'img2img'|'inpaint'|'other'}
     */
    getGenerationMode() {
        if (!this.adapter.isImg2ImgTab())
            return 'txt2img';

        const modeTab = this.adapter.getImg2ImgModeTab();

        return modeTab === SELECTORS.IMG2IMG_IMG2IMG_TAB ? 'img2img'
            : modeTab === SELECTORS.IMG2IMG_INPAINT_UPLOAD_TAB ? 'inpaint'
            : 'other';
    }

    /**
     * Show the WebUI tab of a generation mode
     * @param {'txt2img'|'img2img'|'inpaint'} mode
     * @returns {Promise<void>}
     */
    async setGenerationMode(mode) {
        if (mode === this.getGenerationMode())
            return;

        if (mode === 'txt2img')
            window.switch_to_txt2img?.();
        else if (mode === 'img2img')
            this.adapter.switchToImg2ImgModeTab(SELECTORS.IMG2IMG_IMG2IMG_TAB, 0);
        else if (mode === 'inpaint')
            this.adapter.switchToInpaintUploadTab();

        // Let Gradio render the tab
        await this.sleep(200);
    }

    /**
     * Show a generation tab; img2img keeps its shown mode tab (img2img, Inpaint upload, ...)
     * @param {'txt2img'|'img2img'} tab
     * @returns {Promise<void>}
     */
    async showGenerationTab(tab) {
        if ((tab === 'img2img') === this.adapter.isImg2ImgTab())
            return;

        if (tab === 'txt2img')
            window.switch_to_txt2img?.();
        else {
            const modeTab = this.adapter.getImg2ImgModeTab();
            this.adapter.switchToImg2ImgModeTab(modeTab, 0);
        }

        // Let Gradio render the tab
        await this.sleep(200);
    }

    /**
     * Put an image into the input of a generation mode: the img2img canvas or the inpaint upload image or mask.
     * The mode tab is shown first
     * @param {'img2img'|'inpaint'} mode
     * @param {'image'|'mask'} kind - The mask is used only by inpaint
     * @param {File} file
     * @returns {Promise<boolean>} Whether the image component was found
     */
    async setInputImage(mode, kind, file) {
        if (mode === 'inpaint')
            return this.setInpaintUploadImage(kind, file);

        if (kind === 'mask')
            return false;

        await this.setGenerationMode('img2img');
        return this.adapter.setCanvasFile('IMG2IMG_CANVAS_FILE_INPUT', file);
    }

    /**
     * Sources of the input images of a generation mode, null where there is none
     * @param {'txt2img'|'img2img'|'inpaint'|'other'} mode
     * @returns {{image: string|null, mask: string|null}}
     */
    getInputImages(mode) {
        if (mode === 'img2img')
            return {image: this.adapter.getImageSource('IMG2IMG_CANVAS_IMAGE'), mask: null};

        if (mode === 'inpaint')
            return {image: this.adapter.getImageSource('IMG2IMG_INPAINT_UPLOAD_IMAGE_IMG'),
                    mask: this.adapter.getImageSource('IMG2IMG_INPAINT_UPLOAD_MASK_IMG')};

        return {image: null, mask: null};
    }

    /**
     * Set batch count for the current tab (txt2img or img2img)
     * Automatically detects which tab is active
     * @param {number} count - Number of images to generate per batch
     * @returns {Promise<void>}
     */
    async setBatchCount(count) {
        const isImg2ImgTab = this.adapter.isImg2ImgTab();

        if (isImg2ImgTab) {
            await this.adapter.setInputValue('IMG2IMG_BATCH_COUNT', count);
        } else {
            await this.adapter.setInputValue('TXT2IMG_BATCH_COUNT', count);
        }
    }

    // ==================== IMAGE PARAMETERS (upscaling, varying steps / denoising) ====================

    /**
     * Backup everything applyImageParameters() may change: the shown tab, UI preset, checkpoint, VAE / Text Encoder,
     * clip skip, txt2img prompts and parameters and its Hires. fix
     * @returns {Promise<Object>}
     */
    async backupImageParams() {
        return {
            tab: this.adapter.isImg2ImgTab() ? 'img2img' : 'txt2img',
            uiPreset: this.adapter.getInputValue('FORGE_UI_PRESET'),
            model: this.adapter.getInputValue('MODEL_CHECKPOINT'),
            modules: this.getModules(),
            clipSkip: this.adapter.getInputValue('CLIP_SKIP'),
            txt2img: this.captureTabParams('TXT2IMG'),
            hires: this.captureHiresParams()
        };
    }

    /**
     * Restore the parameters saved by backupImageParams()
     * @param {Object} backup
     * @returns {Promise<void>}
     */
    async restoreImageParams(backup) {
        if (!backup) {
            return;
        }

        // The preset resets the sampling parameters, so it goes first
        if (isSet(backup.uiPreset)) {
            await this.setUiPreset(backup.uiPreset);
        }

        if (backup.model) {
            await this.restoreModel(backup.model);
        }

        // The preset sets its own modules
        await this.restoreModules(backup.modules);

        this.setClipSkip(backup.clipSkip);
        await this.applyTabParams('TXT2IMG', backup.txt2img);
        await this.applyHiresParams(backup.hires);
        await this.showGenerationTab(backup.tab);
    }

    /**
     * Set all generation parameters of an image (its infotext parameters) in txt2img, which is shown.
     * Upscaling uses the Hires. fix settings of WebUI, otherwise the image's Hires. fix is reproduced
     * @param {Object} parameters - Image parameters object
     * @param {Object} options - { upscale: boolean, setDenoising: boolean (denoising of the parameters) }
     * @returns {Promise<void>}
     */
    async applyImageParameters(parameters, options = {}) {
        await this.showGenerationTab('txt2img');

        const model = parameters['model'];
        if (model && !String(this.adapter.getInputValue('MODEL_CHECKPOINT') ?? '').includes(model)) {
            // The preset resets the sampling parameters, which are set below
            await this.applyUiPresetForModel(model);
            await this.restoreModel(model);
        }

        // Images without modules in the infotext keep those of the preset
        const modules = getImageModules(parameters);

        if (modules.length) {
            await this.setModules(modules);
        }

        // WebUI omits the default clip skip from the infotext
        this.setClipSkip(parameters['clip skip'] ?? 1);

        const size = String(parameters['size'] ?? '').match(/^(\d+)x(\d+)$/);
        const subseedStrength = Number(parameters['variation seed strength'] ?? 0);
        const sliderKind = this.getDistilledCfgSliderKind();
        const hiresFix = options.upscale || 'hires upscale' in parameters;
        const setDenoising = options.setDenoising || (!options.upscale && hiresFix);

        await this.applyTabParams('TXT2IMG', {
            prompt: parameters['prompt'] ?? '',
            negativePrompt: parameters['negative prompt'] ?? '',
            sampler: parameters['sampler'],
            scheduler: parameters['schedule type'],
            steps: parameters['steps'],
            cfg: parameters['cfg scale'],
            distilledCfg: sliderKind === 'shift' ? parameters['shift']
                : sliderKind === 'distilledCfg' ? parameters['distilled cfg scale']
                : undefined,
            width: size?.[1],
            height: size?.[2],
            seed: parameters['seed'],
            subseed: parameters['variation seed'],
            subseedStrength,
            subseedShow: subseedStrength > 0 ? true : undefined,
            denoising: setDenoising ? parameters['denoising strength'] : undefined
        });

        await this.applyHiresParams(options.upscale ? {hiresFix} : {
            hiresFix,
            scale: parameters['hires upscale'],
            steps: hiresFix ? parameters['hires steps'] ?? 0 : undefined,
            upscaler: parameters['hires upscaler']
        });
    }

    /**
     * @returns {Object} Hires. fix of txt2img: { hiresFix, scale, steps, upscaler }
     */
    captureHiresParams() {
        return {
            hiresFix: this.adapter.getElement('HIRES_CHECKBOX')?.checked ?? null,
            scale: this.adapter.getInputValue('HIRES_SCALE'),
            steps: this.adapter.getInputValue('HIRES_STEPS'),
            upscaler: this.adapter.getInputValue('HIRES_UPSCALER')
        };
    }

    /**
     * Apply Hires. fix parameters captured by captureHiresParams(); unset ones are left untouched
     * @param {Object} params
     * @returns {Promise<void>}
     */
    async applyHiresParams(params) {
        const differs = (key, value) => isSet(value)
            && String(this.adapter.getInputValue(key)) !== String(value);

        if (differs('HIRES_SCALE', params.scale)) {
            this.adapter.setInputValue('HIRES_SCALE', params.scale);
        }

        if (differs('HIRES_STEPS', params.steps)) {
            this.adapter.setInputValue('HIRES_STEPS', params.steps);
        }

        if (differs('HIRES_UPSCALER', params.upscaler)) {
            await this.adapter.setDropdownValue('HIRES_UPSCALER', params.upscaler, true);
        }

        if (isSet(params.hiresFix)) {
            this.adapter.toggleHiresFix(params.hiresFix, !params.hiresFix);
        }
    }

    /**
     * Set the clip skip setting if it is shown in the quick settings and differs
     * @param {number|string|null} value
     */
    setClipSkip(value) {
        const current = this.adapter.getInputValue('CLIP_SKIP');

        if (isSet(value) && current !== null && String(current) !== String(value)) {
            this.adapter.setInputValue('CLIP_SKIP', value);
        }
    }

    /**
     * Backup current model
     * @returns {Promise<string>} Current model name
     */
    async backupModel() {
        return await this.adapter.getInputValue('MODEL_CHECKPOINT');
    }

    /**
     * Restore/set model
     * @param {string} modelName - Model name to set
     * @returns {Promise<void>}
     */
    async restoreModel(modelName) {
        await this.adapter.setDropdownValue('MODEL_CHECKPOINT', modelName);
    }

    /**
     * VAE / Text Encoder modules chosen in Forge Neo
     * @returns {string[]|null} File names, null if WebUI has no modules dropdown
     */
    getModules() {
        return this.adapter.getMultiselectValues(SELECTORS.FORGE_MODULES_ID);
    }

    /**
     * Choose exactly the given VAE / Text Encoder modules; nothing changes if one of them is not available
     * @param {string[]} modules - File names, with or without the extension
     * @returns {Promise<boolean>} Whether the modules are set
     */
    async setModules(modules) {
        const current = this.getModules();

        if (current === null || !Array.isArray(modules)) {
            return false;
        }

        const stripExtension = name => name.replace(MODULE_EXTENSION, '');
        const key = list => list.map(stripExtension).sort().join('|');

        if (key(current) === key(modules)) {
            return true;
        }

        const set = await this.adapter.setMultiselectValues(SELECTORS.FORGE_MODULES_ID, modules);
        await this.adapter.sleep(333);
        return set;
    }

    /**
     * Restore the modules returned by getModules()
     * @param {string[]|null} modules
     * @returns {Promise<void>}
     */
    async restoreModules(modules) {
        if (Array.isArray(modules)) {
            await this.setModules(modules);
        }
    }

    /**
     * Backup current Forge UI preset
     * @returns {Promise<string|null>} Current preset value or null if absent
     */
    async backupUiPreset() {
        return this.adapter.getInputValue('FORGE_UI_PRESET');
    }

    /**
     * Restore/set Forge UI preset
     * @param {string} preset - Preset value to set
     * @returns {Promise<void>}
     */
    async restoreUiPreset(preset) {
        if (preset) {
            await this.setUiPreset(preset);
        }
    }

    /**
     * Select the Forge UI preset matching the given model name
     * A preset matches if its search term is contained in the model name;
     * the longest matching term wins (e.g. "klein" over "flux")
     * @param {string} modelName - Model title as it appears in the model list
     * @returns {Promise<void>}
     */
    async applyUiPresetForModel(modelName) {
        if (!modelName || !this.adapter.getElement('FORGE_UI_PRESET')) {
            return;
        }

        const name = modelName.toLowerCase().replace(/\\/g, '/');
        let bestPreset = null;
        let bestTerm = '';

        for (const preset of this.getUiPresetChoices()) {
            const term = (UI_PRESET_SEARCH_TERMS[preset] ?? preset).toLowerCase();

            if (name.includes(term) && term.length > bestTerm.length) {
                bestPreset = preset;
                bestTerm = term;
            }
        }

        if (bestPreset) {
            await this.setUiPreset(bestPreset);
        }
    }

    /**
     * Set Forge UI preset only if it differs from the current value
     * @param {string} preset - Preset value to set
     * @returns {Promise<void>}
     */
    async setUiPreset(preset) {
        const current = this.adapter.getInputValue('FORGE_UI_PRESET');

        if (current === null || current === preset) {
            return;
        }

        this.uiPresetSwitches++;

        try {
            await this.adapter.setDropdownValue('FORGE_UI_PRESET', preset);
            await this.waitForUiPresetApplied();
        }
        finally {
            this.uiPresetSwitches--;
        }
    }

    /**
     * Whether a UI preset is being switched
     * @returns {boolean}
     */
    isSwitchingUiPreset() {
        return this.uiPresetSwitches > 0;
    }

    /**
     * Wait until Forge has set the controls of a newly selected UI preset: they changed and stayed unchanged
     * for a while, or did not change at all in the first moments (the presets share the values)
     * @returns {Promise<void>}
     */
    async waitForUiPresetApplied() {
        const signature = () => UI_PRESET_DEPENDENT_KEYS.map(key => this.adapter.getInputValue(key)).join('\n');
        const start = Date.now();
        let last = signature();
        let changedAt = null;

        while (Date.now() - start < UI_PRESET_TIMEOUT) {
            await this.adapter.sleep(100);
            const current = signature();

            if (current !== last) {
                last = current;
                changedAt = Date.now();
            }
            else if (changedAt ? Date.now() - changedAt >= UI_PRESET_SETTLE_TIME
                    : Date.now() - start >= UI_PRESET_FIRST_CHANGE_TIME)
                return;
        }
    }

    /**
     * Get available Forge UI preset choices from Gradio config
     * @returns {string[]}
     */
    getUiPresetChoices() {
        const components = window.gradio_config?.components ?? [];
        const component = components.find(c => c.props?.elem_id === SELECTORS.FORGE_UI_PRESET_ID);
        const choices = component?.props?.choices?.map(c => Array.isArray(c) ? c[1] : c);

        return choices?.length ? choices : DEFAULT_UI_PRESETS;
    }

    /**
     * Get txt2img prompt
     * @returns {Promise<string|null>}
     */
    async getPrompt() {
        return this.adapter.getInputValue('TXT2IMG_PROMPT');
    }

    /**
     * Set txt2img prompt
     * @param {string} text
     * @returns {Promise<void>}
     */
    async setPrompt(text) {
        this.adapter.setInputValue('TXT2IMG_PROMPT', text);
    }

    /**
     * LoRA loader nodes are a ComfyUI concept; SD WebUI applies explored LoRAs through the prompt (<lora:...>)
     */
    async backupLora() {
        return null;
    }

    async setLora(lora) {}

    async restoreLora(backup) {}

    /**
     * Apply per-model generation parameters to txt2img
     * Unset (undefined/null/empty) parameters are left untouched
     * @param {Object} params - { sampler, scheduler, steps, shift, cfg, distilledCfg }
     * @returns {Promise<void>}
     */
    async applyGenerationParams(params) {
        if (!params) {
            return;
        }

        const isSet = value => value !== undefined && value !== null && value !== '';

        if (isSet(params.sampler)) {
            await this.adapter.setDropdownValue('TXT2IMG_SAMPLING', params.sampler, true);
        }

        if (isSet(params.scheduler)) {
            await this.adapter.setDropdownValue('TXT2IMG_SCHEDULER', params.scheduler, true);
        }

        if (isSet(params.steps)) {
            this.adapter.setInputValue('TXT2IMG_STEPS', params.steps);
        }

        if (isSet(params.cfg)) {
            this.adapter.setInputValue('TXT2IMG_CFG_SCALE', params.cfg);
        }

        // Shift and Distilled CFG share one slider, relabeled (or hidden) by the Forge UI preset
        const sliderKind = this.getDistilledCfgSliderKind();
        const sliderValue = sliderKind === 'shift' ? params.shift
            : sliderKind === 'distilledCfg' ? params.distilledCfg
            : undefined;

        if (isSet(sliderValue)) {
            this.adapter.setInputValue('TXT2IMG_DISTILLED_CFG', sliderValue);
        }
    }

    /**
     * Backup txt2img generation parameters affected by applyGenerationParams()
     * @returns {Promise<Object>}
     */
    async backupGenerationParams() {
        const params = {
            sampler: this.adapter.getInputValue('TXT2IMG_SAMPLING'),
            scheduler: this.adapter.getInputValue('TXT2IMG_SCHEDULER'),
            steps: this.adapter.getInputValue('TXT2IMG_STEPS'),
            cfg: this.adapter.getInputValue('TXT2IMG_CFG_SCALE')
        };

        const sliderKind = this.getDistilledCfgSliderKind();
        if (sliderKind) {
            params[sliderKind] = this.adapter.getInputValue('TXT2IMG_DISTILLED_CFG');
        }

        return params;
    }

    /**
     * Restore txt2img generation parameters saved by backupGenerationParams()
     * @param {Object} backup
     * @returns {Promise<void>}
     */
    async restoreGenerationParams(backup) {
        await this.applyGenerationParams(backup);
    }

    /**
     * Capture txt2img and img2img prompts and parameters to be restored after a WebUI reload
     * Model, VAE and clip skip are omitted, as WebUI persists them in its settings; the seeds are not remembered
     * @returns {Object} { uiPreset, txt2img, img2img }
     */
    captureUiParams() {
        const hires = this.captureHiresParams();

        return {
            uiPreset: this.adapter.getInputValue('FORGE_UI_PRESET'),
            txt2img: {
                ...withoutUnremembered(this.captureTabParams('TXT2IMG')),
                hiresFix: hires.hiresFix,
                hiresScale: hires.scale,
                hiresSteps: hires.steps,
                hiresUpscaler: hires.upscaler
            },
            img2img: withoutUnremembered(this.captureTabParams('IMG2IMG'))
        };
    }

    /**
     * Capture prompts and parameters of a generation tab
     * @param {'TXT2IMG'|'IMG2IMG'} tab - Selector key prefix of the tab
     * @returns {Object}
     */
    captureTabParams(tab) {
        const params = {};

        for (const [name, suffix] of Object.entries(TAB_PARAM_SELECTORS)) {
            params[name] = this.adapter.getInputValue(`${tab}_${suffix}`);
        }

        params.distilledCfg = this.getDistilledCfgSliderKind(tab)
            ? this.adapter.getInputValue(`${tab}_DISTILLED_CFG`)
            : null;
        params.subseedShow = this.adapter.getElement(`${tab}_SUBSEED_SHOW`)?.checked ?? null;

        return params;
    }

    /**
     * Apply prompts and parameters captured by captureUiParams()
     * @param {Object} params
     * @returns {Promise<void>}
     */
    async applyUiParams(params) {
        if (!params) {
            return;
        }

        // The preset relabels or hides the distilled CFG sliders, so it goes first
        if (isSet(params.uiPreset)
                && this.adapter.getInputValue('FORGE_UI_PRESET') !== params.uiPreset) {
            await this.setUiPreset(params.uiPreset);
        }

        // Parameters saved by earlier versions may still hold the seeds
        await this.applyTabParams('TXT2IMG', withoutUnremembered(params.txt2img));
        await this.applyTabParams('IMG2IMG', withoutUnremembered(params.img2img));

        await this.applyHiresParams({
            hiresFix: params.txt2img?.hiresFix,
            scale: params.txt2img?.hiresScale,
            steps: params.txt2img?.hiresSteps,
            upscaler: params.txt2img?.hiresUpscaler
        });
    }

    /**
     * Apply prompts and parameters captured by captureTabParams()
     * Unset (undefined/null) parameters and those equal to the current values are left untouched
     * @param {'TXT2IMG'|'IMG2IMG'} tab - Selector key prefix of the tab
     * @param {Object} params
     * @returns {Promise<void>}
     */
    async applyTabParams(tab, params) {
        if (!params) {
            return;
        }

        const differs = (key, value) => isSet(value)
            && String(this.adapter.getInputValue(key)) !== String(value);

        for (const [name, suffix] of Object.entries(TAB_PARAM_SELECTORS)) {
            const key = `${tab}_${suffix}`;

            if (!differs(key, params[name])) {
                continue;
            }

            if (TAB_DROPDOWN_PARAMS.includes(name)) {
                await this.adapter.setDropdownValue(key, params[name], true);
            } else {
                this.adapter.setInputValue(key, params[name]);
            }
        }

        if (differs(`${tab}_DISTILLED_CFG`, params.distilledCfg) && this.getDistilledCfgSliderKind(tab)) {
            this.adapter.setInputValue(`${tab}_DISTILLED_CFG`, params.distilledCfg);
        }

        // The checkbox setter only acts if the state differs
        if (isSet(params.subseedShow)) {
            this.adapter.setCheckboxValue(`${tab}_SUBSEED_SHOW`, params.subseedShow);
        }
    }

    /**
     * Determine what the Forge distilled CFG slider currently controls
     * @param {'TXT2IMG'|'IMG2IMG'} tab - Selector key prefix of the tab
     * @returns {'shift'|'distilledCfg'|null} null if the slider is absent or hidden
     */
    getDistilledCfgSliderKind(tab = 'TXT2IMG') {
        const block = document.getElementById(SELECTORS[`${tab}_DISTILLED_CFG_ID`]);

        if (!block || getComputedStyle(block).display === 'none') {
            return null;
        }

        return block.textContent.includes('Shift') ? 'shift' : 'distilledCfg';
    }

    /**
     * Check that the current tab is ready to generate: the generate button is shown
     * and neither the interrupt nor the "Interrupting..." button is.
     * Newer WebUI versions overlay the interrupt button instead of hiding the generate button,
     * so the generate button alone is not enough. Rendered boxes are checked instead of
     * the inline style, because the buttons may be hidden by stylesheets.
     * @returns {boolean}
     */
    isReadyToGenerate() {
        const tab = this.adapter.isImg2ImgTab() ? 'IMG2IMG' : 'TXT2IMG';
        const isShown = (key) => {
            const element = this.adapter.getElement(key);
            return !!element && element.getClientRects().length > 0;
        };

        return isShown(`${tab}_GENERATE`)
            && !isShown(`${tab}_INTERRUPT`)
            && !isShown(`${tab}_INTERRUPTING`);
    }

    /**
     * Wait until the current tab is ready to generate
     * The previous job may still be finishing when its image is saved
     * @param {number} timeout - Maximum wait in milliseconds
     * @returns {Promise<boolean>} Whether the UI became ready in time
     */
    async waitReadyToGenerate(timeout = 30000) {
        const deadline = Date.now() + timeout;

        while (!this.isReadyToGenerate()) {
            if (Date.now() >= deadline)
                return false;

            await this.sleep(250);
        }

        return true;
    }

    /**
     * Click the generate button for the current tab, once it is ready to generate
     * Automatically detects which tab is active and clicks the appropriate button
     * @returns {Promise<boolean>} Whether the button was clicked
     */
    async clickGenerate() {
        if (!await this.waitReadyToGenerate()) {
            console.warn('[UIOperations] Generation is still running or being interrupted, generate is not clicked');
            return false;
        }

        const isImg2ImgTab = this.adapter.isImg2ImgTab();
        const buttonKey = isImg2ImgTab ? 'IMG2IMG_GENERATE' : 'TXT2IMG_GENERATE';
        this.adapter.getElement(buttonKey).click();
        return true;
    }

    /**
     * Start WebUI "Generate forever" on the current tab, or cancel it on both tabs.
     * Its implementation differs between WebUI versions and is not exposed globally,
     * so the entry of the generate button context menu is clicked instead
     * @param {boolean} enable - Start or cancel
     * @returns {boolean} Whether the menu entry was found
     */
    setGenerateForever(enable) {
        const currentTab = this.adapter.isImg2ImgTab() ? 'IMG2IMG' : 'TXT2IMG';
        const tabs = enable ? [currentTab] : ['TXT2IMG', 'IMG2IMG'];
        const entryName = enable ? 'Generate forever' : 'Cancel generate forever';
        const root = window.gradioApp?.() || document;
        let found = false;

        for (const tab of tabs) {
            const button = this.adapter.getElement(`${tab}_GENERATE`);

            if (!button)
                continue;

            button.dispatchEvent(new MouseEvent('contextmenu',
                {bubbles: true, cancelable: true, composed: true, view: window}));

            const menu = root.querySelector('#context-menu');
            const entry = Array.from(menu?.querySelectorAll('a') || [])
                .find(a => a.textContent.trim() === entryName);

            entry?.click();
            menu?.remove();
            found ||= !!entry;
        }

        return found;
    }

    /**
     * Set up basic generation parameters (seed and batch count)
     * @param {number} seed - Seed value (-1 for random)
     * @param {number} batchCount - Number of images per batch
     * @returns {Promise<void>}
     */
    async setupBasicGeneration(seed, batchCount) {
        await this.adapter.setInputValue('TXT2IMG_SEED', seed);
        await this.setBatchCount(batchCount);
    }

    // ==================== LOW-LEVEL UTILITIES ====================

    /**
     * Get the value of an input element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {Promise<string|number|null>}
     */
    async getInputValue(selectorKey) {
        return this.adapter.getInputValue(selectorKey);
    }

    /**
     * Set the value of an input element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {string|number} value - The value to set
     * @returns {Promise<void>}
     */
    async setInputValue(selectorKey, value) {
        return await this.adapter.setInputValue(selectorKey, value);
    }

    /**
     * Set the value of a dropdown element
     * @param {string} selectorKey - Key from SELECTORS constant
     * @param {string} value - The value to select
     * @returns {Promise<void>}
     */
    async setDropdownValue(selectorKey, value) {
        return await this.adapter.setDropdownValue(selectorKey, value);
    }

    /**
     * Get element by selector key
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {HTMLElement|null}
     */
    getElement(selectorKey) {
        return this.adapter.getElement(selectorKey);
    }

    /**
     * Get all elements matching selector key
     * @param {string} selectorKey - Key from SELECTORS constant
     * @returns {NodeList|Array}
     */
    getAllElements(selectorKey) {
        return this.adapter.getAllElements(selectorKey);
    }

    /**
     * Check if currently on img2img tab
     * @returns {boolean}
     */
    isImg2ImgTab() {
        return this.adapter.isImg2ImgTab();
    }

    /**
     * Check if an element is visible
     * @param {HTMLElement} element - The element to check
     * @returns {boolean}
     */
    isElementVisible(element) {
        return this.adapter.isElementVisible(element);
    }

    /**
     * Get current generation progress percentage
     * @returns {number|null} Progress from 0-100, or null if not available
     */
    getGenerationProgress() {
        return this.adapter.getGenerationProgress();
    }

    /**
     * Toggle hires fix checkbox
     * @param {boolean} onlyEnable - Only enable, don't toggle off
     * @param {boolean} onlyDisable - Only disable, don't toggle on
     */
    toggleHiresFix(onlyEnable = false, onlyDisable = false) {
        this.adapter.toggleHiresFix(onlyEnable, onlyDisable);
    }

    /**
     * Insert an image into the inpaint upload tab of img2img, switching to it
     * @param {'image'|'mask'} kind - Whether the file is the image or the inpainting mask
     * @param {File} file - Image file
     * @returns {Promise<boolean>} Whether the image component was found
     */
    async setInpaintUploadImage(kind, file) {
        this.adapter.switchToInpaintUploadTab();

        // Let Gradio render the tab before replacing its image
        await this.sleep(100);

        const selectorKey = kind === 'mask' ? 'IMG2IMG_INPAINT_UPLOAD_MASK' : 'IMG2IMG_INPAINT_UPLOAD_IMAGE';
        return this.adapter.setImageFile(selectorKey, file);
    }

    /**
     * Sleep for specified milliseconds
     * @param {number} ms - Milliseconds to sleep
     * @returns {Promise<void>}
     */
    async sleep(ms) {
        return await this.adapter.sleep(ms);
    }

    /**
     * Get the platform identifier
     * @returns {string} Platform identifier ('webui')
     */
    getPlatform() {
        return 'webui';
    }
}
