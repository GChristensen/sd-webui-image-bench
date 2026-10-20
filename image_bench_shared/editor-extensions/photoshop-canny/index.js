/**
 * Canny Edges Photoshop plugin
 * Computes Canny edges (with an optional Gaussian blur, as cv2.GaussianBlur + cv2.Canny) of the merged image
 * or the active layer, previews them live and puts them into a layer or a new document
 */

const {entrypoints} = require("uxp");
const {action, app, constants, core, imaging} = require("photoshop");
const {toColorChannels, blurredGradients, cannyFromGradients, detectEdges, downscaleAverage} = require("./canny.js");

const SETTINGS_KEY = "cannySettings";
const DEFAULT_SETTINGS = {threshold1: 100, threshold2: 200, blur: 1, source: "merged", fastPreview: false, selectionOnly: false};
const PREVIEW_SIZE = 640;
const PREVIEW_DELAY = 50;
const REFRESH_DELAY = 200;
const MODAL_RETRIES = 10;
const MODAL_RETRY_DELAY = 300;
// Box width changes (CSS pixels) below this, e.g. a scroll bar shown or hidden, keep the rendered preview
const RESIZE_THRESHOLD = 24;
const HISTORY_NAME = "Canny Edges";

function loadSettings() {
    try {
        return {...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}")};
    } catch {
        return {...DEFAULT_SETTINGS};
    }
}

const settings = loadSettings();

function saveSettings() {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function getParams() {
    const {threshold1, threshold2, blur} = settings;
    return {threshold1, threshold2, blur};
}

function getLayerName({threshold1, threshold2, blur}) {
    return `Canny ${threshold1}/${threshold2} b${blur}`;
}

// ==================== PIXELS ====================

/**
 * Read 8-bit pixels of the whole document area, whatever the source bounds of the returned data are.
 * Must run in a modal scope
 * @param {Function} getPixels - Imaging API call returning {imageData, sourceBounds}
 * @param {Document} doc - Photoshop document
 * @returns {Promise<{data: Uint8Array, width: number, height: number, components: number}>}
 */
async function grabPixels(getPixels, doc) {
    const width = Math.round(doc.width);
    const height = Math.round(doc.height);
    const documentBounds = {left: 0, top: 0, right: width, bottom: height};

    const {imageData, sourceBounds} = await getPixels({
        documentID: doc.id,
        sourceBounds: documentBounds,
        componentSize: 8
    });

    try {
        const data = await imageData.getData({chunky: true});
        return placeOnCanvas(data, imageData, sourceBounds ?? documentBounds, width, height);
    } finally {
        imageData.dispose();
    }
}

/**
 * Put pixel data into a document-sized canvas (filled with zeros) at its source bounds
 * @returns {{data: Uint8Array, width: number, height: number, components: number}}
 */
function placeOnCanvas(data, imageData, bounds, width, height) {
    const components = imageData.components;

    if (bounds.left === 0 && bounds.top === 0 && imageData.width === width && imageData.height === height)
        return {data, width, height, components};

    const canvas = new Uint8Array(width * height * components);
    const rowLength = imageData.width * components;

    for (let y = 0; y < imageData.height; y++) {
        const row = data.subarray(y * rowLength, (y + 1) * rowLength);
        canvas.set(row, ((bounds.top + y) * width + bounds.left) * components);
    }

    return {data: canvas, width, height, components};
}

function getActiveDocument() {
    const doc = app.activeDocument;

    if (!doc)
        throw new Error("No document is open");

    return doc;
}

/**
 * The layer read in the "Active layer" mode, null for the merged image
 */
function getSourceLayer(doc) {
    if (settings.source !== "layer")
        return null;

    const layer = doc.activeLayers[0];

    if (!layer)
        throw new Error("No layer is selected");

    return layer;
}

function findLayer(layers, id) {
    for (const layer of layers ?? []) {
        if (layer.id === id)
            return layer;

        const found = findLayer(layer.layers, id);
        if (found)
            return found;
    }

    return null;
}

// ==================== SOURCE ====================

/**
 * The pixels edges are computed from: the full-size image, a copy downscaled for the preview and the full-size
 * edges of the last parameters
 * @type {{docId: number, layerId: number|null, full: Object, preview: Object, scale: number, fullEdges?: Object}|null}
 */
let source = null;

function getSourceKey(doc) {
    const layer = getSourceLayer(doc);
    return {docId: doc.id, layerId: layer?.id ?? null};
}

function isCurrentSource(doc) {
    if (!source)
        return false;

    const {docId, layerId} = getSourceKey(doc);
    return source.docId === docId && source.layerId === layerId;
}

async function readSource(doc) {
    const {docId, layerId} = getSourceKey(doc);
    const pixels = await core.executeAsModal(() => grabPixels(
        options => imaging.getPixels({...options, colorSpace: "RGB", ...(layerId !== null ? {layerID: layerId} : {})}),
        doc
    ), {commandName: "Canny Edges: Read Image"});

    const {width, height} = pixels;
    const {data, comps} = toColorChannels(pixels.data, width * height, pixels.components);
    const full = {data, width, height, comps};
    const scale = Math.min(1, PREVIEW_SIZE / Math.max(width, height));
    let preview = full;

    if (scale < 1) {
        const previewWidth = Math.max(1, Math.round(width * scale));
        const previewHeight = Math.max(1, Math.round(height * scale));
        preview = {
            data: downscaleAverage(data, width, height, comps, previewWidth, previewHeight),
            width: previewWidth,
            height: previewHeight,
            comps
        };
    }

    source = {docId, layerId, full, preview, scale};
    schedulePreview(0);
}

/**
 * Full-size edges of the source, kept for the last parameters. The gradients are kept for the last blur,
 * so that a threshold change only reruns the suppression and the hysteresis
 */
function getFullEdges(params) {
    const key = JSON.stringify(params);

    if (source.fullEdges?.key !== key) {
        if (source.fullGradients?.blur !== params.blur)
            source.fullGradients = {blur: params.blur, gradients: blurredGradients(source.full, params.blur)};

        const edges = cannyFromGradients(source.fullGradients.gradients, params.threshold1, params.threshold2);
        source.fullEdges = {key, edges};
    }

    return source.fullEdges.edges;
}

/**
 * Re-read the source if the document, the source layer or the source mode has changed, or if forced
 */
async function refreshSource(force = false, retry = 0) {
    const doc = app.activeDocument;

    if (!doc) {
        source = null;
        showPreview(null);
        setStatus("No document is open");
        return;
    }

    if (!force && isCurrentSource(doc))
        return;

    // The result of the last apply stays shown (applying opens a new document or selects a layer, which refreshes)
    const status = document.getElementById("status");
    const previousStatus = status.classList.contains("error") ? "" : status.textContent;

    setBusy(true, "Reading the image");
    try {
        await readSource(doc);
        setStatus(previousStatus);
    } catch (error) {
        console.error(error);
        source = null;

        // Another plugin is still in its modal scope (e.g. Image Bench opening or placing an image)
        if (isModalBusy(error) && retry < MODAL_RETRIES) {
            setTimeout(() => refreshSource(force, retry + 1), MODAL_RETRY_DELAY);
            return;
        }

        showPreview(null);
        setStatus(error.message, true);
    } finally {
        setBusy(false);
    }
}

function isModalBusy(error) {
    return error?.number === 9 || /modal/i.test(error?.message ?? "");
}

// ==================== PREVIEW ====================

let previewTimer = null;
let rendering = false;
let renderPending = false;
// Width of the preview box (CSS pixels) the shown preview was rendered for, 0 if it was not laid out
let renderedBoxWidth = 0;
// Whether a resize has come since the panel was shown
let previewSettled = false;

function schedulePreview(delay = PREVIEW_DELAY) {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(renderPreview, delay);
}

/**
 * Render the preview, once more if the parameters changed meanwhile
 */
async function renderPreview() {
    if (rendering) {
        renderPending = true;
        return;
    }

    rendering = true;
    try {
        do {
            renderPending = false;
            await drawPreview();
        } while (renderPending);
    } catch (error) {
        console.error(error);
        setStatus(error.message, true);
    } finally {
        rendering = false;
    }
}

async function drawPreview() {
    if (!panelVisible)
        return;

    // A document opened or closed without a notification reaching the panel (e.g. by another plugin): the source
    // is read first, which renders the preview again
    const doc = app.activeDocument;
    if (doc ? !isCurrentSource(doc) : source) {
        await refreshSource();
        return;
    }

    if (!source)
        return;

    const params = getParams();
    const {preview, scale} = source;
    let edges, edgesWidth, edgesHeight;

    if (settings.fastPreview && scale < 1) {
        // Edges of the downscaled image, the blur scaled with it: close to the result, but not the same edges
        edges = detectEdges(preview, {...params, blurScale: scale});
        ({width: edgesWidth, height: edgesHeight} = preview);
    } else {
        edges = getFullEdges(params);
        ({width: edgesWidth, height: edgesHeight} = source.full);
    }

    // Averaged down to the device pixels of the preview, as Photoshop shows a zoomed out image: thin lines turn gray
    const {width, height} = getPreviewSize(edgesWidth, edgesHeight);
    if (width !== edgesWidth || height !== edgesHeight)
        edges = downscaleAverage(edges, edgesWidth, edgesHeight, 1, width, height);

    const rgb = new Uint8Array(width * height * 3);
    for (let i = 0; i < edges.length; i++)
        rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = edges[i];

    const imageData = await imaging.createImageDataFromBuffer(rgb, {width, height, components: 3, colorSpace: "RGB", chunky: true});
    try {
        showPreview("data:image/jpeg;base64," + await imaging.encodeImageData({imageData, base64: true}));
    } finally {
        imageData.dispose();
    }

    // Drawn before the panel was laid out: again once it is
    if (!renderedBoxWidth)
        schedulePreview(REFRESH_DELAY);
}

/**
 * Size of the preview image in device pixels at the width of the preview box (never above the image size),
 * so that the panel shows it unscaled
 */
function getPreviewSize(imageWidth, imageHeight) {
    renderedBoxWidth = getBoxWidth();
    const boxWidth = renderedBoxWidth || PREVIEW_SIZE;
    const width = Math.min(imageWidth, Math.round(boxWidth * (window.devicePixelRatio || 1)));
    return {width, height: Math.max(1, Math.round(imageHeight * width / imageWidth))};
}

/**
 * Width of the preview box in CSS pixels, 0 while the panel is not laid out
 */
function getBoxWidth() {
    return document.getElementById("preview-box").clientWidth;
}

function showPreview(url) {
    const image = document.getElementById("preview");
    const empty = document.getElementById("preview-empty");

    if (url) {
        image.src = url;
        image.classList.remove("hidden");
        empty.classList.add("hidden");
    } else {
        image.classList.add("hidden");
        empty.classList.remove("hidden");
    }
}

// ==================== APPLYING ====================

// The layer each document got from "Apply as layer", reused (overwritten) on the next apply
const appliedLayers = new Map();
let applying = false;

/**
 * Image data of edges for the mode and depth of a document (white edges on black)
 */
async function createEdgesImageData(edges, width, height, doc) {
    const gray = doc.mode === constants.DocumentMode.GRAYSCALE;

    if (!gray && doc.mode !== constants.DocumentMode.RGB)
        throw new Error("Only RGB and Grayscale documents can get an edges layer: use Apply as document");

    const components = gray ? 1 : 3;
    let componentSize = 8, buffer, on = 255;

    if (doc.bitsPerChannel === constants.BitsPerChannelType.SIXTEEN) {
        // The 16-bit range of Photoshop is 0..32768
        componentSize = 16;
        buffer = new Uint16Array(edges.length * components);
        on = 32768;
    } else if (doc.bitsPerChannel === constants.BitsPerChannelType.THIRTYTWO) {
        componentSize = 32;
        buffer = new Float32Array(edges.length * components);
        on = 1;
    } else
        buffer = new Uint8Array(edges.length * components);

    for (let i = 0; i < edges.length; i++)
        if (edges[i])
            for (let c = 0; c < components; c++)
                buffer[i * components + c] = on;

    return imaging.createImageDataFromBuffer(buffer, {
        width, height, components, componentSize, chunky: true, colorSpace: gray ? "Grayscale" : "RGB"
    });
}

/**
 * Clear the edges outside the selection (taken as selected from half the selection value)
 */
async function maskWithSelection(edges, doc) {
    if (!doc.selection?.bounds)
        throw new Error("There is no selection");

    const mask = await grabPixels(options => imaging.getSelection(options), doc);
    const masked = new Uint8Array(edges.length);

    for (let i = 0; i < edges.length; i++)
        if (mask.data[i * mask.components] >= 128)
            masked[i] = edges[i];

    return masked;
}

async function putEdges(edges, width, height, doc, layer) {
    const imageData = await createEdgesImageData(edges, width, height, doc);
    try {
        await imaging.putPixels({documentID: doc.id, layerID: layer.id, imageData, replace: true, targetBounds: {left: 0, top: 0}});
    } finally {
        imageData.dispose();
    }
}

/**
 * Re-read the source (the image may have been edited since the preview) and compute its full-size edges
 */
async function computeEdges(doc) {
    await readSource(doc);
    const params = getParams();
    return {params, edges: getFullEdges(params), width: source.full.width, height: source.full.height};
}

async function applyAsLayer() {
    const doc = getActiveDocument();
    const {params, edges, width, height} = await computeEdges(doc);
    const name = getLayerName(params);

    await core.executeAsModal(async context => {
        const historyId = await context.hostControl.suspendHistory({documentID: doc.id, name: HISTORY_NAME});
        try {
            const output = settings.selectionOnly ? await maskWithSelection(edges, doc) : edges;
            const activeLayer = doc.activeLayers[0];
            let layer = findLayer(doc.layers, appliedLayers.get(doc.id));

            if (!layer) {
                layer = doc.createPixelLayer ? await doc.createPixelLayer({name}) : await doc.createLayer({name});
                appliedLayers.set(doc.id, layer.id);
            }

            layer.name = name;
            await putEdges(output, width, height, doc, layer);

            // A new layer becomes the active one, which the "Active layer" source would read next
            if (activeLayer && activeLayer.id !== layer.id)
                await action.batchPlay([{
                    _obj: "select",
                    _target: [{_ref: "layer", _id: activeLayer.id}],
                    makeVisible: false
                }], {});
        } finally {
            await context.hostControl.resumeHistory(historyId);
        }
    }, {commandName: "Canny Edges: Apply as Layer"});

    return `Edges put into the layer ${name}`;
}

async function applyAsDocument() {
    const doc = getActiveDocument();
    const {params, edges, width, height} = await computeEdges(doc);
    // Document names become file names, which cannot contain a slash
    const name = getLayerName(params).replace("/", "-");

    await core.executeAsModal(async () => {
        const output = settings.selectionOnly ? await maskWithSelection(edges, doc) : edges;
        const edgesDoc = await app.documents.add({
            width,
            height,
            resolution: doc.resolution,
            mode: constants.NewDocumentMode.RGB,
            // A transparent document has a normal layer, the edges cover it completely
            fill: constants.DocumentFill.TRANSPARENT,
            name
        });
        await putEdges(output, width, height, edgesDoc, edgesDoc.layers[0]);
    }, {commandName: "Canny Edges: Apply as Document"});

    return `Edges opened as the document ${name}`;
}

// ==================== UI ====================

let panelReady = false;
let panelVisible = false;

function setStatus(text, isError = false) {
    const status = document.getElementById("status");
    status.textContent = text;
    status.classList.toggle("error", isError);
}

// Operations under way and the timer blinking the busy indicator
let busyCount = 0;
let busyTimer = null;

/**
 * Show an operation under way: a blinking indicator with the text, and the buttons disabled
 * (CSS animations are not available in UXP panels)
 * @param {boolean} busy - Start (with the text) or end an operation
 * @param {string} [text]
 */
function setBusy(busy, text) {
    busyCount = Math.max(0, busyCount + (busy ? 1 : -1));
    const active = busyCount > 0;

    if (busy)
        setStatus(`${text}...`);

    const indicator = document.getElementById("busy-dot");
    indicator.classList.toggle("active", active);
    document.querySelectorAll(".buttons sp-button").forEach(button => {
        if (active)
            button.setAttribute("disabled", "");
        else
            button.removeAttribute("disabled");
    });

    if (active && !busyTimer)
        busyTimer = setInterval(() => indicator.classList.toggle("dim"), 400);
    else if (!active && busyTimer) {
        clearInterval(busyTimer);
        busyTimer = null;
        indicator.classList.remove("dim");
    }
}

/**
 * Run an apply action, showing it under way and reporting the result in the panel
 * @param {Function} apply - Action returning a status message
 */
async function run(apply) {
    // One at a time: double clicks would apply twice
    if (applying)
        return;

    applying = true;
    setBusy(true, "Computing the edges");

    let result, failure;
    try {
        result = await apply();
    } catch (error) {
        console.error(error);
        failure = error;
    } finally {
        applying = false;
        setBusy(false);
    }

    if (failure)
        setStatus(failure.message, true);
    else
        setStatus(result);
}

const SLIDERS = ["threshold1", "threshold2", "blur"];

function initPanel() {
    if (panelReady)
        return;

    for (const name of SLIDERS) {
        const slider = document.getElementById(name);
        const label = document.getElementById(`${name}-value`);
        slider.value = settings[name];
        label.textContent = settings[name];

        const update = () => {
            const value = Math.round(Number(slider.value));
            if (value === settings[name])
                return;
            settings[name] = value;
            label.textContent = value;
            saveSettings();
            schedulePreview();
        };
        slider.addEventListener("input", update);
        slider.addEventListener("change", update);
    }

    const sources = document.querySelectorAll("#source sp-radio");
    sources.forEach(radio => {
        radio.checked = radio.getAttribute("value") === settings.source;
        radio.addEventListener("change", () => {
            if (!radio.checked || settings.source === radio.getAttribute("value"))
                return;
            settings.source = radio.getAttribute("value");
            saveSettings();
            refreshSource();
        });
    });

    for (const name of ["fastPreview", "selectionOnly"]) {
        const checkbox = document.getElementById(name);
        checkbox.checked = settings[name];
        checkbox.addEventListener("change", () => {
            settings[name] = checkbox.checked;
            saveSettings();
            if (name === "fastPreview")
                schedulePreview(0);
        });
    }

    document.getElementById("refresh").addEventListener("click", () => {
        if (!applying)
            refreshSource(true);
    });
    document.getElementById("apply-layer").addEventListener("click", () => run(applyAsLayer));
    document.getElementById("apply-document").addEventListener("click", () => run(applyAsDocument));

    // Another document or layer selected: the source changes (the panel's own layer selection is ignored).
    // A placed image (Image Bench sends images so) changes the pixels of the same source
    let refreshTimer = null;
    let refreshForced = false;
    action.addNotificationListener(["select", "open", "close", "placeEvent"], event => {
        if (!panelVisible || applying)
            return;
        if (event === "placeEvent")
            refreshForced = true;
        clearTimeout(refreshTimer);
        refreshTimer = setTimeout(() => {
            const force = refreshForced;
            refreshForced = false;
            refreshSource(force);
        }, REFRESH_DELAY);
    });

    // The preview is rendered at the device pixels of its box. A new preview changes the panel height, which may
    // show or hide its scroll bar and so change the box width: small changes are ignored, or the two would
    // keep triggering each other. The first resize after showing the panel always renders: the preview drawn
    // from show() comes before the panel is laid out and may not be displayed
    window.addEventListener("resize", () => {
        const settled = previewSettled;
        previewSettled = true;
        if (!settled || !renderedBoxWidth || Math.abs(getBoxWidth() - renderedBoxWidth) >= RESIZE_THRESHOLD)
            schedulePreview(REFRESH_DELAY);
    });

    panelReady = true;
}

entrypoints.setup({
    panels: {
        cannyPanel: {
            show() {
                initPanel();
                panelVisible = true;
                previewSettled = false;
                // The image may have changed while the panel was hidden
                refreshSource(true);
            },
            hide() {
                panelVisible = false;
            }
        }
    }
});
