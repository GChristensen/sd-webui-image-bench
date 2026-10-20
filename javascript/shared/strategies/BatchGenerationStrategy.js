/**
 * BatchGenerationStrategy
 * Strategy for batch generation with optional variations
 */

import { QueueProcessor } from '../core/QueueProcessor.js';

export class BatchGenerationStrategy extends QueueProcessor {
    constructor(uiOperations, messageBus) {
        super(uiOperations, messageBus);
        this.isImg2Img = false;
        this.isVariations = false;
        this.nImagesToGenerate = 100;
        this.config = null;
        this.savedImages = 0;
        this.isForever = false;
    }

    isWebUI() {
        return this.uiOperations.getPlatform() === 'webui';
    }

    /**
     * Initialize batch generation
     * @param {Object} options - { img2img: boolean, strength: number (for variations), preset: string }
     */
    initialize(options) {
        this.isImg2Img = options.img2img || false;
        this.isVariations = options.strength !== undefined;
        this.nImagesToGenerate = options.generateImages || 100;
        this.generationId = this.createGenerationId();
        this.savedImages = 0;
        // -1 images: generate until stopped (WebUI "Generate forever", ComfyUI re-queues an item per image)
        this.isForever = this.nImagesToGenerate === -1;

        // Detect platform to determine queue structure
        const platform = this.uiOperations.getPlatform();

        if (platform === 'comfyui') {
            // ComfyUI: Create N queue items (one per image)
            // Each processItem() call queues one workflow
            this.queue = [];
            const nItems = this.isForever ? 1 : this.nImagesToGenerate;
            for (let i = 0; i < nItems; i++) {
                this.queue.push({ index: i });
            }
            this.totalItems = this.queue.length;
        } else {
            // SD WebUI: Single queue item, batch count parameter handles multiple images
            this.queue = [true];
            this.totalItems = 1;
        }
    }

    /**
     * Prepare for batch generation
     */
    async prepare(options) {
        this.config = options.config || {};

        // Notify that processing started
        this.messageBus.publish('BEGIN_PROCESSING', {});

        const isImg2ImgTab = this.uiOperations.isImg2ImgTab();
        const platform = this.uiOperations.getPlatform();

        // Set seed
        if (this.isVariations) {
            await this.uiOperations.enableVariations(options.strength);
        } else {
            await this.uiOperations.setInputValue('TXT2IMG_SEED', -1);
        }

        // Set batch count (only for WebUI, no-op in ComfyUI)
        if (platform === 'webui') {
            const nImagesToGenerate = this.isForever
                ? 1
                : this.nImagesToGenerate || this.config.defaultBatches || 100;
            await this.uiOperations.setBatchCount(nImagesToGenerate);
        }

        // Disable hires fix for txt2img (WebUI only)
        if (platform === 'webui' && !isImg2ImgTab) {
            this.uiOperations.toggleHiresFix(false, true);
        }
    }

    /**
     * Process the batch generation (click generate button)
     */
    async processItem(item) {
        await this.uiOperations.sleep(500);

        if (this.isForever && this.isWebUI())
            await this.startGenerateForever();
        else
            await this.clickGenerate();
    }

    /**
     * Start WebUI "Generate forever", or stop the strategy if it is not available
     */
    async startGenerateForever() {
        if (await this.uiOperations.waitReadyToGenerate() && this.uiOperations.setGenerateForever(true))
            return;

        console.warn('[BatchGenerationStrategy] Unable to start "Generate forever"');

        if (this.isActive) {
            this.messageBus.publish('STRATEGY_FINISH_REQUEST');
            this.messageBus.publish('GENERATION_FINISHED', {});
        }
    }

    /**
     * On WebUI the whole batch is a single generation: processNext() is called on each saved image,
     * which only advances the progress. The strategy is finished by BATCH_GENERATION_FINISHED
     * when the interrupt button is hidden.
     * On ComfyUI generating forever queues the next item, so the queue never runs out until stopped
     */
    async processNext() {
        if (this.isWebUI() && this.queue.length === 0) {
            this.savedImages += 1;
            this.reportProgress();
            return;
        }

        if (this.isForever && this.isActive && this.queue.length === 0)
            this.queue.push({ index: ++this.savedImages });

        await super.processNext();
    }

    /**
     * On WebUI report the overall progress over the batch: saved images / batch count
     */
    reportProgress() {
        // The popup shows an indeterminate progress when generating forever
        if (this.isForever)
            return;

        if (!this.isWebUI())
            return super.reportProgress();

        const completed = Math.min(this.savedImages, this.nImagesToGenerate);
        const progress = (completed / this.nImagesToGenerate) * 100;

        this.messageBus.publish('GENERATION_PROGRESS', { progress, completed, total: this.nImagesToGenerate });
    }

    /**
     * Finish batch generation and cleanup
     */
    async finish() {
        this.isActive = false;

        const platform = this.uiOperations.getPlatform();

        if (this.isForever) {
            this.isForever = false;
            if (platform === 'webui')
                this.uiOperations.setGenerateForever(false);
        }

        // Reset batch count (only for WebUI)
        if (platform === 'webui') {
            await this.uiOperations.setBatchCount(1);
        }

        // Reset variations if used
        if (this.isVariations) {
            this.isVariations = false;
            await this.uiOperations.disableVariations();
        }

        this.generationId = null;
        this.isImg2Img = false;

        await this.uiOperations.sleep(1000);

        // Publish GENERATION_FINISHED event
        if (platform === 'comfyui')
            this.messageBus.publish('GENERATION_FINISHED', {});
    }

    /**
     * Get message parameters for saved images
     */
    getMessageParams() {
        const params = {
            generationId: this.generationId
        };

        if (this.isImg2Img) {
            params.img2img = true;
        }

        return params;
    }
}
