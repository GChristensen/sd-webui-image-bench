/**
 * CSS Selectors for SD WebUI/Forge
 * Centralized constants to avoid duplication and ease maintenance
 */

// Element id suffixes of a Forge "ControlNet Integrated" unit, by name
const CONTROLNET_ELEMENT_IDS = {
    enabled: 'controlnet_enable_checkbox',
    pixelPerfect: 'controlnet_pixel_perfect_checkbox',
    allowPreview: 'controlnet_preprocessor_preview_checkbox',
    useMask: 'controlnet_mask_upload_checkbox',
    // img2img only: the unit uses its own image instead of the img2img image
    independent: 'controlnet_same_img2img_checkbox',
    controlType: 'controlnet_type_filter_radio',
    preprocessor: 'controlnet_preprocessor_dropdown',
    model: 'controlnet_model_dropdown',
    runPreprocessor: 'controlnet_trigger_preprocessor',
    refreshModels: 'controlnet_refresh_models',
    weight: 'controlnet_control_weight_slider',
    timestepRange: 'controlnet_control_step_slider',
    // Preprocessor sliders, relabeled and shown or hidden by Forge for each preprocessor
    processorRes: 'controlnet_preprocessor_resolution_slider',
    thresholdA: 'controlnet_threshold_A_slider',
    thresholdB: 'controlnet_threshold_B_slider',
    controlMode: 'controlnet_control_mode_radio',
    resizeMode: 'controlnet_resize_mode_radio',
    // Forge canvases: the control image, its mask and the preprocessor preview
    image: 'input_image',
    mask: 'mask_image',
    preview: 'generated_image'
};

export const SELECTORS = {
    // Generation buttons
    TXT2IMG_GENERATE: 'txt2img_generate',
    IMG2IMG_GENERATE: 'img2img_generate',
    TXT2IMG_INTERRUPT: 'txt2img_interrupt',
    IMG2IMG_INTERRUPT: 'img2img_interrupt',
    TXT2IMG_SKIP: 'txt2img_skip',
    IMG2IMG_SKIP: 'img2img_skip',
    // "Interrupting..." placeholder shown until an interrupted job ends (absent in older versions)
    TXT2IMG_INTERRUPTING: 'txt2img_interrupting',
    IMG2IMG_INTERRUPTING: 'img2img_interrupting',

    // Prompts
    TXT2IMG_PROMPT: '#txt2img_prompt textarea',
    TXT2IMG_NEG_PROMPT: '#txt2img_neg_prompt textarea',

    // Seeds
    TXT2IMG_SEED: '#txt2img_seed input',
    TXT2IMG_SUBSEED: '#txt2img_subseed input',
    TXT2IMG_SUBSEED_STRENGTH: '#txt2img_subseed_strength input',
    TXT2IMG_SUBSEED_SHOW: '#txt2img_subseed_show input',

    // Parameters
    TXT2IMG_STEPS: '#txt2img_steps input',
    TXT2IMG_CFG_SCALE: '#txt2img_cfg_scale input',
    TXT2IMG_DISTILLED_CFG: '#txt2img_distilled_cfg_scale input',
    TXT2IMG_DISTILLED_CFG_ID: 'txt2img_distilled_cfg_scale',
    TXT2IMG_WIDTH: '#txt2img_width input',
    TXT2IMG_HEIGHT: '#txt2img_height input',
    TXT2IMG_BATCH_COUNT: '#txt2img_batch_count input[type="number"]',
    IMG2IMG_BATCH_COUNT: '#img2img_batch_count input[type="number"]',
    TXT2IMG_DENOISING: '#txt2img_denoising_strength input',
    TXT2IMG_SAMPLING: '#txt2img_sampling input',
    TXT2IMG_SCHEDULER: '#txt2img_scheduler input',

    // img2img prompts and parameters
    IMG2IMG_PROMPT: '#img2img_prompt textarea',
    IMG2IMG_NEG_PROMPT: '#img2img_neg_prompt textarea',
    IMG2IMG_SEED: '#img2img_seed input',
    IMG2IMG_SUBSEED: '#img2img_subseed input',
    IMG2IMG_SUBSEED_STRENGTH: '#img2img_subseed_strength input',
    IMG2IMG_SUBSEED_SHOW: '#img2img_subseed_show input',
    IMG2IMG_STEPS: '#img2img_steps input',
    IMG2IMG_CFG_SCALE: '#img2img_cfg_scale input',
    IMG2IMG_DISTILLED_CFG: '#img2img_distilled_cfg_scale input',
    IMG2IMG_DISTILLED_CFG_ID: 'img2img_distilled_cfg_scale',
    IMG2IMG_WIDTH: '#img2img_width input',
    IMG2IMG_HEIGHT: '#img2img_height input',
    IMG2IMG_DENOISING: '#img2img_denoising_strength input',
    IMG2IMG_SAMPLING: '#img2img_sampling input',
    IMG2IMG_SCHEDULER: '#img2img_scheduler input',

    // img2img parameters mirrored in the Generate tab of the popup (radio groups, set by their choice labels)
    IMG2IMG_RESIZE_MODE_ID: 'resize_mode',
    IMG2IMG_MASK_MODE_ID: 'img2img_mask_mode',
    IMG2IMG_INPAINT_AREA_ID: 'img2img_inpaint_full_res',
    IMG2IMG_MASKED_CONTENT_ID: 'img2img_inpainting_fill',
    IMG2IMG_MASK_BLUR: '#img2img_mask_blur input',
    IMG2IMG_INPAINT_PADDING: '#img2img_inpaint_full_res_padding input',
    // "Resize to" / "Resize by" tabs of the img2img size: the width and height apply only with "Resize to"
    IMG2IMG_RESIZE_TABS: 'img2img_tabs_resize',
    IMG2IMG_PROMPT_ID: 'img2img_prompt',
    IMG2IMG_NEG_PROMPT_ID: 'img2img_neg_prompt',
    IMG2IMG_TOKEN_COUNTER: 'img2img_token_counter',
    IMG2IMG_NEG_TOKEN_COUNTER: 'img2img_negative_token_counter',
    IMG2IMG_REUSE_SEED: 'img2img_reuse_seed',
    IMG2IMG_REUSE_SUBSEED: 'img2img_reuse_subseed',
    IMG2IMG_LIVE_PREVIEW: '#img2img_gallery .livePreview img',

    // img2img mode tabs and the input images: the img2img canvas (Forge) and the inpaint upload images
    IMG2IMG_MODE_TABS: 'mode_img2img',
    IMG2IMG_IMG2IMG_TAB: 'img2img_img2img_tab',
    IMG2IMG_CANVAS: 'img2img_image',
    IMG2IMG_CANVAS_IMAGE: '#img2img_image img.forge-image',
    IMG2IMG_CANVAS_FILE_INPUT: '#img2img_image input.forge-file-upload',
    IMG2IMG_INPAINT_UPLOAD_IMAGE_IMG: '#img_inpaint_base img',
    IMG2IMG_INPAINT_UPLOAD_MASK_IMG: '#img_inpaint_mask img',
    IMG2IMG_INPAINT_UPLOAD_TAB: 'img2img_inpaint_upload_tab',
    IMG2IMG_INPAINT_UPLOAD_IMAGE: 'img_inpaint_base',
    IMG2IMG_INPAINT_UPLOAD_MASK: 'img_inpaint_mask',
    IMAGE_COMPONENT: '[data-testid="image"]',
    FILE_INPUT: 'input[type="file"]',

    // Model/VAE/Settings
    MODEL_CHECKPOINT: '#setting_sd_model_checkpoint input, .model_selection input',
    MODEL_REFRESH_BUTTON: '#refresh_sd_model_checkpoint, #forge_refresh_checkpoint',
    // Hidden buttons clicked by the Refresh buttons of the LoRA extra networks pages, they rescan the LoRAs
    LORA_REFRESH_BUTTON: '#txt2img_lora_extra_refresh_internal, #img2img_lora_extra_refresh_internal',
    SD_VAE: '#setting_sd_vae input',
    CLIP_SKIP: '#setting_CLIP_stop_at_last_layers input',
    FORGE_UI_PRESET: '#forge_ui_preset input',
    FORGE_UI_PRESET_ID: 'forge_ui_preset',
    // Multiselect dropdown "VAE / Text Encoder" of Forge Neo
    FORGE_MODULES_ID: 'setting_sd_modules',

    // Hires fix
    HIRES_CHECKBOX: 'txt2img_hr-visible-checkbox',
    HIRES_SCALE: '#txt2img_hr_scale input',
    HIRES_STEPS: '#txt2img_hires_steps input',
    HIRES_UPSCALER: '#txt2img_hr_upscaler input',
    HIRES_UPSCALER_ID: 'txt2img_hr_upscaler',

    // txt2img extras mirrored in the Generate tab of the popup
    TXT2IMG_PROMPT_ID: 'txt2img_prompt',
    TXT2IMG_NEG_PROMPT_ID: 'txt2img_neg_prompt',
    TXT2IMG_TOKEN_COUNTER: 'txt2img_token_counter',
    TXT2IMG_NEG_TOKEN_COUNTER: 'txt2img_negative_token_counter',
    TXT2IMG_REUSE_SEED: 'txt2img_reuse_seed',
    TXT2IMG_REUSE_SUBSEED: 'txt2img_reuse_subseed',
    TXT2IMG_LIVE_PREVIEW: '#txt2img_gallery .livePreview img',

    // Config presets
    CONFIG_PRESET_TXT2IMG_DROPDOWN: '#config_preset_txt2img_dropdown input',
    CONFIG_PRESET_WRAPPER: (kind) => `config_preset_wrapper_${kind}`,
    RESULTS_DIV: (kind) => `${kind}_results`,

    // Forge "ImageStitch Integrated" (reference images of the edit models), by tab: txt2img or img2img;
    // its upload image and buttons have no ids and are located inside the accordion
    IMAGE_STITCH_GALLERY: (tab) => `script_${tab}_imagestitch_integrated_ref_latent`,
    IMAGE_STITCH_THUMBNAIL: '.thumbnail-item',
    // Settings shown in a generation tab ("Settings in UI"), which override the global settings in that tab
    EXTRA_OPTIONS: (tab) => `extra_options_${tab}`,
    SETTING_CHECKBOX: (name) => `#setting_${name} input[type="checkbox"]`,

    // Forge "ControlNet Integrated" mirrored in the ControlNet tab of the popup, by tab (txt2img or img2img)
    // and unit index (0-based; WebUI labels the units from 1)
    CONTROLNET_ELEMENT: (tab, unit, name) => `${tab}_controlnet_ControlNet-${unit}_${CONTROLNET_ELEMENT_IDS[name]}`,
    CONTROLNET_TABS: (tab) => `${tab}_controlnet_tabs`,
    TAB_BUTTONS: ':scope > .tab-nav button, :scope > div > .tab-nav button',
    FORGE_CANVAS_IMAGE: 'img.forge-image',
    FORGE_CANVAS_FILE_INPUT: 'input.forge-file-upload',
    FORGE_CANVAS_REMOVE: '[id^="removeButton_"]',
    // gradio_rangeslider (the timestep range): number inputs of both ends
    RANGE_SLIDER_MIN: 'input[data-testid="min-input"]',
    RANGE_SLIDER_MAX: 'input[data-testid="max-input"]',
    // Hidden OpenPose elements of the preprocessor preview group: the pose JSON link (a data URL), and the textbox
    // and button that render an edited pose into the preview
    CONTROLNET_PREVIEW_GROUP: '.cnet-generated-image-group',
    CONTROLNET_POSE_LINK: '.cnet-download-pose a',
    CONTROLNET_POSE_TEXTBOX: '.cnet-pose-json textarea',
    CONTROLNET_POSE_RENDER: '.cnet-render-pose',
    // Gradio slider: its range input and label
    RANGE_INPUT: 'input[type="range"]',
    BLOCK_LABEL: '[data-testid="block-info"]',
    CHECKBOX_INPUT: 'input[type="checkbox"]',
    NUMBER_INPUT: 'input[type="number"]',
    DROPDOWN_INPUT: 'input',

    // Progress
    PROGRESS_BAR: '.progressDiv .progress',

    // Dropdown elements
    DROPDOWN_BLOCK: '.block',
    DROPDOWN_LIST: 'ul',
    DROPDOWN_OPTION: 'li',
    // Chosen values of a multiselect dropdown: a token with the value and its remove button
    MULTISELECT_TOKEN: '.token',
    MULTISELECT_TOKEN_REMOVE: '.token-remove',

    // Header of a Gradio accordion, a child of the accordion block; it has the "open" class while expanded
    ACCORDION_LABEL_WRAP: '.label-wrap',
    ACCORDION_OPEN_CLASS: 'open',

    // Forge detection
    FORGE_INDICATOR: '[id^="forge"]',

    // PNG Info / Send to
    SEND_TO_TXT2IMG: '#tab_pnginfo #txt2img_tab',

    // Quick settings
    QUICK_SETTINGS: 'quicksettings'
};

/**
 * Helper to get element by ID (without # prefix)
 * @param {string} id - Element ID
 * @returns {HTMLElement|null}
 */
export function getElementById(id) {
    return document.getElementById(id);
}

/**
 * Helper to query selector
 * @param {string} selector - CSS selector
 * @returns {HTMLElement|null}
 */
export function querySelector(selector) {
    return document.querySelector(selector);
}

/**
 * Helper to query all selectors
 * @param {string} selector - CSS selector
 * @returns {NodeList}
 */
export function querySelectorAll(selector) {
    return document.querySelectorAll(selector);
}
