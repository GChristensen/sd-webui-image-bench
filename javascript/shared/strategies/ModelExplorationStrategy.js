/**
 * ModelExplorationStrategy
 * Strategy for exploring different models by generating images with each
 */

import { QueueProcessor } from '../core/QueueProcessor.js';

export class ModelExplorationStrategy extends QueueProcessor {
    constructor(uiOperations, messageBus) {
        super(uiOperations, messageBus);
        this.currentModel = null;
        this.modelBeforeExplore = null;
        this.uiPresetBeforeExplore = null;
        // VAE / Text Encoder of Forge Neo, which the UI presets change
        this.modulesBeforeExplore = null;
        this.paramsBeforeExplore = null;
        this.paramsBeforeModel = null;
        this.promptBeforeExplore = null;
        this.currentLora = null;
        this.exploringLoras = false;
        this.loraBeforeExplore = null;
        this.invalidated = false;
        this.seed = null;
        this.seedControlBeforeExplore = null;
        // The item being prepared, which finish() waits for before restoring
        this.processing = null;
    }

    /**
     * Initialize the exploration queue
     * @param {Object} options - { models: [], loras: [{name, prompt, weight}], loraFreeImages: boolean, generateImages: number,
     *                             matrix: boolean }; a matrix generates every image with the same random seed
     *                           SD WebUI applies a LoRA through its prompt, ComfyUI through the node marked ib:lora
     */
    initialize(options) {
        console.log('[ModelExploration] initialize() called with options:', options);

        if (!options.models || !options.models.length) {
            console.error('[ModelExploration] No models provided!');
            throw new Error('No models provided for exploration');
        }

        // Build queue of model x LoRA entries; null is the LoRA-free run,
        // skipped when LoRAs are explored and LoRA-free images are disabled
        const loras = options.loras || [];
        const loraVariants = loras.length && options.loraFreeImages === false ? loras : [null, ...loras];

        this.queue = [];
        for (const model of options.models) {
            for (const lora of loraVariants) {
                for (let i = 0; i < options.generateImages; i++) {
                    this.queue.push({model, lora});
                }
            }
        }

        this.totalItems = this.queue.length;
        this.generationId = this.createGenerationId();
        this.currentModel = options.models[0];
        this.seed = options.matrix ? Math.floor(Math.random() * 2 ** 32) : null;

        console.log('[ModelExploration] Queue built with', this.totalItems, 'items');
        console.log('[ModelExploration] Models to explore:', options.models.map(m => m.title).join(', '));
        console.log('[ModelExploration] LoRAs to explore:', (options.loras || []).map(l => l.name).join(', '));
        console.log('[ModelExploration] Images per model/LoRA:', options.generateImages);
        console.log('[ModelExploration] Generation ID:', this.generationId);
    }

    /**
     * Prepare for exploration - set initial model and parameters
     */
    async prepare(options) {
        console.log('[ModelExploration] prepare() starting...');

        // Save current model to restore later
        console.log('[ModelExploration] Backing up current model...');
        this.modelBeforeExplore = await this.uiOperations.backupModel();
        console.log('[ModelExploration] Backed up model:', this.modelBeforeExplore);
        this.uiPresetBeforeExplore = await this.uiOperations.backupUiPreset();
        this.modulesBeforeExplore = this.uiOperations.getModules?.() ?? null;

        if (options.models.some(m => m.params)) {
            this.paramsBeforeExplore = await this.uiOperations.backupGenerationParams();
            console.log('[ModelExploration] Backed up generation params:', this.paramsBeforeExplore);
        }

        if (options.loras?.length) {
            this.promptBeforeExplore = await this.uiOperations.getPrompt();
            console.log('[ModelExploration] Backed up prompt:', this.promptBeforeExplore);
            this.loraBeforeExplore = await this.uiOperations.backupLora();
            this.exploringLoras = true;
        }

        // Set initial model
        console.log('[ModelExploration] Setting initial model to:', this.currentModel.title);
        await this.uiOperations.applyUiPresetForModel(this.currentModel.title);
        await this.uiOperations.restoreModel(this.currentModel.title);

        // Configure generation parameters
        console.log('[ModelExploration] Configuring generation parameters (seed=' + (this.seed ?? -1) + ', batch=1)');
        await this.uiOperations.setupBasicGeneration(this.seed ?? -1, 1);

        // Keep ComfyUI from changing the shared seed of a matrix after each queued prompt
        if (this.seed !== null && this.uiOperations.setControlAfterGenerate) {
            this.seedControlBeforeExplore = this.uiOperations.getControlAfterGenerate();
            this.uiOperations.setControlAfterGenerate('fixed');
        }

        // Notify that processing started
        console.log('[ModelExploration] Publishing BEGIN_PROCESSING event');
        this.messageBus.publish('BEGIN_PROCESSING', {});
        console.log('[ModelExploration] prepare() complete');
    }

    /**
     * Process a single model/LoRA exploration
     * @param {Object} item - { model: {title, params}, lora: {name, prompt} | null }
     */
    async processItem(item) {
        this.processing = this.prepareItem(item);

        try {
            await this.processing;
        } finally {
            this.processing = null;
        }
    }

    /**
     * Set the model, prompt, LoRA and parameters of an item and generate it; stopped meanwhile, it ends at the next
     * step, so that finish() restores after it
     * @param {Object} item - { model: {title, params}, lora: {name, prompt} | null }
     */
    async prepareItem({model, lora}) {
        console.log('[ModelExploration] processItem() called for model:', model.title, 'LoRA:', lora?.name ?? 'none');
        console.log('[ModelExploration] Current model:', this.currentModel.title);

        // Switch model if different from current
        if (this.currentModel.title !== model.title) {
            console.log('[ModelExploration] Switching model from', this.currentModel.title, 'to', model.title);
            await this.restoreParamsBeforeModel();
            await this.uiOperations.applyUiPresetForModel(model.title);
            await this.uiOperations.restoreModel(model.title);
            this.currentModel = model;
            console.log('[ModelExploration] Model switched successfully');
        } else {
            console.log('[ModelExploration] Model is already loaded, skipping switch');
        }

        if (!this.isActive)
            return;

        // Set the prompt for every image, so the LoRA string is removed once its combination is done
        if (this.promptBeforeExplore !== null) {
            const prompt = lora
                ? [this.promptBeforeExplore, lora.prompt].filter(Boolean).join(' ')
                : this.promptBeforeExplore;

            console.log('[ModelExploration] Setting prompt:', prompt);
            await this.uiOperations.setPrompt(prompt);
        }

        if (this.exploringLoras) {
            await this.uiOperations.setLora(lora);
        }

        this.currentLora = lora?.name ?? null;

        console.log('[ModelExploration] Waiting 1 second before generation...');
        await this.uiOperations.sleep(1000);

        if (!this.isActive)
            return;

        // Apply per-model parameters after the wait, so the Forge UI preset reset doesn't overwrite them
        if (model.params) {
            // Back up once per model, on its first image, to restore when its exploration is complete
            if (!this.paramsBeforeModel) {
                this.paramsBeforeModel = await this.uiOperations.backupGenerationParams();
                console.log('[ModelExploration] Backed up generation params before model:', this.paramsBeforeModel);
            }

            console.log('[ModelExploration] Applying generation params:', model.params);
            await this.uiOperations.applyGenerationParams(model.params);
            await this.uiOperations.sleep(333);
        }

        // Set the shared seed of a matrix again, in case a UI preset or model switch has reset it
        if (this.seed !== null) {
            await this.uiOperations.setupBasicGeneration(this.seed, 1);
        }

        // Click generate button
        console.log('[ModelExploration] Clicking generate button');
        if (await this.clickGenerate())
            console.log('[ModelExploration] Generate button clicked, waiting for image callback...');
    }

    /**
     * Restore generation params changed by the per-model params of the current model
     */
    async restoreParamsBeforeModel() {
        if (this.paramsBeforeModel) {
            console.log('[ModelExploration] Restoring generation params before model:', this.paramsBeforeModel);
            await this.uiOperations.restoreGenerationParams(this.paramsBeforeModel);
            this.paramsBeforeModel = null;
        }
    }

    /**
     * Finish exploration and restore original model
     */
    async finish() {
        console.log('[ModelExploration] finish() called');
        this.isActive = false;
        this.queue = [];

        // An item being prepared would set its values after they are restored
        await this.processing?.catch(() => {});

        await this.restoreParamsBeforeModel();

        if (this.promptBeforeExplore !== null) {
            console.log('[ModelExploration] Restoring prompt:', this.promptBeforeExplore);
            await this.uiOperations.setPrompt(this.promptBeforeExplore);
            this.promptBeforeExplore = null;
        }

        if (this.exploringLoras) {
            console.log('[ModelExploration] Restoring LoRA:', this.loraBeforeExplore);
            await this.uiOperations.restoreLora(this.loraBeforeExplore);
            this.loraBeforeExplore = null;
            this.exploringLoras = false;
        }

        this.currentLora = null;

        if (this.seed !== null) {
            console.log('[ModelExploration] Resetting the shared matrix seed');
            await this.uiOperations.setupBasicGeneration(-1, 1);

            if (this.seedControlBeforeExplore !== null && this.uiOperations.setControlAfterGenerate) {
                this.uiOperations.setControlAfterGenerate(this.seedControlBeforeExplore);
            }

            this.seed = null;
            this.seedControlBeforeExplore = null;
        }

        // Restore original model if saved
        if (this.modelBeforeExplore) {
            console.log('[ModelExploration] Restoring original model:', this.modelBeforeExplore);
            await this.uiOperations.restoreUiPreset(this.uiPresetBeforeExplore);
            await this.uiOperations.restoreModel(this.modelBeforeExplore);
            await this.uiOperations.restoreModules?.(this.modulesBeforeExplore);
            this.modelBeforeExplore = null;
            this.uiPresetBeforeExplore = null;
            this.modulesBeforeExplore = null;
        } else {
            console.log('[ModelExploration] No model to restore');
        }

        // Restore after the wait, so the Forge UI preset reset doesn't overwrite them
        if (this.paramsBeforeExplore) {
            console.log('[ModelExploration] Restoring generation params:', this.paramsBeforeExplore);
            await this.uiOperations.sleep(1000);
            await this.uiOperations.restoreGenerationParams(this.paramsBeforeExplore);
            this.paramsBeforeExplore = null;
        }

        this.generationId = null;
        console.log('[ModelExploration] Publishing GENERATION_FINISHED event');
        this.messageBus.publish('GENERATION_FINISHED', {});
        console.log('[ModelExploration] Exploration finished');
    }

    /**
     * Invalidate this exploration (called when "Send to Txt2Img" is used)
     */
    invalidate() {
        this.invalidated = true;
    }

    /**
     * Check if exploration is invalidated
     */
    isInvalidated() {
        return this.invalidated;
    }

    /**
     * Get message parameters for saved images
     */
    getMessageParams() {
        return {
            generationId: this.generationId,
            exploreLora: this.currentLora
        };
    }
}
