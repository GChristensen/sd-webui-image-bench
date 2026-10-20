/**
 * ControlNet inputs of the generated images: the enabled units are read when Generate is clicked, their images are
 * uploaded to the backend, which stores them by hash (shared_backend/controlnet_inputs.py), and the images of the
 * job carry the units as image.controlnet = {units: [{index, params, image, mask, preview}]}, the images as hashes.
 *
 * Nothing here is awaited by a generation or may throw into it: capture() only reads the DOM and starts the uploads,
 * attach() only sets a field of an image message whose record is complete.
 */

const INPUT_ENDPOINT = '/image-bench/controlnet/input';
const IMAGE_KINDS = ['image', 'mask', 'preview'];
// Hashes of the last image sources, so that an unchanged image is neither read nor uploaded again
const MAX_SOURCES = 32;
// Records of the last jobs by their batchId, for the later images of a job
const MAX_BATCHES = 8;

// Length and ends of a source (a data URL of several MB), as controlnet.js:sendImages() tells a new image
function signatureOf(source) {
    return `${source.length}:${source.slice(0, 64)}:${source.slice(-64)}`;
}

// Forge writes "ControlNet N" into the infotext for each enabled unit; the parser lowercases the keys
function hasControlNetInfo(parameters) {
    return !!parameters && Object.keys(parameters).some(key => /^controlnet \d+$/.test(key));
}

/**
 * @param {Object} controlNet - Of controlnet.js
 * @param {(tab: 'txt2img'|'img2img') => {index: number, params: Object, image: string|null, mask: string|null,
 *     preview: string|null}[]} controlNet.readEnabledUnits
 */
export function createControlNetRecorder(controlNet) {
    // signature -> Promise of the hash
    const hashes = new Map();
    // The record of the last Generate click, taken by the first image of the next job with ControlNet units.
    // A click replaces it, so that a job that failed before saving an image leaves no record to a later one
    let pending = null;
    const batches = new Map();

    function hashOf(source) {
        const signature = signatureOf(source);
        let hash = hashes.get(signature);

        if (hash) {
            // The most recently used last
            hashes.delete(signature);
        }
        else {
            hash = upload(source);
            hash.catch(() => hashes.delete(signature));
        }

        hashes.set(signature, hash);

        while (hashes.size > MAX_SOURCES)
            hashes.delete(hashes.keys().next().value);

        return hash;
    }

    async function upload(source) {
        const blob = await (await fetch(source)).blob();
        const response = await fetch(INPUT_ENDPOINT, {method: 'POST', body: blob});

        if (!response.ok)
            throw new Error(`HTTP ${response.status}`);

        return (await response.json()).hash;
    }

    async function resolve(record, units) {
        try {
            await Promise.all(units.flatMap((unit, position) => IMAGE_KINDS
                .filter(kind => unit[kind])
                .map(async kind => record.units[position][kind] = await hashOf(unit[kind]))));

            record.ready = true;
        } catch (error) {
            console.warn('[Image Bench] Unable to store the ControlNet images:', error);
        }
    }

    /**
     * Read the enabled units of the generation tab, called when its Generate button is clicked
     * @param {'txt2img'|'img2img'} tab
     */
    function capture(tab) {
        const units = controlNet.readEnabledUnits(tab);

        if (!units.length) {
            pending = null;
            return;
        }

        const record = {
            units: units.map(({index, params}) => ({index, params, image: null, mask: null, preview: null})),
            ready: false
        };

        pending = record;
        resolve(record, units);
    }

    /**
     * Add the units of its job to the message of a saved image (SAVED_IMAGE)
     * @param {Object} msg
     */
    function attach(msg) {
        if (!hasControlNetInfo(msg.parameters))
            return;

        let record = batches.get(msg.batchId);

        if (record === undefined) {
            record = pending;
            pending = null;
            batches.set(msg.batchId, record);

            while (batches.size > MAX_BATCHES)
                batches.delete(batches.keys().next().value);
        }

        if (record?.ready)
            msg.controlnet = {units: record.units};
        else if (record)
            console.warn('[Image Bench] The ControlNet images of the generation are not stored yet');
    }

    return {capture, attach};
}
