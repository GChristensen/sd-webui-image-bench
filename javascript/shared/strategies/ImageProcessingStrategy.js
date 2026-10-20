/**
 * ImageProcessingStrategy
 * Strategy for processing/upscaling images with parameter control
 */

import { QueueProcessor } from '../core/QueueProcessor.js';

export class ImageProcessingStrategy extends QueueProcessor {
    constructor(uiOperations, messageBus) {
        super(uiOperations, messageBus);
        this.setSteps = false;
        this.setDenoising = false;
        // Generate the images again as they are (with their own Hires. fix) instead of upscaling them
        this.reproduce = false;
        this.paramsBackup = null;
        // Parameters of the current image being set
        this.applying = null;
        this.progressMonitoring = false;
    }

    /**
     * Initialize image processing queue
     * @param {Object} options - { images: [], setSteps: boolean, setDenoising: boolean, preset: string }
     */
    initialize(options) {
        if (!options.images || !options.images.length) {
            throw new Error('No images provided for processing');
        }

        this.queue = [...options.images];
        this.totalItems = options.images.length;
        this.generationId = this.createGenerationId();
        this.setSteps = options.setSteps || false;
        this.setDenoising = options.setDenoising || false;
    }

    /**
     * Prepare for processing - backup parameters and configure
     */
    async prepare(options) {
        // Notify that processing started
        this.messageBus.publish('BEGIN_PROCESSING', {});

        // Backup all parameters that the images set, restored in finish()
        this.paramsBackup = await this.uiOperations.backupImageParams();

        // Apply preset if specified
        if (options.preset) {
            await this.uiOperations.applyPreset(options.preset);
            await this.uiOperations.sleep(500);
        }

        // Start progress monitoring
        this.startProgressMonitoring();
    }

    /**
     * Process a single image
     * @param {Object} imageData - Image data with parameters
     */
    async processItem(imageData) {
        if (!imageData || !imageData.parameters) {
            return;
        }

        const parameters = imageData.parameters;

        // Set all generation parameters of the image; generating with other steps or modules reproduces
        // the image's own Hires. fix, otherwise the image is upscaled with Hires. fix.
        // finish() waits for this, so that it restores the parameters after they are set
        this.applying = (async () => {
            await this.uiOperations.applyImageParameters(parameters, {
                upscale: !this.setSteps && !this.reproduce,
                setDenoising: this.setDenoising
            });

            // The tab may have been switched to txt2img
            await this.uiOperations.setBatchCount(1);
            await this.uiOperations.sleep(500);
        })();

        try {
            await this.applying;
        } finally {
            this.applying = null;
        }

        // Stopped while the parameters were being set
        if (!this.isActive)
            return;

        // Click generate button
        await this.clickGenerate();
    }

    /**
     * Override reportProgress to include sub-progress from current generation
     */
    reportProgress() {
        if (this.totalItems === 0) return;

        const chunk = 1 / this.totalItems;
        const completed = this.getCompletedItems();
        let progress = completed * chunk * 100;

        // Add current generation progress
        const currentProgress = this.uiOperations.getGenerationProgress();
        if (currentProgress !== null && !isNaN(currentProgress) && currentProgress < 100) {
            progress += currentProgress * chunk;
        }

        this.messageBus.publish('GENERATION_PROGRESS', { progress, completed, total: this.totalItems });
    }

    /**
     * Start monitoring progress with sub-progress
     */
    async startProgressMonitoring() {
        this.progressMonitoring = true;

        const monitorProgress = async () => {
            while (this.progressMonitoring && this.isActive) {
                await this.uiOperations.sleep(1000);
                this.reportProgress();
            }
        };

        // Start monitoring in background
        monitorProgress();
    }

    /**
     * Finish processing and restore parameters
     */
    async finish() {
        this.isActive = false;
        this.progressMonitoring = false;
        this.queue = [];

        // Taken before awaiting, so that a finish request arriving meanwhile does not restore twice
        const paramsBackup = this.paramsBackup;
        this.generationId = null;
        this.paramsBackup = null;
        this.setDenoising = false;
        this.setSteps = false;
        this.reproduce = false;

        // Restore the parameters set before processing (also when interrupted)
        await this.applying?.catch(() => {});
        await this.uiOperations.restoreImageParams(paramsBackup);

        this.messageBus.publish('GENERATION_FINISHED', {});
    }

    /**
     * Get message parameters for saved images
     */
    getMessageParams() {
        const params = {
            generationId: this.generationId
        };

        if (this.setSteps) {
            params.setSteps = true;
        }

        return params;
    }
}
