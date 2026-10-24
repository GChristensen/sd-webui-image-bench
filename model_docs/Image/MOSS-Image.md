# MOSS-Image Reference

## Overview

- **Model:** OpenMOSS, 2026-10; trained from scratch on about 3.2B images, SFT fine-tuned from Base
- **Backbone:** single-stream DiT, 42 blocks, hidden size 3072, 5.1B; flow matching, shift 5
- **Text:** Qwen3.5-9B (LLM), frozen during training, prompts up to 4K tokens
- **Latent:** FLUX.2 VAE (small decoder), 32 ch, 8x, 2x2 patches → multiples of 16
- **Strengths:** text rendering and native bounding-box JSON layouts; 0.25-4 MP without buckets; Apache-2.0

## Encoder/VAE

- Repos: HF [OpenMOSS-Team/MOSS-Image-SFT](https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT) · [OpenMOSS-Team/MOSS-Image-Base](https://huggingface.co/OpenMOSS-Team/MOSS-Image-Base) · ComfyUI [Comfy-Org/MOSS-Image](https://huggingface.co/Comfy-Org/MOSS-Image)
- Text encoder (Qwen3.5-9B): `qwen3.5_9b_int8_convrot.safetensors` (9.75 GB, the sensible pick for 24 GB VRAM / 32 GB RAM) or `qwen3.5_9b_w4a8_gptq.safetensors` (7.3 GB). CLIPLoader type `moss_image`.
- VAE: `flux2-vae.safetensors` (336 MB), FLUX.2 latent space with the small decoder.

## Recommended Defaults (SFT)

```text
model:      moss_image_sft_bf16.safetensors (fits a 3090; int8_convrot if VRAM is tight)
steps:      25 (drafts) / 50 (finals)
cfg:        3.0 (true CFG, two forward passes per step; KSampler cfg = 3.0)
sampler:    euler
scheduler:  simple or sgm_uniform [?]
shift:      5 (applied by the model; no ModelSamplingSD3/AuraFlow node needed)
slg:        SkipLayerGuidanceDiTSimple, single_layers 22, start 0.0, end 1.0
resolution: 1024x1024 (1-2 MP, sides multiple of 16)
negative:   empty
extras:     moss_sft_destripe_top64_bf16 LoRA, strength 1.0 at 768 px / 1.5 at 1024 px
```

## Recommended Defaults (Base)

```text
model:      moss_image_base_bf16.safetensors
steps:      25 (drafts) / 50 (finals) or more
cfg:        3.0 (true CFG; raise toward 4-6 for short prompts)
sampler:    euler
scheduler:  simple or sgm_uniform [?]
shift:      5 (applied by the model)
slg:        SkipLayerGuidanceDiTSimple, single_layers 22, start 0.0, end 1.0
resolution: 832x1216 / 1024x1024 (1-2 MP)
negative:   nsfw, worst quality, bad anatomy, watermark, jpeg artifact
```

## Recommended Defaults (Base + 8-step DMD2 LoRA)

```text
model:      moss_image_base_bf16.safetensors (or Kromoss)
lora:       8-steps-dmd2-lora.safetensors, LoraLoaderModelOnly, strength 1.0
steps:      8 (4 also works)
cfg:        1.0 (KSampler cfg must be 1)
sampler:    euler
scheduler:  simple
shift:      5 (applied by the model)
slg:        none (remove SkipLayerGuidance; there is no negative branch)
resolution: 1024x1024
negative:   none (ignored at cfg 1)
```

## Variants

| Variant          | What it is               | License    | Size        | Pick when       |
|------------------|--------------------------|------------|-------------|-----------------|
| MOSS-Image-SFT   | curated-data fine-tune   | Apache-2.0 | 10.2 GB     | default         |
| MOSS-Image-Base  | raw pretrain, no distill | Apache-2.0 | 10.2 GB     | LoRA training   |
| *_int8_convrot   | W8A8 quant (Comfy-Org)   | Apache-2.0 | 5.4 GB      | VRAM ≤ 16 GB    |
| Kromoss          | community full fine-tune | Apache-2.0 | 10.2 GB [?] | SFT alternative |
| 8-step DMD2 LoRA | step-distilled LoRA      | Apache-2.0 | [?]         | speed           |
| GGUF (unsloth)   | community quant          | [?]        | [?]         | < 12 GB VRAM    |

- Architecture: 5.1B single-stream DiT, 42 blocks, hidden size 3072, trained from scratch on about 3.2B images with light quality filtering.
- Neither official checkpoint is distilled: both need ~50 steps and real CFG. Commercial use is allowed (Apache-2.0).
- Few-step: `8-steps-dmd-lora.safetensors` and `8-steps-dmd2-lora.safetensors` in [lodestones/Kromoss](https://huggingface.co/lodestones/Kromoss) are distilled from Base (rank 128, use one at a time, DMD2 recommended). They transfer to Kromoss; behaviour on SFT is untested [?]. Do not merge them into bf16 weights — the delta is near bf16 rounding.
- Kromoss is a drop-in replacement for `moss_image_sft_bf16.safetensors` in the Comfy-Org workflows.
- OpenMOSS says its own few-step (DMD) distillation is in progress.

## Resolution

- No fixed bucket list: trained for arbitrary aspect ratios. Recommended total area 1 MP, 1.5 MP or 2 MP.
- Supported range: 0.25 MP (512×512) to 4 MP (about 2048×2048). Both sides must be a multiple of 16 (the Python API raises an error otherwise).
- Example sizes (computed, multiples of 16; swap for portrait):

| Ratio | ~1 MP     | ~1.5 MP   | ~2 MP     |
|-------|-----------|-----------|-----------|
| 1:1   | 1024×1024 | 1216×1216 | 1408×1408 |
| 4:3   | 1152×864  | 1408×1056 | 1632×1216 |
| 3:2   | 1248×832  | 1504×1008 | 1728×1152 |
| 16:9  | 1344×768  | 1664×928  | 1920×1088 |
| 21:9  | 1536×640  | 1856×800  | 2176×928  |

- The official README sample renders at 1456×1456; testers have posted clean 4 MP typography posters from SFT at 50 steps, CFG 3.
- SFT colour striping gets stronger at higher width (stripe period ~16 px at 768 wide, ~21 px at 1024 wide).

## Parameters

| Setting   | SFT                       | Base                      | Base + DMD2 LoRA |
|-----------|---------------------------|---------------------------|------------------|
| Steps     | 50+                       | 50+                       | 8 (4 works)      |
| CFG       | 3, true CFG               | 3 (3–6), true CFG         | 1                |
| Sampler   | euler                     | euler                     | euler            |
| Scheduler | simple or sgm_uniform [?] | simple or sgm_uniform [?] | simple           |
| Shift     | 5, set by model           | 5, set by model           | 5, set by model  |
| SLG       | uncond skip, layer 22     | uncond skip, layer 22     | off              |
| Negative  | empty                     | official tag list         | ignored at CFG 1 |

- SLG: the official default is "two-pass" skip-layer guidance — the negative/uncond pass runs with layer 22 (0-indexed) skipped. Layers 24 and 26 also help. In ComfyUI this is `SkipLayerGuidanceDiTSimple` (single_layers 22, 0.0–1.0). A "standard SLG" variant (scale 3, 0.01–1.0) is also documented.
- Turning SLG off gives a more photographic look but fine detail tends to collapse. A compromise used in community workflows: `end_percent` 0.5 at 25 steps.
- CFG 3 is tuned for long prompts; short prompts need higher CFG (up to 6) or the prompt enhancer.
- Silent failures: CFG > 1 with the DMD LoRA burns the image; SLG left on with CFG 1 does nothing useful; a non-multiple-of-16 size errors in Diffusers and may be silently cropped in UIs [?].
- Forge Neo (via extension): sampler Euler, schedule type `MOSS`, 50 steps, CFG 3; the extension's `moss` UI preset sets these.

## Prompting

- Accepts natural language, booru-style tag sequences, or a JSON layout; natural language and JSON can be combined.
- English has the most training data; Chinese text and prompts are strong; Japanese (including vertical text) has been shown working with bbox layouts.
- Long prompts up to 4K tokens. Behaviour past that limit (truncation vs. error) is not documented [?].
- Tag order that works best: Quality → Score → Meta → Year → Character → Series → Artist → General.
- Text rendering: put the exact words in double quotes. The model inserts line breaks itself; to control them, put `\n` or real line breaks inside the quoted text. Short, well-spaced lines render more reliably than dense small type.
- Negative prompts work (true CFG). Official Base list: `nsfw, worst quality, bad anatomy, watermark, jpeg artifact`. Leave it empty on SFT.
- `(word:1.2)` weighting: no evidence it is honoured by the Qwen3.5 LLM encoder; rely on wording instead [?].
- Writing "No text." at the end of a scene prompt is used in practice to suppress stray lettering.
- The Comfy-Org SFT template has an optional prompt enhancer (`TextGenerate` running on the same Qwen3.5 encoder) that expands short prompts into dense captions and keeps quoted text; switch it off when feeding layout JSON.

Example (natural language, text rendering):

```text
A wide view of a small bakery storefront at dusk, warm light spilling from the window onto a wet cobblestone street. A hand-painted wooden sign above the door reads "MORNING CRUMB", and a chalkboard on the sidewalk says:
"Fresh sourdough
Open 6am – 2pm"
Photorealistic, 35mm lens, shallow depth of field, soft reflections on the pavement.
```

Example (tag sequence, in the recommended order):

```text
best quality, highres, 1girl, solo, silver hair, short hair, red scarf, winter coat, standing on a snowy railway platform, falling snow, steam from breath, looking at viewer, soft evening light
```

## Generation Modes

| Mode               | Support                      |
|--------------------|------------------------------|
| txt2img            | native                       |
| layout (bbox JSON) | native                       |
| img2img            | native (VAE encode)          |
| inpaint            | generic latent mask only [?] |
| outpaint           | generic pad + mask only [?]  |
| instruct-edit      | not supported                |
| reference/identity | not supported (LoRA only)    |

- img2img: around 0.6 denoise keeps the scene while following changed details (Forge Neo extension guidance).
- No dedicated inpaint checkpoint or adapter exists. OpenMOSS mentions reference-based generation via SFT as future work.

## Regional and Compositional Prompting

- Native method: the JSON layout prompt (officially "experimental"). Schema: `summary` (`meta`, `canvas`, `caption`) plus `items`, each with `label` (`text`, `character` or `object`), `caption`, `bbox`, and `text` for words to render.
- Coordinates: `bbox_format: "yxyx"` = `[y_min, x_min, y_max, x_max]`; `bbox_coord_space: "abs_centralized"` = pixels from the canvas centre (x right, y down). On 1024×1024 each axis runs −512…+512; subtract W/2 and H/2 from top-left coordinates.
- Layout dimensions must match the generation width/height exactly.
- ComfyUI: `Create Bounding Boxes` (draw boxes) → `MOSS-Image Layout Prompt` (merges boxes and global prompt into the JSON) → CLIP Text Encode. Forge Neo: paste the JSON into the prompt field via the extension.
- Structured editing: keep the seed, change one item's caption, text or box, and mostly that region changes [?].
- Works with true CFG; behaviour with the DMD LoRA at CFG 1 is untested [?].
- Keep text boxes slightly larger than the text so glyphs do not collide.

```text
{"summary": {"meta": ["poster"], "canvas": "single",
  "caption": "A flat vector travel poster on a warm beige background, a red lighthouse on a rocky coast, calm teal sea."},
 "items": [
  {"label": "text", "caption": "Bold dark-teal uppercase title, centered at the top.",
   "text": "NORTH COAST", "bbox": [-440, -400, -320, 400]},
  {"label": "object", "caption": "A red and white striped lighthouse on dark rocks.",
   "bbox": [-240, -180, 400, 180]},
  {"label": "text", "caption": "Small teal subtitle at the bottom.",
   "text": "Summer 2027", "bbox": [430, -160, 490, 160]}],
 "bbox_coord_space": "abs_centralized", "bbox_format": "yxyx"}
```

## Upscaling and High-Resolution Work

- The model extrapolates natively to 4 MP, so for up to ~2048 px the best route is generating directly at the target size rather than hires-fixing.
- At 3–4 MP use `VAE Decode (Tiled)` to keep decode VRAM in check.
- No model-specific hires-fix or tile-ControlNet guidance exists; beyond 4 MP use a generic ESRGAN-family upscale, optionally followed by a low-denoise img2img pass [?].

1. Compose at 1–1.5 MP (fast iteration; fix seed and layout).
2. Re-render the final at 2–4 MP with the same prompt (composition shifts, so re-check layout boxes scaled to the new size).
3. Decode with tiled VAE.
4. Only if more than 4 MP is needed: ESRGAN upscale, then optional light img2img [?].

## Quirks and Failure Modes

- SFT paints faint vertical colour stripes in smooth areas (sky, walls, backdrops). Fix: `moss_sft_destripe_top64_bf16.safetensors` from [nynxz/MOSS-Image](https://huggingface.co/nynxz/MOSS-Image), strength 1.0 at 768 px, 1.5 at 1024 px; SFT only, not Base.
- Base anime output is rated weak by several testers out of the box; character/style LoRAs improve it a lot. Photoreal is decent but not class-leading.
- Pose instructions are sometimes ignored (e.g. "looking back" rendered as front-facing).
- Light data filtering means watermarks, blur and JPEG artefacts can leak in; keep them in the negative on Base.
- Speed: ~50 s per 832×1216 image at 50 steps on an RTX 4070 with int8 weights; peak VRAM ~11.6 GB in that setup.
- ComfyUI must be recent enough to include native support (merged 16 Oct 2026, PR #17095, initially master only after 0.41.x). An older install fails to load the model.
- Wrong CLIPLoader type (anything other than `moss_image`) breaks conditioning.
- `Load LoRA (Bypass)` silently drops q/k/v adapters on the fused Comfy-Org checkpoints; use the normal LoRA loader, or the split-qkv checkpoints from nynxz/MOSS-Image. Watch the console for `lora key not loaded`.
- `Create Bounding Boxes`: wiring width/height from another node offsets the boxes; type the numbers in by hand.
- Layout boxes in top-left coordinates or `xyxy` order land in the wrong place with no error.
- The official Diffusers pipeline runs the VAE and initial noise in fp32; forcing the VAE to bf16/fp16 may cost quality [?].
- When training LoRAs, keep the text encoder frozen (official advice).

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*