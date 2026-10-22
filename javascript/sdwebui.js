import {getGenerationState, setGenerationState} from "./shared/state.js";
import {messageBus} from "./shared/messaging/MessageBus.js";
import {sleep} from "./shared/utils.js";
import {SELECTORS, getElementById, querySelector} from "./adapters/selectors.js";
import {adapter} from "./adapters/adapter.js";
import {getImageModules} from "./facade/UIOperations.js";

// Dependencies injected from core.js
let sendPopupMessage;
let checkWebSocketConnection;

export function hookIntoSDWebUI(sendPopupFn, checkWebSocketFn) {
    // Store dependencies
    sendPopupMessage = sendPopupFn;
    checkWebSocketConnection = checkWebSocketFn;
    const txt2ImgGenerateButton = getElementById(SELECTORS.TXT2IMG_GENERATE);
    txt2ImgGenerateButton.addEventListener("mousedown", onGenerateMousedown);

    const img2ImgGenerateButton = getElementById(SELECTORS.IMG2IMG_GENERATE);
    img2ImgGenerateButton.addEventListener("mousedown", onGenerateMousedown);

    // Both tabs: stopGeneration() sends mousedown to the shown one
    for (const id of [SELECTORS.TXT2IMG_INTERRUPT, SELECTORS.IMG2IMG_INTERRUPT])
        getElementById(id).addEventListener("mousedown", onInterruptMousedown);
    listenInterruptButtonMutations();

    // "input" also fires when Image Bench sets the prompts (SDWebuiAdapter.setInputElementValue), "change" does not
    const promptInput = querySelector(SELECTORS.TXT2IMG_PROMPT);
    promptInput.addEventListener("input", onPromptChange);

    const negativePromptInput = querySelector(SELECTORS.TXT2IMG_NEG_PROMPT);
    negativePromptInput.addEventListener("input", onNegativePromptChange);

    const sendToTxt2ImgButton = querySelector(SELECTORS.SEND_TO_TXT2IMG);
    sendToTxt2ImgButton.addEventListener("click", onSendToTxt2ImgButtonClick);
}

function listenInterruptButtonMutations() {
    const txt2imgInterrupt = getElementById(SELECTORS.TXT2IMG_INTERRUPT);
    const img2imgInterrupt = getElementById(SELECTORS.IMG2IMG_INTERRUPT);

    setMutationListener(txt2imgInterrupt);
    setMutationListener(img2imgInterrupt);

    function setMutationListener(element) {
        const config = { attributes: true, attributeFilter: ['style'] };
        const callback = async function(mutationsList, observer) {
            for (const mutation of mutationsList) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
                    if (mutation.target.style.cssText.includes("display: none"))
                        if (getGenerationState() === "BATCH_GENERATION") {
                            messageBus.publish('BATCH_GENERATION_FINISHED');
                        }
                }
            }
        };

        const observer = new MutationObserver(callback);

        observer.observe(element, config);
    }
}

export function initializePopupPrompts(sendPopupFn) {
    // Use injected dependency if provided (for direct calls)
    const messageSender = sendPopupFn || sendPopupMessage;
    const promptInput = querySelector(SELECTORS.TXT2IMG_PROMPT);
    const negativePromptInput = querySelector(SELECTORS.TXT2IMG_NEG_PROMPT);
    onPromptChange({target: promptInput}, messageSender);
    onNegativePromptChange({target: negativePromptInput}, messageSender);
}

function onGenerateMousedown(e) {
    checkWebSocketConnection();
    setGenerationState("BATCH_GENERATION");
    // Started in WebUI: the popup flashes the Generated tab instead of switching to it
    sendPopupMessage({type: "BEGIN_PROCESSING", host: true});
}

async function onInterruptMousedown(e) {
    // Request to finish current active strategy via message bus
    messageBus.publish('STRATEGY_FINISH_REQUEST');
}

function onPromptChange(e, messageSender) {
    const sender = messageSender || sendPopupMessage;
    sender({type: "PROMPT_CHANGE", text: e.target.value});
}

function onNegativePromptChange(e, messageSender) {
    const sender = messageSender || sendPopupMessage;
    sender({type: "NEGATIVE_PROMPT_CHANGE", text: e.target.value});
}

function onSendToTxt2ImgButtonClick(e) {
    messageBus.publish('EXPLORATION_INVALIDATE');
}

export async function stopGeneration() {
    const mousedownEvent = new MouseEvent('mousedown', {
        bubbles: true,
        cancelable: true,
        view: window,
        button: 0
    });

    const txt2ImgInterruptButton = getElementById(SELECTORS.TXT2IMG_INTERRUPT);
    const img2ImgInterruptButton = getElementById(SELECTORS.IMG2IMG_INTERRUPT);
    const interruptButton = txt2ImgInterruptButton.offsetParent === null
        ? img2ImgInterruptButton
        : txt2ImgInterruptButton;

    interruptButton.dispatchEvent(mousedownEvent);
    if (adapter.isElementVisible(interruptButton))
        interruptButton.click();

    await sleep(333);

    if (adapter.isElementVisible(interruptButton))
        interruptButton.click();
}

/**
 * Skip the image being generated; WebUI continues with the next image of the batch
 */
export function skipGeneration() {
    const skipButton = getElementById(adapter.isImg2ImgTab() ? SELECTORS.IMG2IMG_SKIP : SELECTORS.TXT2IMG_SKIP);
    skipButton?.click();
}

export async function repositionConfigPresetsDropdown(kind) {
    const configPresetsDiv = getElementById(SELECTORS.CONFIG_PRESET_WRAPPER(kind));

    if (configPresetsDiv) {
        const resultsDiv = getElementById(SELECTORS.RESULTS_DIV(kind));

        configPresetsDiv.parentNode.removeChild(configPresetsDiv);
        resultsDiv.insertBefore(configPresetsDiv, resultsDiv.firstChild);
    }
}

/**
 * Civitai page and metadata of the selected checkpoint (the backend hashes it if needed)
 * @returns {Promise<{found: boolean, url?: string, searchUrl?: string, error?: string}>}
 */
export async function fetchCurrentModelInfo() {
    try {
        const response = await fetch("/image-bench/civitai/model_info?kind=checkpoint");

        if (response.ok)
            return await response.json();

        return {found: false, error: `Request failed: ${response.status} ${response.statusText}`};
    } catch (e) {
        return {found: false, error: `Request failed: ${e.message}`};
    }
}

export async function setConfigPreset(preset) {
    const presetDropdown = querySelector(SELECTORS.CONFIG_PRESET_TXT2IMG_DROPDOWN);

    if (presetDropdown) {
        if (presetDropdown.value === preset) {
            await adapter.setDropdownValue('CONFIG_PRESET_TXT2IMG_DROPDOWN', "None");
            await sleep(333);
        }

        await adapter.setDropdownValue('CONFIG_PRESET_TXT2IMG_DROPDOWN', preset);
    }
}

export async function setImageSeed(options) {
    if (!options.parameters)
        return;

    const params = options.parameters;

    adapter.setInputValue('TXT2IMG_SEED', params["seed"]);

    if ("variation seed" in params)
        adapter.setInputValue('TXT2IMG_SUBSEED', params["variation seed"]);
}

export async function setImageParams(options) {
    const params = options.parameters;

    if (!params)
        return;

    if ("model" in params)
        await adapter.setDropdownValue('MODEL_CHECKPOINT', params["model"]);

    if ("vae" in params)
        await adapter.setDropdownValue('SD_VAE', params["vae"]);

    // VAE / Text Encoder of Forge Neo; images without them keep those of the preset
    const modules = getImageModules(params);

    if (modules.length)
        await adapter.setMultiselectValues(SELECTORS.FORGE_MODULES_ID, modules);

    if ("prompt" in params)
        adapter.setInputValue('TXT2IMG_PROMPT', params["prompt"]);
    else
        adapter.setInputValue('TXT2IMG_PROMPT', "");

    if ("negative prompt" in params)
        adapter.setInputValue('TXT2IMG_NEG_PROMPT', params["negative prompt"]);
    else
        adapter.setInputValue('TXT2IMG_NEG_PROMPT', "");

    if ("sampler" in params)
        await adapter.setDropdownValue('TXT2IMG_SAMPLING', params["sampler"]);

    if ("schedule type" in params)
        await adapter.setDropdownValue('TXT2IMG_SCHEDULER', params["schedule type"]);

    if ("steps" in params)
        adapter.setInputValue('TXT2IMG_STEPS', params["steps"]);

    if ("cfg scale" in params)
        adapter.setInputValue('TXT2IMG_CFG_SCALE', params["cfg scale"]);

    if ("seed" in params)
        adapter.setInputValue('TXT2IMG_SEED', params["seed"]);

    if ("variation seed" in params) {
        adapter.setInputValue('TXT2IMG_SUBSEED', params["variation seed"]);
        adapter.setInputValue('TXT2IMG_SUBSEED_STRENGTH', params["variation seed strength"]);
    }

    if ("size" in params && params["size"].includes("x")) {
        const sizes = params["size"].split("x");
        adapter.setInputValue('TXT2IMG_WIDTH', sizes[0]);
        adapter.setInputValue('TXT2IMG_HEIGHT', sizes[1]);
    }

    if ("clip skip" in params)
        adapter.setInputValue('CLIP_SKIP', params["clip skip"]);

    if ("denoising strength" in params)
        adapter.setInputValue('TXT2IMG_DENOISING', params["denoising strength"]);

    if ("hires steps" in params)
        adapter.setInputValue('HIRES_SCALE', params["hires steps"]);

    if ("hires upscale" in params) {
        adapter.setInputValue('HIRES_SCALE', params["hires upscale"]);
        adapter.toggleHiresFix(true);
    }
}
