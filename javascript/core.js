import {loadAppConfig} from "./shared/utils.js";
import {getGenerationState, setGenerationState} from "./shared/state.js";
import {createStrategies} from "./shared/strategy-factory.js";
import {createPopupManager, getEmbeddingWindow} from "./shared/popup.js";
import {showAppLinkDialog} from "./shared/appLink.js";
import {createWebSocket, isConnectionClosed} from "./shared/websocket.js";
import {
    fetchCurrentModelInfo,
    hookIntoSDWebUI,
    initializePopupPrompts,
    repositionConfigPresetsDropdown,
    setImageParams,
    setImageSeed,
    skipGeneration,
    stopGeneration
} from "./sdwebui.js";
import {adapter} from "./adapters/adapter.js";
import {UIOperations} from "./facade/UIOperations.js";
import {messageBus} from "./shared/messaging/MessageBus.js";
import {SELECTORS} from "./adapters/selectors.js";
import {restoreUiParams, saveUiParams} from "./persistence.js";
import {initControlNetPreviewButtons, initEditorBridge} from "./editor.js";
import {createHeaderButton} from "./utils_html.js";
import {createWebUIMirror} from "./mirror.js";
import {createControlNet} from "./controlnet.js";
import {createControlNetRecorder} from "./controlnetRecorder.js";

// Create popup manager instance (no WebSocket integration for WebUI)
const popupManager = createPopupManager({
    endpoint: '/image-bench/window',
    integrateWebSocket: false,
    windowName: '_blank',
    windowFeatures: 'width=1024,height=720,left=100,top=100'
});

// Create WebSocket state
let websocket = null;

// Helper to send popup messages
const sendPopupMessage = (msg) => popupManager.sendMessage(msg);

// Create UIOperations facade and strategies
const uiOperations = new UIOperations(adapter);
const strategies = createStrategies(uiOperations, sendPopupMessage);

// Extract strategy instances
const {exploration: explorationStrategy, batch: batchStrategy, processing: processingStrategy,
        varying: varyingStrategy, controlNetSweep: controlNetSweepStrategy} = strategies;

// txt2img parameters mirrored in the Generate tab of the popup
const mirror = createWebUIMirror(uiOperations, adapter, {sendMessage: sendPopupMessage, isOpen: popupManager.isOpen});
// ControlNet unit mirrored in the ControlNet tab of the popup, also the target of the ControlNet buttons of the editor plugin
const controlNet = createControlNet(uiOperations, adapter, {sendMessage: sendPopupMessage, isOpen: popupManager.isOpen},
    showAlert);
// ControlNet inputs of each generation, read when Generate is clicked and carried by its images
const controlNetRecorder = createControlNetRecorder(controlNet);

let appConfig;
let modelInfoButton;
let openButton;
// Where images sent from the editor go, set in the Generate tab of the popup: 'input' or 'reference'
let editorTarget = 'input';

export async function init() {
    setGenerationState("BATCH_GENERATION");
    appConfig = await loadAppConfig() || {};
    await initUI();

    window.addEventListener("message", onMessage);

    // Asked by the popup before it starts an operation
    window.imageBenchIsGenerationActive = isGenerationActive;

    // Close popup on page unload
    window.addEventListener("pagehide", () => {
        popupManager.close();
        fetch("/image-bench/close_websocket", {keepalive: true});
    });

    // Set up message bus event handlers
    setupMessageBusHandlers();

    // Receive images sent from the editor plugin
    initEditorBridge(onEditorImage, image => sendPopupMessage({type: "COMPARE_IMAGE", image}));
    initControlNetPreviewButtons(showAlert);

    // Only user clicks fire mousedown, strategies click the buttons programmatically
    for (const id of [SELECTORS.TXT2IMG_GENERATE, SELECTORS.IMG2IMG_GENERATE])
        document.getElementById(id)?.addEventListener("mousedown", saveGenerationParams);

    // Every generation clicks Generate (users, strategies, the popup and Generate Forever); the capture phase runs
    // before Gradio reads the inputs. The recorder only reads the DOM here and uploads in the background
    for (const [id, tab] of [[SELECTORS.TXT2IMG_GENERATE, 'txt2img'], [SELECTORS.IMG2IMG_GENERATE, 'img2img']])
        document.getElementById(id)?.addEventListener("click", () => {
            try {
                controlNetRecorder.capture(tab);
            } catch (error) {
                console.warn('[Image Bench] Unable to read the ControlNet units:', error);
            }
        }, true);

    // Embedded mode: this page is loaded in the iframe of the Image Bench window, which takes the place of the popup
    const embeddingWindow = getEmbeddingWindow();

    if (embeddingWindow && popupManager.attach(embeddingWindow))
        connectPopup();

    // The popup reloads this page when the backend is back after a restart (opener mode): the old page lets the
    // popup go, so its pagehide does not close it, and the new one takes it over
    window.imageBenchReleasePopup = () => popupManager.release();
    window.imageBenchAdoptPopup = (popup) => {
        if (popupManager.adopt(popup))
            connectPopup();
    };
}

/**
 * Save txt2img and img2img prompts and parameters when the user starts a generation or opens a project
 * The config is reloaded, since the setting may be changed in the popup
 */
async function saveGenerationParams() {
    const params = uiOperations.captureUiParams();
    appConfig = await loadAppConfig() || appConfig;

    if (appConfig.persistGenerationParams)
        saveUiParams(params);
}

/**
 * Get the currently active strategy based on generation state
 */
function getActiveStrategy() {
    const state = getGenerationState();
    
    if (state === "EXPLORE_MODELS") return explorationStrategy;
    if (state === "CONTROLNET_SWEEP") return controlNetSweepStrategy;
    if (state === "BATCH_GENERATION") return batchStrategy;
    if (state === "HIRES_FIX" || state === "SEQUENTIAL_GENERATION") {
        return processingStrategy.isProcessing() ? processingStrategy : varyingStrategy;
    }
    return null;
}

/**
 * Set up message bus event handlers for strategy control
 */
function setupMessageBusHandlers() {
    // Handle strategy finish requests
    messageBus.subscribe('STRATEGY_FINISH_REQUEST', async () => {
        const strategy = getActiveStrategy();
        if (strategy && strategy.isProcessing()) {
            await strategy.finish();
        }
        setGenerationState("BATCH_GENERATION");
    });
    
    // Handle exploration invalidation
    messageBus.subscribe('EXPLORATION_INVALIDATE', () => {
        explorationStrategy.invalidate();
    });
    
    // Handle batch generation finished notification
    messageBus.subscribe('BATCH_GENERATION_FINISHED', async () => {
        // "Generate forever" starts the next generation shortly after the previous one,
        // it has finished only if it was cancelled from the WebUI context menu
        if (batchStrategy.isProcessing() && batchStrategy.isForever) {
            await uiOperations.sleep(1500);

            if (!batchStrategy.isProcessing() || !uiOperations.isReadyToGenerate())
                return;
        }

        if (batchStrategy.isProcessing()) {
            await batchStrategy.finish();
        }
        sendPopupMessage({type: "GENERATION_FINISHED"});
    });
}

async function initUI() {
    //window.name = "sd-webui-main-window";
    //console.log(appConfig)
    // Let Gradio finish initializing its components before restoring
    if (appConfig?.persistGenerationParams)
        setTimeout(() => restoreUiParams(uiOperations), 1500);

    if (appConfig?.repositionConfigPresetsDropdown)
        setTimeout(async () => {
            await repositionConfigPresetsDropdown("txt2img");
            await repositionConfigPresetsDropdown("img2img");
        }, 2000);

    modelInfoButton = createHeaderButton('Civitai Model Info', "ℹ️", {}, onShowModelInfo,
        document.querySelector(SELECTORS.MODEL_REFRESH_BUTTON));
    openButton = createHeaderButton('Image Bench', "🔬",  {}, onShowWindow);
    updateHeaderButtons();
    // The settings may be changed in the popup, the user then returns to this window
    window.addEventListener("focus", async () => {
        appConfig = await loadAppConfig() || appConfig;
        updateHeaderButtons();
    });

    popupManager.dispose();
}

function updateHeaderButtons() {
    modelInfoButton.style.display = appConfig?.addModelInfoButton ? "" : "none";
    // Not in the iframe of Image Bench, which has its own tabs
    openButton.style.display = getEmbeddingWindow() ? "none" : "";
}

/**
 * Open the Civitai page of the selected checkpoint (or the search by name if the model is unknown to Civitai).
 * The button shows a spinner while the backend hashes the model and queries Civitai.
 */
async function onShowModelInfo() {
    if (modelInfoButton.disabled)
        return;

    // Opened before the request, so that it is not blocked as a popup without a user gesture
    const civitaiWindow = window.open("about:blank", "_blank");

    const icon = modelInfoButton.innerHTML;

    modelInfoButton.disabled = true;
    modelInfoButton.innerHTML = '<span class="image-bench-spinner"></span>';

    try {
        const info = await fetchCurrentModelInfo();

        if (info.found) {
            if (civitaiWindow)
                civitaiWindow.location = info.url;
            else
                window.open(info.url, "_blank");
        }
        else {
            civitaiWindow?.close();

            if (info.error)
                alert(info.error);
            else if (info.searchUrl && confirm(`'${info.name}' is not found on Civitai. Search by name?`))
                window.open(info.searchUrl, "_blank");
        }
    } finally {
        modelInfoButton.disabled = false;
        modelInfoButton.innerHTML = icon;
    }
}

async function onShowWindow() {
    // Image Bench is started by its link (/image-bench/app) unless it is set to be opened from here
    if (!appConfig?.openFromHostUI)
        return showAppLinkDialog("WebUI");

    if (popupManager.open())
        connectPopup();
}

/**
 * Forward the images of the backend to the popup, opened or attached
 */
function connectPopup() {
    createWebSocketConnection();
    hookIntoSDWebUI(sendPopupMessage, checkWebSocketConnection);
}

function createWebSocketConnection() {
    if (!websocket) {
        websocket = createWebSocket({
            endpoint: '/image-bench/websocket',
            onMessage: onBackendMessage
        });
    }
}

function checkWebSocketConnection() {
    if (isConnectionClosed(websocket)) {
        createWebSocketConnection();
        return false;
    }
    return true;
}

async function onMessage(msg) {
    checkWebSocketConnection();

    const payload = msg.data;

    if (payload.type === "INITIALIZE_PROMPTS")
        initializePopupPrompts(sendPopupMessage);
    else if (payload.type === "STOP_GENERATION")
        stopGeneration();
    else if (payload.type === "SKIP_GENERATION")
        skipGeneration();
    else if (payload.type === "EXPLORE_MODELS")
        await handleExploreModels(payload);
    else if (payload.type === "BATCH_GENERATE")
        await handleBatchGenerate(payload, appConfig);
    else if (payload.type === "GENERATE_VARIATIONS")
        await handleGenerateVariations(payload, appConfig);
    else if (payload.type === "UPSCALE_IMAGES")
        await handleProcessImages(payload);
    else if (payload.type === "SET_IMAGE_SEED")
        setImageSeed(payload)
    else if (payload.type === "SET_IMAGE_PARAMS")
        setImageParams(payload)
    else if (payload.type === "GENERATE_VARYING_STEPS" || payload.type === "GENERATE_VARYING_MODULES")
        await handleGenerateVaryingSteps(payload)
    else if (payload.type === "CONTROLNET_SWEEP")
        await handleControlNetSweep(payload);
    else if (payload.type === "UPSCALE_VARYING_DENOISING")
        await handleUpscaleVaryingDenoising(payload)
    else if (payload.type === "GENERATE_IMAGE")
        await handleGenerateImage(payload.mode)
    else if (payload.type === "MIRROR_SUBSCRIBE")
        mirror.subscribe(payload.active)
    else if (payload.type === "SET_WEBUI_PARAMS")
        await mirror.applyParams(payload.params)
    else if (payload.type === "REUSE_SEED")
        mirror.reuseSeed(payload.which)
    else if (payload.type === "LOCK_WEBUI_PROMPTS")
        mirror.setPromptsLocked(payload.locked)
    else if (payload.type === "SET_GENERATION_MODE")
        await mirror.setMode(payload.mode, payload.params)
    else if (payload.type === "SET_INPUT_IMAGE")
        await mirror.setInputImage(payload.kind, payload.file, payload.mode)
    else if (payload.type === "EDIT_REFERENCES")
        await mirror.editReferences(payload.edit)
    else if (payload.type === "SET_EDITOR_TARGET")
        editorTarget = payload.target
    else if (payload.type === "CONTROLNET_SUBSCRIBE")
        controlNet.subscribe(payload.active, payload.unit, payload.defaults !== false)
    else if (payload.type === "SET_CONTROLNET_PARAMS")
        await controlNet.applyParams(payload.unit, payload.params)
    else if (payload.type === "CONTROLNET_ACTION")
        await controlNet.runAction(payload.unit, payload.action)
    else if (payload.type === "SET_CONTROLNET_IMAGE")
        await controlNet.setUnitImage(payload.unit, payload.kind, payload.file)
    else if (payload.type === "SET_CONTROLNET_POSE")
        await controlNet.setPose(payload.unit, payload.pose)
    else if (payload.type === "SET_CONTROLNET_TAB")
        await controlNet.setTab(payload.tab)
    else if (payload.type === "REFRESH_MODELS")
        refreshModelLists()
    else if (payload.type === "PROJECT_CAPTURE")
        await respond(payload, captureProject)
    else if (payload.type === "PROJECT_RESTORE")
        await respond(payload, () => restoreProject(payload.snapshot))
}

/**
 * Answer a request of the popup with HOST_RESPONSE
 * @param {{requestId: number}} payload
 * @param {() => Promise<any>} handler
 */
async function respond(payload, handler) {
    try {
        sendPopupMessage({type: "HOST_RESPONSE", requestId: payload.requestId, result: await handler()});
    } catch (error) {
        console.error(error);
        sendPopupMessage({type: "HOST_RESPONSE", requestId: payload.requestId, error: error.message || String(error)});
    }
}

/**
 * Parameters of a project: those of the shown generation mode and the enabled ControlNet units of its tab
 * @returns {Promise<Object>}
 */
async function captureProject() {
    await mirror.settled();

    const {mode, params} = mirror.captureSnapshot();
    const tab = mode === 'txt2img' ? 'txt2img' : 'img2img';

    return {mode, params, controlnet: {tab, units: await controlNet.captureUnits(tab)}};
}

/**
 * Restore the parameters of a project captured by captureProject()
 * @param {Object} snapshot - {mode, params, controlnet: {units}} with the ControlNet images as files
 * @returns {Promise<{missingUnits: number[]}>}
 */
async function restoreProject({mode, params, controlnet}) {
    await mirror.restoreSnapshot(mode, params || {});

    const tab = mode === 'txt2img' ? 'txt2img' : 'img2img';
    const missingUnits = controlnet ? await controlNet.restoreUnits(tab, controlnet.units || []) : [];

    // A reload before the next generation restores the parameters of the project, not those of the last one
    await mirror.settled();
    await saveGenerationParams();

    return {missingUnits};
}

/**
 * Refresh the checkpoint dropdown and the LoRA cards of the extra networks pages, as their Refresh buttons do
 */
function refreshModelLists() {
    document.querySelector(SELECTORS.MODEL_REFRESH_BUTTON)?.click();
    document.querySelectorAll(SELECTORS.LORA_REFRESH_BUTTON)
        .forEach(button => button.dispatchEvent(new Event("click")));
}

/**
 * Put an image sent from the editor where the Generate tab of the popup routes it: a new reference image
 * of the shown generation tab, or the input of the shown mode. Without the popup, the input of img2img
 * if its img2img mode is shown, else the inpaint upload (the mask always goes there).
 * The ControlNet buttons of the plugin send to the unit shown in the ControlNet tab of the popup
 * @param {'image'|'mask'} kind
 * @param {File} file
 * @param {'input'|'cn_preprocess'|'cn_image'|'cn_mask'} target
 */
async function onEditorImage(kind, file, target) {
    if (target !== 'input') {
        await controlNet.onEditorImage(target, file);
        return;
    }

    if (kind === 'image' && editorTarget === 'reference' && popupManager.isOpen()) {
        await mirror.editReferences({add: [file]});
        return;
    }

    const mode = uiOperations.getGenerationMode() === 'img2img' && kind === 'image' ? 'img2img' : 'inpaint';
    await uiOperations.setInputImage(mode, kind, file);
}

/**
 * Show a message in the popup's dialog; native alert only if the popup is gone
 * @param {string} message
 */
function showAlert(message) {
    if (!sendPopupMessage({type: "SHOW_ALERT", message}))
        alert(message);
}

/**
 * Whether WebUI is generating or interrupting, or a strategy is running (also between its images,
 * while WebUI is momentarily idle)
 * @returns {boolean}
 */
function isGenerationActive() {
    return !uiOperations.isReadyToGenerate()
        || Object.values(strategies).some(strategy => strategy.isProcessing());
}

/**
 * Refuse to start a strategy while a generation is active, before the strategy changes any UI parameters
 * @returns {boolean} Whether the strategy may start
 */
function checkReadyToGenerate() {
    if (!isGenerationActive())
        return true;

    sendPopupMessage({type: "GENERATION_FINISHED"});
    showAlert("A generation is in progress. Please wait until it finishes or stop it.");
    return false;
}

async function handleExploreModels(options) {
    if (!options.models || !options.models.length) {
        return;
    }

    if (!checkReadyToGenerate())
        return;

    if (explorationStrategy.isInvalidated()) {
        sendPopupMessage({type: "GENERATION_FINISHED"});
        showAlert("'Send to Txt2Img' was used. Please reload WebUI to explore models.");
        return;
    }

    setGenerationState("EXPLORE_MODELS");
    return await explorationStrategy.process(options);
}

async function handleBatchGenerate(options, config) {
    if (!checkReadyToGenerate())
        return;

    // Started from the Generate tab: its mode, or the shown WebUI tab if it is another one
    if (options.mode !== undefined) {
        await prepareMode(options.mode);

        // The batch strategy randomizes the txt2img seed
        if (uiOperations.isImg2ImgTab())
            await uiOperations.setInputValue('IMG2IMG_SEED', -1);
    }

    setGenerationState("BATCH_GENERATION");
    return await batchStrategy.process({...options, config});
}

/**
 * Generate a single image from the Generate tab with the parameters as they are (seed included),
 * in its generation mode (txt2img, img2img or inpaint).
 * BEGIN_PROCESSING is marked single, so that the popup stays on the tab and shows the live preview.
 * @param {'txt2img'|'img2img'|'inpaint'|null} mode - null: the shown WebUI tab
 */
async function handleGenerateImage(mode) {
    if (!checkReadyToGenerate())
        return;

    await prepareMode(mode);
    setGenerationState("BATCH_GENERATION");
    await uiOperations.setBatchCount(1);
    await saveGenerationParams();
    sendPopupMessage({type: "BEGIN_PROCESSING", single: true});

    if (!await uiOperations.clickGenerate())
        sendPopupMessage({type: "GENERATION_FINISHED"});
}

/**
 * The Generate tab of the popup mirrors a generation mode and may have just sent its parameters:
 * apply them and show the WebUI tab of the mode, on which the strategies then detect and use its controls
 * @param {'txt2img'|'img2img'|'inpaint'|null} mode - null: the shown WebUI tab
 */
async function prepareMode(mode) {
    await mirror.settled();

    if (mode)
        await uiOperations.setGenerationMode(mode);
}

async function handleGenerateVariations(options, config) {
    if (!checkReadyToGenerate())
        return;

    if (options.mode !== undefined)
        await prepareMode(options.mode);

    setGenerationState("BATCH_GENERATION");
    return await batchStrategy.process({...options, config});
}

async function handleProcessImages(options) {
    if (!checkReadyToGenerate())
        return;

    setGenerationState(options?.setSteps ? "SEQUENTIAL_GENERATION" : "HIRES_FIX");
    return await processingStrategy.process(options);
}

async function handleGenerateVaryingSteps(options) {
    if (!checkReadyToGenerate())
        return;

    setGenerationState("SEQUENTIAL_GENERATION");
    return await varyingStrategy.process(options);
}

async function handleUpscaleVaryingDenoising(options) {
    if (!checkReadyToGenerate())
        return;

    setGenerationState("HIRES_FIX");
    return await varyingStrategy.process(options);
}

/**
 * Generate the matrix of ControlNet weights x ending steps of a unit of the shown generation tab
 * @param {Object} options - {unit, weights, ends, reference: {weight, end}}
 */
async function handleControlNetSweep(options) {
    if (!checkReadyToGenerate())
        return;

    // Edits the popup sent just before are applied first, so that the values restored after the sweep are theirs
    await controlNet.applyParams(options.unit, {});

    if (!controlNet.readParams(options.unit)) {
        sendPopupMessage({type: "GENERATION_FINISHED"});
        showAlert(`ControlNet unit ${options.unit + 1} is not found.`);
        return;
    }

    setGenerationState("CONTROLNET_SWEEP");
    return await controlNetSweepStrategy.process({...options, controlNet});
}

function isProcessingActive() {
    const generationState = getGenerationState();
    return generationState === "HIRES_FIX" || generationState === "SEQUENTIAL_GENERATION";
}

function onBackendMessage(e) {
    if (e?.data) {
        const msg = JSON.parse(e.data);

        // Set message parameters based on active strategy
        if (msg.type === "SAVED_IMAGE") {
            const strategy = getActiveStrategy();
            
            if (strategy && strategy.isProcessing())
                Object.assign(msg, strategy.getMessageParams());

            try {
                controlNetRecorder.attach(msg);
            } catch (error) {
                console.warn('[Image Bench] Unable to add the ControlNet units to the image:', error);
            }
        }

        sendPopupMessage(msg);

        // Process next item based on active strategy
        if (msg.type === "SAVED_IMAGE") {
            const strategy = getActiveStrategy();
            if (strategy && strategy.isProcessing()) {
                strategy.processNext();
            }
        }
    }
}
