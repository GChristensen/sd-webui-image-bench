/**
 * ControlNetSweepStrategy
 * Generates the same image (same seed) over a matrix of ControlNet weights x ending steps of one unit,
 * after a reference image with the unit's current values. The cells are generated diagonals first (weak and short
 * to strong and long, then strong and short to weak and long), then each time the cell farthest from those done,
 * so that a stopped sweep still covers the matrix
 */

import { QueueProcessor } from '../core/QueueProcessor.js';

/**
 * Order of the cells of a rows x columns matrix
 * @param {number} rows
 * @param {number} columns
 * @returns {Array<[number, number]>} [row, column] pairs, row 0 is the lowest weight, column 0 the lowest ending step
 */
export function sweepOrder(rows, columns) {
    const length = Math.max(rows, columns);
    const at = (k, n) => length === 1 ? 0 : Math.round(k * (n - 1) / (length - 1));
    const order = [];
    const done = new Set();

    const add = (row, column) => {
        const key = row * columns + column;

        if (!done.has(key)) {
            done.add(key);
            order.push([row, column]);
        }
    };

    for (let k = 0; k < length; k++)
        add(at(k, rows), at(k, columns));

    for (let k = 0; k < length; k++)
        add(at(length - 1 - k, rows), at(k, columns));

    // Farthest-point order of the rest; ties in row order
    while (order.length < rows * columns) {
        let best = null;
        let bestDistance = -1;

        for (let row = 0; row < rows; row++) {
            for (let column = 0; column < columns; column++) {
                if (done.has(row * columns + column))
                    continue;

                const distance = Math.min(...order.map(([r, c]) => (r - row) ** 2 + (c - column) ** 2));

                if (distance > bestDistance) {
                    best = [row, column];
                    bestDistance = distance;
                }
            }
        }

        add(...best);
    }

    return order;
}

export class ControlNetSweepStrategy extends QueueProcessor {
    constructor(uiOperations, messageBus) {
        super(uiOperations, messageBus);
        this.controlNet = null;
        this.unit = 0;
        this.paramsBefore = null;
        this.seedBefore = null;
        this.currentItem = null;
    }

    /**
     * @param {Object} options - {unit, weights: number[], ends: number[], reference: {weight, end}, seed: number|null,
     *                            controlNet: {readParams(unit), applyParams(unit, params)}} (added by the host page)
     */
    initialize(options) {
        const {weights, ends, reference} = options;

        // The cell with the reference values is the reference image, which the popup also shows in that cell:
        // generated again, its prompt would be the same, and ComfyUI, serving it from cache, would send no image
        const round = value => Math.round(Number(value) * 1000) / 1000;
        const isReference = cell => round(cell.weight) === round(reference.weight) && round(cell.end) === round(reference.end);

        this.controlNet = options.controlNet;
        this.unit = options.unit;
        this.queue = [{...reference, reference: true},
            ...sweepOrder(weights.length, ends.length)
                .map(([row, column]) => ({weight: weights[row], end: ends[column]}))
                .filter(cell => !isReference(cell))];
        this.totalItems = this.queue.length;
        this.generationId = this.createGenerationId();
    }

    async prepare(options) {
        this.paramsBefore = this.controlNet.readParams(this.unit);
        this.seedBefore = await this.uiOperations.pinSeed(options.seed ?? null);
        await this.uiOperations.setBatchCount(1);

        if (this.paramsBefore && !this.paramsBefore.enabled)
            await this.controlNet.applyParams(this.unit, {enabled: true});

        this.messageBus.publish('BEGIN_PROCESSING', {});
    }

    async processItem(item) {
        this.currentItem = item;
        await this.controlNet.applyParams(this.unit, {weight: item.weight, guidanceEnd: item.end});
        // Lets the host take the values before Generate reads them
        await this.uiOperations.sleep(500);
        await this.clickGenerate();
    }

    async finish() {
        this.isActive = false;
        this.queue = [];
        this.currentItem = null;

        // GENERATION_FINISHED resets the generation state, which would otherwise route all later images to the sweep
        try {
            if (this.paramsBefore) {
                const {weight, guidanceEnd, enabled} = this.paramsBefore;
                await this.controlNet.applyParams(this.unit, {weight, guidanceEnd, enabled});
            }

            await this.uiOperations.restoreSeed(this.seedBefore);
            await this.uiOperations.setBatchCount(1);
        } finally {
            this.paramsBefore = null;
            this.seedBefore = null;
            this.generationId = null;
            this.messageBus.publish('GENERATION_FINISHED', {});
        }
    }

    getMessageParams() {
        const item = this.currentItem;

        return {
            generationId: this.generationId,
            sweepCell: item && {weight: item.weight, end: item.end, reference: !!item.reference}
        };
    }
}
