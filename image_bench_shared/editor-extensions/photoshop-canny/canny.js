/**
 * Gaussian blur and Canny edge detection on 8-bit interleaved pixels,
 * reproducing cv2.GaussianBlur(img, (k, k), 0) and cv2.Canny(img, th1, th2) of OpenCV
 * (aperture 3, L1 gradient, multi-channel input) closely enough to look the same, not bit-exact
 */

// OpenCV's fixed kernels for the small sizes when no sigma is given
const SMALL_KERNELS = {
    1: [1],
    3: [0.25, 0.5, 0.25],
    5: [0.0625, 0.25, 0.375, 0.25, 0.0625],
    7: [0.03125, 0.109375, 0.21875, 0.28125, 0.21875, 0.109375, 0.03125]
};

// Up to this kernel size (sigma from the size), the blur in 8-bit fixed point (kernel in 1/256, remainder on the
// center tap) matches cv2 exactly; larger kernels differ by 1-2 levels in either fixed or floating point
const MAX_FIXED_POINT_KERNEL = 11;
const FIXED_POINT_ONE = 256;

// tan(22.5°) in 15-bit fixed point, as the direction buckets of OpenCV's non-maximum suppression
const TG22 = Math.round(0.4142135623730950488 * (1 << 15));

/**
 * Sigma that OpenCV derives from the kernel size when it is 0
 */
function defaultSigma(ksize) {
    return 0.3 * ((ksize - 1) * 0.5 - 1) + 0.8;
}

/**
 * Smallest odd kernel size covering ±3 sigma, as OpenCV picks it for 8-bit images
 */
function kernelSizeForSigma(sigma) {
    return Math.max(3, Math.round(sigma * 6 + 1) | 1);
}

function gaussianKernel(ksize, sigma) {
    if (!sigma && SMALL_KERNELS[ksize])
        return Float32Array.from(SMALL_KERNELS[ksize]);

    sigma = sigma || defaultSigma(ksize);
    const radius = (ksize - 1) / 2;
    const kernel = new Float32Array(ksize);
    let sum = 0;

    for (let i = 0; i < ksize; i++) {
        const x = i - radius;
        kernel[i] = Math.exp(-(x * x) / (2 * sigma * sigma));
        sum += kernel[i];
    }

    for (let i = 0; i < ksize; i++)
        kernel[i] /= sum;

    return kernel;
}

function fixedPointKernel(kernel) {
    const fixed = Int32Array.from(kernel, weight => Math.round(weight * FIXED_POINT_ONE));
    fixed[(kernel.length - 1) >> 1] += FIXED_POINT_ONE - fixed.reduce((sum, weight) => sum + weight, 0);
    return fixed;
}

/**
 * Index into [0, n) for BORDER_REFLECT_101 (dcb|abcdefgh|gfe)
 */
function reflect101(i, n) {
    if (n === 1)
        return 0;

    while (i < 0 || i >= n)
        i = i < 0 ? -i : 2 * n - 2 - i;

    return i;
}

/**
 * Reduce pixels to the RGB (or gray) channels, alpha premultiplied, so transparent areas are black
 * @param {Uint8Array} src - Interleaved pixels
 * @param {number} count - Pixel count
 * @param {number} comps - Components per pixel: 1 (gray), 3 (RGB) or 4 (RGBA)
 * @returns {{data: Uint8Array, comps: number}}
 */
function toColorChannels(src, count, comps) {
    if (comps === 1 || comps === 3)
        return {data: src, comps};

    const channels = comps === 2 ? 1 : 3;
    const data = new Uint8Array(count * channels);

    for (let i = 0; i < count; i++) {
        const alpha = src[i * comps + channels];
        for (let c = 0; c < channels; c++)
            data[i * channels + c] = Math.round(src[i * comps + c] * alpha / 255);
    }

    return {data, comps: channels};
}

/**
 * Separable Gaussian blur of each channel with BORDER_REFLECT_101
 * @param {Uint8Array} src - Interleaved pixels
 * @param {number} ksize - Odd kernel size, 1 returns the source
 * @param {number} [sigma] - Derived from the kernel size if not given
 * @returns {Uint8Array}
 */
function gaussianBlur(src, width, height, comps, ksize, sigma) {
    if (ksize <= 1)
        return src;

    const fixedPoint = !sigma && ksize <= MAX_FIXED_POINT_KERNEL;
    const kernel = fixedPoint ? fixedPointKernel(gaussianKernel(ksize)) : gaussianKernel(ksize, sigma);
    const scale = fixedPoint ? 1 / (FIXED_POINT_ONE * FIXED_POINT_ONE) : 1;
    const radius = (ksize - 1) >> 1;
    const rowLength = width * comps;
    const tmp = fixedPoint ? new Int32Array(src.length) : new Float32Array(src.length);
    const out = new Uint8Array(src.length);

    // Source columns of each kernel tap for each x, borders reflected
    const columns = new Int32Array(width * ksize);
    for (let x = 0; x < width; x++)
        for (let k = 0; k < ksize; k++)
            columns[x * ksize + k] = reflect101(x + k - radius, width) * comps;

    for (let y = 0; y < height; y++) {
        const row = y * rowLength;
        for (let x = 0; x < width; x++) {
            const taps = x * ksize;
            for (let c = 0; c < comps; c++) {
                let sum = 0;
                for (let k = 0; k < ksize; k++)
                    sum += kernel[k] * src[row + columns[taps + k] + c];
                tmp[row + x * comps + c] = sum;
            }
        }
    }

    const rows = new Int32Array(ksize);
    for (let y = 0; y < height; y++) {
        for (let k = 0; k < ksize; k++)
            rows[k] = reflect101(y + k - radius, height) * rowLength;

        const row = y * rowLength;
        for (let i = 0; i < rowLength; i++) {
            let sum = 0;
            for (let k = 0; k < ksize; k++)
                sum += kernel[k] * tmp[rows[k] + i];
            // Uint8Array clamps
            out[row + i] = Math.round(sum * scale);
        }
    }

    return out;
}

/**
 * Sobel gradients of interleaved pixels: per pixel, the gradient of the channel with the largest L1 magnitude
 * @param {Uint8Array} src - Interleaved pixels (1 or 3 components, see toColorChannels)
 * @returns {{gx: Int16Array, gy: Int16Array, mag: Int32Array, width: number, height: number}} -
 *   mag has a zero border of one pixel (row length width + 2)
 */
function computeGradients(src, width, height, comps) {
    const count = width * height;
    const rowLength = width * comps;

    const gx = new Int16Array(count);
    const gy = new Int16Array(count);
    // Magnitudes with a zero border of one pixel, so the neighbors of the image border read 0
    const stride = width + 2;
    const mag = new Int32Array(stride * (height + 2));

    // Sobel 3x3 with replicated borders
    for (let y = 0; y < height; y++) {
        const above = Math.max(y - 1, 0) * rowLength;
        const row = y * rowLength;
        const below = Math.min(y + 1, height - 1) * rowLength;

        for (let x = 0; x < width; x++) {
            const left = Math.max(x - 1, 0) * comps;
            const center = x * comps;
            const right = Math.min(x + 1, width - 1) * comps;
            let best = -1, bestX = 0, bestY = 0;

            for (let c = 0; c < comps; c++) {
                const a = src[above + left + c], b = src[above + center + c], d = src[above + right + c];
                const e = src[row + left + c], f = src[row + right + c];
                const g = src[below + left + c], h = src[below + center + c], k = src[below + right + c];
                const dx = (d + 2 * f + k) - (a + 2 * e + g);
                const dy = (g + 2 * h + k) - (a + 2 * b + d);
                const m = Math.abs(dx) + Math.abs(dy);

                if (m > best) {
                    best = m;
                    bestX = dx;
                    bestY = dy;
                }
            }

            const i = y * width + x;
            gx[i] = bestX;
            gy[i] = bestY;
            mag[(y + 1) * stride + x + 1] = best;
        }
    }

    return {gx, gy, mag, width, height};
}

/**
 * Canny edges from the gradients: non-maximum suppression and hysteresis
 * @param {number} threshold1 - Hysteresis threshold, swapped with threshold2 if larger
 * @param {number} threshold2
 * @returns {Uint8Array} One component, edges 255 on 0
 */
function cannyFromGradients({gx, gy, mag, width, height}, threshold1, threshold2) {
    const low = Math.floor(Math.min(threshold1, threshold2));
    const high = Math.floor(Math.max(threshold1, threshold2));
    const count = width * height;
    const stride = width + 2;

    // Non-maximum suppression: 0 no edge, 1 weak candidate, 2 edge
    const map = new Uint8Array(count);
    const stack = new Int32Array(count);
    let top = 0;

    for (let y = 0; y < height; y++) {
        for (let x = 0; x < width; x++) {
            const p = (y + 1) * stride + x + 1;
            const m = mag[p];

            if (m <= low)
                continue;

            const i = y * width + x;
            const xs = gx[i], ys = gy[i];
            const ax = Math.abs(xs);
            const ay = Math.abs(ys) << 15;
            const tg22x = ax * TG22;
            let maximum;

            if (ay < tg22x)
                maximum = m > mag[p - 1] && m >= mag[p + 1];
            else if (ay > tg22x + (ax << 16))
                maximum = m > mag[p - stride] && m >= mag[p + stride];
            else {
                const s = (xs ^ ys) < 0 ? -1 : 1;
                maximum = m > mag[p - stride - s] && m > mag[p + stride + s];
            }

            if (!maximum)
                continue;

            if (m > high) {
                map[i] = 2;
                stack[top++] = i;
            } else
                map[i] = 1;
        }
    }

    // Hysteresis: candidates 8-connected to an edge become edges
    while (top > 0) {
        const i = stack[--top];
        const x = i % width;
        const y = (i - x) / width;

        for (let ny = Math.max(y - 1, 0); ny <= Math.min(y + 1, height - 1); ny++)
            for (let nx = Math.max(x - 1, 0); nx <= Math.min(x + 1, width - 1); nx++) {
                const n = ny * width + nx;
                if (map[n] === 1) {
                    map[n] = 2;
                    stack[top++] = n;
                }
            }
    }

    const edges = new Uint8Array(count);
    for (let i = 0; i < count; i++)
        if (map[i] === 2)
            edges[i] = 255;

    return edges;
}

/**
 * Canny edges of interleaved pixels, as cv2.Canny with aperture 3 and the L1 gradient
 * @param {Uint8Array} src - Interleaved pixels (1 or 3 components, see toColorChannels)
 * @returns {Uint8Array} One component, edges 255 on 0
 */
function canny(src, width, height, comps, threshold1, threshold2) {
    return cannyFromGradients(computeGradients(src, width, height, comps), threshold1, threshold2);
}

/**
 * Gradients of the image blurred as the original extension does (if the kernel size is above 1), the part of the
 * edge detection that does not depend on the thresholds
 * @param {{data: Uint8Array, width: number, height: number, comps: number}} image - Color channels (toColorChannels)
 * @param {number} blur - Kernel size
 * @param {number} [blurScale] - Scales the blur sigma for an image downscaled by that factor
 */
function blurredGradients(image, blur, blurScale = 1) {
    const {width, height, comps} = image;
    let data = image.data;

    if (blur > 1) {
        if (blurScale === 1)
            data = gaussianBlur(data, width, height, comps, blur);
        else {
            const sigma = defaultSigma(blur) * blurScale;
            // A blur of less than about a third of a pixel changes nothing visible
            if (sigma >= 0.3)
                data = gaussianBlur(data, width, height, comps, kernelSizeForSigma(sigma), sigma);
        }
    }

    return computeGradients(data, width, height, comps);
}

/**
 * Blur (if the kernel size is above 1) and detect the edges, as the original extension does
 * @param {{data: Uint8Array, width: number, height: number, comps: number}} image - Color channels (toColorChannels)
 * @param {{threshold1: number, threshold2: number, blur: number, blurScale?: number}} params -
 *   blurScale scales the blur sigma for an image downscaled by that factor
 * @returns {Uint8Array}
 */
function detectEdges(image, {threshold1, threshold2, blur, blurScale = 1}) {
    return cannyFromGradients(blurredGradients(image, blur, blurScale), threshold1, threshold2);
}

/**
 * Downscale interleaved pixels by averaging the source area of each target pixel
 */
function downscaleAverage(src, width, height, comps, targetWidth, targetHeight) {
    const out = new Uint8Array(targetWidth * targetHeight * comps);
    const sums = new Float64Array(comps);

    for (let ty = 0; ty < targetHeight; ty++) {
        const y0 = Math.floor(ty * height / targetHeight);
        const y1 = Math.max(y0 + 1, Math.floor((ty + 1) * height / targetHeight));

        for (let tx = 0; tx < targetWidth; tx++) {
            const x0 = Math.floor(tx * width / targetWidth);
            const x1 = Math.max(x0 + 1, Math.floor((tx + 1) * width / targetWidth));
            sums.fill(0);

            for (let y = y0; y < y1; y++)
                for (let x = x0; x < x1; x++) {
                    const i = (y * width + x) * comps;
                    for (let c = 0; c < comps; c++)
                        sums[c] += src[i + c];
                }

            const area = (y1 - y0) * (x1 - x0);
            const o = (ty * targetWidth + tx) * comps;
            for (let c = 0; c < comps; c++)
                out[o + c] = Math.round(sums[c] / area);
        }
    }

    return out;
}

module.exports = {toColorChannels, gaussianBlur, canny, blurredGradients, cannyFromGradients, detectEdges, downscaleAverage};
