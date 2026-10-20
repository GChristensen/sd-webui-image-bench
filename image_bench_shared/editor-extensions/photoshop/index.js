/**
 * Image Bench Photoshop plugin
 * Sends the active document and its selection (as a black and white mask)
 * to SD WebUI (the img2img canvas while img2img › img2img is shown, else the inpaint upload tab) or ComfyUI (the nodes marked ib:img and ib:mask)
 * with the Image Bench extension, or to a ControlNet unit of SD WebUI (the one shown in the Image Bench window),
 * saves it into the current project of Image Bench (Keep › File / Final),
 * and places images sent from the Image Bench window into Photoshop
 */

const {entrypoints, storage} = require("uxp");
const {action, app, core, imaging} = require("photoshop");

const fs = storage.localFileSystem;

const DEFAULT_WEBUI_URL = "http://127.0.0.1:7860";
const WEBUI_URL_KEY = "webuiUrl";
const RECENT_URLS_KEY = "recentWebuiUrls";
const MAX_RECENT_URLS = 5;
const SMART_OBJECTS_KEY = "placeSmartObjects";
const PLUGIN_WEBSOCKET_PATH = "/image-bench/editor/websocket";
const RECONNECT_DELAY = 5000;
// Close code of a connection replaced by another editor, which is not restored on its own
const REPLACED_CLOSE_CODE = 4000;

function getWebuiUrl() {
    return (localStorage.getItem(WEBUI_URL_KEY) || DEFAULT_WEBUI_URL).replace(/\/+$/, "");
}

/**
 * Read 8-bit pixels of the whole document area, whatever the source bounds of the returned data are
 * @param {Function} getPixels - Imaging API call returning {imageData, sourceBounds}
 * @param {Document} doc - Photoshop document
 * @param {string} commandName - Name of the modal operation shown in Photoshop
 * @returns {Promise<{data: Uint8Array, width: number, height: number, components: number}>}
 */
async function readPixels(getPixels, doc, commandName) {
    const width = Math.round(doc.width);
    const height = Math.round(doc.height);
    const documentBounds = {left: 0, top: 0, right: width, bottom: height};

    return core.executeAsModal(async () => {
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
    }, {commandName});
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

async function readDocumentImage(doc) {
    return readPixels(options => imaging.getPixels({...options, colorSpace: "RGB"}),
        doc, "Image Bench: Read Image");
}

async function readSelectionMask(doc) {
    if (doc.selection && !doc.selection.bounds)
        throw new Error("There is no selection");

    return readPixels(options => imaging.getSelection(options), doc, "Image Bench: Read Selection");
}

/**
 * Send pixels to the Image Bench backend, which forwards them to the connected WebUI or ComfyUI pages
 * @param {'image'|'mask'} kind - Image kind
 * @param {{data: Uint8Array, width: number, height: number, components: number}} pixels
 * @param {'input'|'cn_preprocess'|'cn_image'|'cn_mask'|'compare'} target - The generation input, a ControlNet unit (WebUI):
 *   its image to preprocess, its control image used without a preprocessor, or its mask; or the Compare tab
 */
async function upload(kind, pixels, target = "input") {
    const {data, width, height, components} = pixels;
    const query = Object.entries({kind, width, height, components, target})
        .map(([name, value]) => `${name}=${encodeURIComponent(value)}`)
        .join("&");
    const body = data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength);

    let response;
    try {
        response = await fetch(`${getWebuiUrl()}/image-bench/editor/upload?${query}`, {
            method: "POST",
            headers: {"Content-Type": "application/octet-stream"},
            body
        });
    } catch (error) {
        throw new Error(`Unable to connect to ${getWebuiUrl()}`);
    }

    if (!response.ok)
        throw await responseError(response);

    const {clients, saved} = await response.json();

    // Images of the Compare tab are saved by the server and shown when the Image Bench window opens
    if (!clients && !saved)
        throw new Error("No WebUI or ComfyUI page is open");
}

/**
 * The error of a failed response, with the message of a JSON error ({error} of Image Bench, {detail} of FastAPI)
 */
async function responseError(response) {
    let text = await response.text();

    try {
        const body = JSON.parse(text);
        text = body.error || body.detail || text;
    } catch (e) {
        // Not JSON: the text as it is
    }

    return new Error(`The server responded with ${response.status}: ${text}`);
}

/**
 * The document as a layered PSD file, saved as a copy into the temporary folder, so that the document keeps its file
 * @returns {Promise<ArrayBuffer>}
 */
async function readDocumentPsd(doc) {
    const folder = await fs.getTemporaryFolder();
    const file = await folder.createFile("image-bench-document.psd", {overwrite: true});

    await core.executeAsModal(async () => {
        await doc.saveAs.psd(file, {layers: true, embedColorProfile: true, maximizeCompatibility: true}, true);
    }, {commandName: "Image Bench: Save Document"});

    try {
        return await file.read({format: storage.formats.binary});
    } finally {
        await file.delete().catch(() => {});
    }
}

/**
 * Save the document into the folder of the current project of Image Bench
 * @param {'file'|'final'} save - <project>-NNN.psd, or final-NNN.psd, .png and .jpg (the project's final image)
 * @param {ArrayBuffer} psd - The document as a PSD file
 * @param {{data: Uint8Array, width: number, height: number, components: number}} [pixels] - The merged image, for "final"
 * @returns {Promise<string>} The result message
 */
async function saveToProject(save, psd, pixels) {
    const query = {save, psd: psd.byteLength};
    let body = new Uint8Array(psd);

    if (pixels) {
        const {data, width, height, components} = pixels;
        Object.assign(query, {width, height, components});
        body = new Uint8Array(psd.byteLength + data.byteLength);
        body.set(new Uint8Array(psd), 0);
        body.set(data, psd.byteLength);
    }

    const queryString = Object.entries(query).map(([name, value]) => `${name}=${encodeURIComponent(value)}`).join("&");
    let response;

    try {
        response = await fetch(`${getWebuiUrl()}/image-bench/editor/project?${queryString}`, {
            method: "POST",
            headers: {"Content-Type": "application/octet-stream"},
            body: body.buffer
        });
    } catch (error) {
        throw new Error(`Unable to connect to ${getWebuiUrl()}`);
    }

    if (!response.ok)
        throw await responseError(response);

    const {project, files} = await response.json();
    return `Saved ${files.join(", ")} in ${project}`;
}

async function sendImage() {
    const doc = getActiveDocument();
    await upload("image", await readDocumentImage(doc));
    return "Image sent to the input image";
}

async function sendMask() {
    const doc = getActiveDocument();
    await upload("mask", await readSelectionMask(doc));
    return "Mask sent to the input mask";
}

async function sendImageAndMask() {
    const doc = getActiveDocument();
    // Read the selection first, so nothing is sent if there is no selection
    const mask = await readSelectionMask(doc);
    await upload("image", await readDocumentImage(doc));
    await upload("mask", mask);
    return "Image and mask sent to the input";
}

async function sendControlNetPreprocess() {
    await upload("image", await readDocumentImage(getActiveDocument()), "cn_preprocess");
    return "Image sent to the ControlNet preprocessor";
}

async function sendControlNetImage() {
    await upload("image", await readDocumentImage(getActiveDocument()), "cn_image");
    return "Image sent as the ControlNet control image";
}

async function sendControlNetMask() {
    await upload("mask", await readSelectionMask(getActiveDocument()), "cn_mask");
    return "Mask sent to ControlNet";
}

async function sendCompare() {
    await upload("image", await readDocumentImage(getActiveDocument()), "compare");
    return "Image added to the Compare tab";
}

async function saveFile() {
    return saveToProject("file", await readDocumentPsd(getActiveDocument()));
}

async function saveFinal() {
    const doc = getActiveDocument();
    return saveToProject("final", await readDocumentPsd(doc), await readDocumentImage(doc));
}

// ==================== RECEIVING ====================

let socket = null;
let reconnectTimer = null;

/**
 * Connect to WebUI or ComfyUI to receive images sent from the Image Bench window.
 * The connection lives as long as the plugin is loaded, regardless of the panel visibility,
 * and is restored if lost (e.g. when the server restarts)
 */
function connect() {
    clearTimeout(reconnectTimer);

    let websocket;
    try {
        websocket = new WebSocket(getWebuiUrl().replace(/^http/i, "ws") + PLUGIN_WEBSOCKET_PATH);
    } catch (error) {
        console.error(error);
        setConnectionState("disconnected");
        setStatus(`Invalid server URL: ${getWebuiUrl()}`, true);
        return;
    }

    socket = websocket;
    setConnectionState("connecting");

    websocket.onopen = () => {
        if (socket === websocket) {
            setConnectionState("connected");
            rememberUrl(getWebuiUrl());
            // The server then waits for OPEN_IMAGE_DONE, so that Image Bench shows the transfer until it ends
            websocket.send(JSON.stringify({type: "HELLO", editor: "Photoshop", acks: true}));
        }
    };
    websocket.onmessage = onWebuiMessage;
    websocket.onclose = e => {
        // A replaced connection is closed deliberately
        if (socket !== websocket)
            return;

        // Another editor (another Photoshop or Krita) took the connection: both would take it in turn otherwise
        if (e.code === REPLACED_CLOSE_CODE) {
            setConnectionState("replaced");
            return;
        }

        setConnectionState("disconnected");
        reconnectTimer = setTimeout(connect, RECONNECT_DELAY);
    };
}

function reconnect() {
    const websocket = socket;
    socket = null;
    websocket?.close();
    connect();
}

async function onWebuiMessage(e) {
    const msg = JSON.parse(e.data);

    if (msg.type !== "OPEN_IMAGE")
        return;

    const websocket = e.target;
    setBusy(true, `Receiving ${msg.name}`);

    try {
        await openImage(msg);
        reportOpened(websocket, msg);
        setBusy(false);
        setStatus(`Received ${msg.name}`);
    } catch (error) {
        console.error(error);
        reportOpened(websocket, msg, error.message);
        setBusy(false);
        setStatus(error.message, true);

        if (!panelVisible)
            await app.showAlert(`Image Bench: ${error.message}`);
    }
}

/**
 * Tell the server that a received image is in Photoshop or could not be opened
 */
function reportOpened(websocket, {requestId}, error) {
    if (!requestId)
        return;

    try {
        websocket.send(JSON.stringify({type: "OPEN_IMAGE_DONE", requestId, ...(error ? {error} : {})}));
    } catch (e) {
        console.error(e);
    }
}

/**
 * Place a received image as a new layer of the active document, or open it if there is no document
 * or a new document is requested
 * @param {{name: string, imageUrl: string, newDocument?: boolean}} msg - Image file name, its URL relative to the server
 *   and whether to open it as a new document
 */
async function openImage({name, imageUrl, newDocument}) {
    const response = await fetch(getWebuiUrl() + imageUrl);

    if (!response.ok)
        throw new Error(`Unable to download ${name}: the server responded with ${response.status}`);

    const folder = await fs.getTemporaryFolder();
    const file = await folder.createFile(name, {overwrite: true});
    await file.write(await response.arrayBuffer(), {format: storage.formats.binary});

    await core.executeAsModal(async () => {
        if (app.documents.length && !newDocument)
            await placeAsLayer(file);
        else
            await app.open(file);
    }, {commandName: "Image Bench: Open Image"});
}

/**
 * Place a file as a layer centered in the active document, named after the file. Placing makes a smart object,
 * which is rasterized unless the panel keeps smart objects, so that its pixels can be edited directly
 * (a selection deleted, painted on, ...)
 */
async function placeAsLayer(file) {
    const commands = [{
        _obj: "placeEvent",
        null: {_path: fs.createSessionToken(file), _kind: "local"},
        freeTransformCenterState: {_enum: "quadCenterState", _value: "QCSAverage"},
        offset: {
            _obj: "offset",
            horizontal: {_unit: "pixelsUnit", _value: 0},
            vertical: {_unit: "pixelsUnit", _value: 0}
        }
    }];

    if (localStorage.getItem(SMART_OBJECTS_KEY) !== "true")
        commands.push({
            _obj: "rasterizeLayer",
            _target: [{_ref: "layer", _enum: "ordinal", _value: "targetEnum"}]
        });

    const results = await action.batchPlay(commands, {});
    const error = results.find(result => result?._obj === "error");

    if (error)
        throw new Error(`Unable to place ${file.name}: ${error.message}`);
}

// ==================== UI ====================

let panelReady = false;
let panelVisible = false;

function setStatus(text, isError = false) {
    const status = document.getElementById("status");
    status.textContent = text;
    status.classList.toggle("error", isError);
}

// Transfers under way (sending and receiving may overlap) and the timer blinking the busy indicator
let busyCount = 0;
let busyTimer = null;

/**
 * Show a transfer under way: a blinking indicator with the text, and the send buttons disabled
 * (CSS animations are not available in UXP panels)
 * @param {boolean} busy - Start (with the text) or end a transfer
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

const CONNECTION_STATES = {
    connected: {label: "Connected", title: "Connected to the server: click to reconnect"},
    connecting: {label: "Connecting...", title: "Connecting to the server: click to retry"},
    disconnected: {label: "Reconnect", title: "Not connected to the server: click to reconnect"},
    replaced: {label: "Reconnect", title: "Another editor connected to the server: click to take the connection"}
};

/**
 * Show the connection state in the reconnect button and the indicator next to it
 * @param {'connected'|'connecting'|'disconnected'|'replaced'} state
 */
function setConnectionState(state) {
    const {label, title} = CONNECTION_STATES[state];
    const button = document.getElementById("connection");
    button.textContent = label;
    button.title = title;
    document.getElementById("connection-dot").className = state;
}

/**
 * Save the URL of the field and reconnect, if it has changed or if forced (Enter, the reconnect button)
 */
function applyUrl(force) {
    const urlField = document.getElementById("webui-url");
    const url = urlField.value.trim();
    const changed = url !== (localStorage.getItem(WEBUI_URL_KEY) ?? "");

    if (changed)
        localStorage.setItem(WEBUI_URL_KEY, url);

    if (changed || force)
        reconnect();
}

// ==================== RECENT URLS ====================

function getRecentUrls() {
    try {
        const urls = JSON.parse(localStorage.getItem(RECENT_URLS_KEY) || "[]");
        return Array.isArray(urls) ? urls : [];
    } catch {
        return [];
    }
}

function setRecentUrls(urls) {
    localStorage.setItem(RECENT_URLS_KEY, JSON.stringify(urls));
    renderRecentUrls();
}

/**
 * Put a URL the plugin connected to at the top of the recent ones
 */
function rememberUrl(url) {
    const urls = getRecentUrls();
    if (urls[0] !== url)
        setRecentUrls([url, ...urls.filter(u => u !== url)].slice(0, MAX_RECENT_URLS));
}

function showRecentUrls(open) {
    const list = document.getElementById("recent-urls");
    list.classList.toggle("open", open && getRecentUrls().length > 0);
}

function renderRecentUrls() {
    const urls = getRecentUrls();
    const list = document.getElementById("recent-urls");
    list.innerHTML = "";

    for (const url of urls) {
        const item = document.createElement("div");
        item.className = "recent-item";
        item.title = `Connect to ${url}`;

        const label = document.createElement("span");
        label.className = "recent-url";
        label.textContent = url;

        const remove = document.createElement("span");
        remove.className = "recent-remove";
        remove.textContent = "✕";
        remove.title = "Remove from the recent URLs";

        item.append(label, remove);
        item.addEventListener("click", e => {
            if (e.target === remove) {
                setRecentUrls(getRecentUrls().filter(u => u !== url));
                showRecentUrls(true);
                return;
            }
            document.getElementById("webui-url").value = url;
            showRecentUrls(false);
            applyUrl(true);
        });
        list.appendChild(item);
    }

    const toggle = document.getElementById("recent-toggle");
    if (urls.length)
        toggle.removeAttribute("disabled");
    else {
        toggle.setAttribute("disabled", "");
        list.classList.remove("open");
    }
}

let sending = false;

/**
 * Run an action, showing it under way and reporting the result in the panel, or errors in an alert when invoked as a menu command
 * @param {Function} action - Action returning a status message
 * @param {boolean} fromPanel - Whether the action is invoked from the panel
 */
async function run(action, fromPanel = false) {
    // One send at a time: double clicks would send twice
    if (sending)
        return;

    sending = true;
    setBusy(true, "Sending");

    let result, failure;
    try {
        result = await action();
    } catch (error) {
        console.error(error);
        failure = error;
    } finally {
        sending = false;
        setBusy(false);
    }

    if (!failure)
        setStatus(result);
    else if (fromPanel)
        setStatus(failure.message, true);
    else
        await app.showAlert(`Image Bench: ${failure.message}`);
}

function initPanel() {
    if (panelReady)
        return;

    const urlField = document.getElementById("webui-url");
    urlField.value = getWebuiUrl();
    // Enter also fires "change", which then finds the URL already saved
    urlField.addEventListener("keydown", e => {
        if (e.key === "Enter") {
            showRecentUrls(false);
            applyUrl(true);
        } else if (e.key === "ArrowDown")
            showRecentUrls(true);
        else if (e.key === "Escape" || e.key === "ArrowUp")
            showRecentUrls(false);
    });
    urlField.addEventListener("change", () => applyUrl(false));
    document.getElementById("connection").addEventListener("click", () => applyUrl(true));

    renderRecentUrls();
    document.getElementById("recent-toggle").addEventListener("click", () =>
        showRecentUrls(!document.getElementById("recent-urls").classList.contains("open")));

    const smartObjects = document.getElementById("smart-objects");
    smartObjects.checked = localStorage.getItem(SMART_OBJECTS_KEY) === "true";
    smartObjects.addEventListener("change", () => localStorage.setItem(SMART_OBJECTS_KEY, String(smartObjects.checked)));

    document.getElementById("send-image").addEventListener("click", () => run(sendImage, true));
    document.getElementById("send-mask").addEventListener("click", () => run(sendMask, true));
    document.getElementById("send-image-and-mask").addEventListener("click", () => run(sendImageAndMask, true));
    document.getElementById("send-cn-preprocess").addEventListener("click", () => run(sendControlNetPreprocess, true));
    document.getElementById("send-cn-image").addEventListener("click", () => run(sendControlNetImage, true));
    document.getElementById("send-cn-mask").addEventListener("click", () => run(sendControlNetMask, true));
    document.getElementById("send-compare").addEventListener("click", () => run(sendCompare, true));
    document.getElementById("save-file").addEventListener("click", () => run(saveFile, true));
    document.getElementById("save-final").addEventListener("click", () => run(saveFinal, true));

    panelReady = true;
}

entrypoints.setup({
    commands: {
        sendImage: () => run(sendImage),
        sendMask: () => run(sendMask),
        sendImageAndMask: () => run(sendImageAndMask),
        sendControlNetPreprocess: () => run(sendControlNetPreprocess),
        sendControlNetImage: () => run(sendControlNetImage),
        sendControlNetMask: () => run(sendControlNetMask),
        sendCompare: () => run(sendCompare),
        saveFile: () => run(saveFile),
        saveFinal: () => run(saveFinal)
    },
    panels: {
        imageBenchPanel: {
            show() {
                initPanel();
                panelVisible = true;
            },
            hide() {
                panelVisible = false;
            }
        }
    }
});

connect();
