# Qwen-Image-2.1 Reference

## Overview

- **Model:** Qwen team (Alibaba), 2026-09; new architecture, not derived from the 20B Qwen-Image (its LoRAs and ControlNets do not load)
- **Backbone:** single-stream DiT, 32 layers, 7B, mixed-granularity attention with a prefix KV cache of the text and references
- **Text:** Qwen3-VL-8B (VLM), also sees the reference images
- **Latent:** Qwen-Image 2.1 VAE, 64 ch, 16x, RGBA → multiples of 32
- **Strengths:** native transparency (RGBA), 2K output, generation and up-to-10-reference editing in one checkpoint, typography

## Encoder/VAE
- Repos: HF [Qwen/Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) · ComfyUI [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1)
- Text encoder: `qwen3vl_8b_int8_convrot.safetensors` (bf16: `qwen3vl_8b_bf16.safetensors`)
  - ComfyUI: `CLIPLoader`, type = `qwen_image`
- VAE: `qwen_image_2.1_vae_bf16.safetensors` (64-ch, 16×, RGBA)

## Recommended Defaults (Base, ComfyUI)

``` text
steps:           25 (40 for finals)
cfg:             1.0   # true CFG is OFF; never leave KSampler default of 8
sampler:         euler
scheduler:       simple
resolution:      1248x832 drafts / 2048x2048 finals
negative_prompt: none (ignored at cfg 1.0)
denoise:         1.0
```

## Recommended Defaults (Base, diffusers)

``` text
pipeline:        QwenImage21Pipeline
steps:           40
true_cfg_scale:  1.0   # >1 needs a negative prompt and doubles compute
scheduler:       pipeline default (flow-match, dynamic shift)
resolution:      2048x2048
negative_prompt: none
offload:         enable_model_cpu_offload() on 24 GB with bf16
```

## Recommended Defaults (Viggle Turbo v0.2.1)

``` text
lora:            Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors
lora_strength:   1.0   # load via "Viggle Turbo LoRA (unmerged)" node, not stock loader
steps:           6
sigmas:          1.0, 0.9375, 0.875, 0.75, 0.5, 0.25   # "Viggle Turbo Sigmas" node
cfg:             1.0   # BasicGuider, no CFG
sampler:         euler
negative_prompt: none
resolution:      1024x1024 (2K not validated)
```

## Recommended Defaults (GGUF)

``` text
loader:          Unet Loader (GGUF), leejet/ComfyUI-GGUF fork
quant:           Q8_0 on 24 GB, Q4_K_M on 12–16 GB
everything else: same as Base, ComfyUI
```

## Variants

| Variant              | What it is                   | License       |
|----------------------|------------------------------|---------------|
| base bf16            | Full precision, 7B DiT       | Qwen Research |
| base int8_convrot    | Comfy-Org quant, 7.3 GB      | Qwen Research |
| Unsloth int8 / FP8   | Quant for diffusers          | Qwen Research |
| \*-GGUF              | Community quants             | Qwen Research |
| viggle-turbo v0.2.1  | 6-step DMD distill LoRA      | Qwen Research |
| Fun-Controlnet-Union | ControlNet branch, 7.0 GB    | Qwen Research |
| PE-T2I / PE-I2I      | Prompt rewriter LLMs (9B)    | \[?\]         |

Qwen Research License = non-commercial only.

## Resolution

| Ratio | Native 2K   | ~1 MP draft |
|-------|-------------|-------------|
| 1:1   | 2048x2048   | 1024x1024   |
| 4:3   | 2400x1792   | 1152x864    |
| 3:4   | 1792x2400   | 864x1152    |
| 3:2   | 2528x1696   | 1248x832    |
| 2:3   | 1696x2528   | 832x1248    |
| 16:9  | 2752x1536   | 1536x864    |
| 9:16  | 1536x2752   | 864x1536    |

- Multiple of 32.
- Practical min ~1024² area; above the 2K presets untested \[?\].
- ComfyUI Resolution Selector: 4.0 MP ≈ 2048², 1.0 MP ≈ 1024².
- Edit output follows the **first** reference's aspect ratio in ComfyUI (last in diffusers).

Notes:

- On RTX 3090 + 32 GB RAM use the int8 pair (~17 GB). The bf16 pair (~31.7 GB) will thrash RAM.
- FP8 gives no speedup on Ampere (memory only); int8 is the better format for a 3090.
- Prefix KV cache is on by default. Same seed with cache on/off gives different images.
- Old city96 GGUF loader fails with "Unknown model architecture!" — use the leejet fork.
- Old Qwen-Image Lightning LoRAs do not work on 2.1.

## Prompting

- Style: long natural-language descriptions, not booru tags.
- Structure: subject → action/pose → setting → lighting/camera → style → literal text in "quotes".
- Optional prompt enhancer: PE-T2I / PE-I2I via `TextGenerate` node (needs NVIDIA driver ≥ 580).
- Token budget: no documented cap; truncation behavior unknown \[?\].
- Weighting syntax (word:1.2): unreliable with an LLM encoder \[?\].
- Negative prompts: no-op at cfg 1.0.
- Text rendering: strong — posters, infographics, dense small text.
- Transparency (RGBA): wrap the prompt as
  "This is an RGBA image with transparency. <description>. The image has alpha channel and the
  background is transparent."
- Edit prompts address references as `<image1>`, `<image2>`, … in slot order.

Two example prompts:

- "Clean flat vector infographic titled "FROM CHERRY TO CUP" showing five numbered steps left to
  right, each with an icon and a one-word label: 1 Harvest, 2 Process, 3 Roast, 4 Grind, 5 Brew.
  Earthy palette, generous white space, all labels crisp and legible."
- "Street portrait on a brownstone stoop at golden hour. A man in denim-on-denim sits on the
  steps, elbows on knees, gold rings catching the light. Warm brick background softly out of
  focus. Shot on 85mm at f/1.8, natural skin texture."

## Generation modes

| Mode               | Support                            |
|--------------------|------------------------------------|
| txt2img            | Native                             |
| txt2img RGBA       | Native                             |
| img2img            | Via denoise < 1 \[?\]              |
| Inpaint            | Native (mask / circle + prompt)    |
| Outpaint           | Via edit instruction \[?\]         |
| Instruct-edit      | Native, same checkpoint            |
| Multi-reference    | Native, up to 10 refs              |
| Reference/identity | Native (people / products)         |
| Background removal | Native (edit template)             |

- No dedicated inpaint checkpoint; Fun-Controlnet-Union has an inpaint mode.
- Reference limits differ by frontend: Qwen 10, ComfyUI node 16 slots, vLLM 4, turbo LoRA ≤3.
- img2img denoise not published; start at 0.2–0.35 for refinement, 0.35–0.6 for restyle \[?\].
  For "change X" tasks use instruct-edit instead.
- Background removal prompt: "Remove the background, and output a PNG image".

## Edit Modes

- Checkpoint: the same Qwen-Image-2.1 checkpoint (and the viggle-turbo LoRA) generates and
  edits.
- Mechanism: the Qwen3-VL encoder sees the references and their latents join the sequence; the
  prefix KV cache reuses the reference context across steps.

| Edit type                  | Support | Refs |
|----------------------------|---------|------|
| Instruction edit           | native  | 1    |
| Multi-reference compose    | native  | 2-10 |
| Identity / product ref     | native  | 1+   |
| Outfit transfer            | native  | 2    |
| Local edit by painted mark | native  | 1    |
| Sketch to photo            | native  | 1    |
| Background removal (RGBA)  | native  | 1    |

- References: 10 officially; the ComfyUI Text Encode Qwen Image 2.1 node has 16 slots (the
  templates wire 10); turbo LoRA up to 3. The canvas size sets the cost.
- Prompt: address slots by index as `<image1>`, `<image2>`, ...
- Output size: the canvas follows `image_1`. `resolution` 0 keeps its pixel size (rounded to 32),
  a value N scales its aspect ratio to N x N pixels. A custom size (Resolution Selector) must
  stay close to the resized `image_1`, or the edit shifts. Far above 2K adherence drops.
- Settings: base 25 steps, CFG 1, euler / simple; turbo 8 steps on its ManualSigmas schedule.
  Local edits work at 4-8 steps, whole-frame rewrites need ~25, hands ~30. CFG 2 follows dense
  prompts but oversharpens; CFG 5 degrades badly, 0.5 breaks the image.
- ComfyUI: Text Encode Qwen Image 2.1, the Image Edit subgraph (`resolution`, `custom_size`),
  Resolution Selector, Qwen Image 2.1 Cache (`int8` halves the cache). Forge Neo: toggle
  img2img / reference (edit) in Settings › Stable Diffusion.
- Region targeting: paint a red mark over the area in the Mask Editor and name it in the prompt.
- Typical failures: drift when the canvas differs from `image_1`, lost likeness when the prompt
  does not say what to keep. Start with "Keep ... in `<image1>` unchanged".

Example edit prompts:

- "make the sky sunset"
- "Keep the character and pose in `<image1>` unchanged, put this light blue denim shirt from
  `<image2>` on the character"
- "These three characters are sitting around a campfire in a forest"
- "change the jacket in the red area"
- "Create a photorealistic photograph of the motor yacht from the input sketch"
- "Remove the background, and output a PNG image"

## ControlNet and Structural Control

One Union ControlNet, recent but native in ComfyUI 0.37+.

- Model: [alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union](https://huggingface.co/alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union)
  (~7.5 GB, control branch only); ComfyUI conversions (bf16, int8 convrot) in
  [Kijai/QwenImage_experimental](https://huggingface.co/Kijai/QwenImage_experimental).
- Mechanism: VideoX-Fun Union side branch (16 control blocks on every 2nd DiT block).
- Conditions: canny, depth, grayscale, HED, lineart, MLSD, pose (DWPose), scribble, plus masked
  inpaint. No tile, normal or segmentation.
- ComfyUI: Load Model Patch (ModelPatchLoader) → Apply Qwen Image DiffSynth ControlNet
  (QwenImageDiffsynthControlnet: `strength`, optional `mask`, `start_percent`, `end_percent`),
  merged in PR #16519. No official template yet; workflows and a loader for older builds in
  [T8mars/Comfyui-Qwen-Image-2.1-Fun-Controlnet-Union-T8](https://github.com/T8mars/Comfyui-Qwen-Image-2.1-Fun-Controlnet-Union-T8).
- VideoX-Fun scripts: the config must be `config/qwenimage21/qwenimage21_control.yaml`, or the
  control weights are silently dropped.
- Strength: 1.0 for all published results; lower loosens, 0.0 disables.
- The control map must match the output canvas, sides multiples of 16.
- On a 3090, expect offloading: the branch adds ~7.5 GB on top of the DiT and the 8B encoder.
- The same weights edit, so a pose or depth map can also go in as a reference ("follow the pose
  in `<image1>`") without the ControlNet.
- Old Qwen-Image ControlNets (InstantX, DiffSynth, 2512 Fun) do not load. Forge Neo: not
  supported.
- License: Qwen Research License, non-commercial.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
