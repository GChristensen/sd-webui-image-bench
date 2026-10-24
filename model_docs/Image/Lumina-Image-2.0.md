# Lumina-Image-2.0 Reference

## Overview

- **Model:** Alpha-VLLM (Shanghai AI Lab), 2025-01; base of the Neta Lumina and NetaYume anime fine-tunes
- **Backbone:** Unified Next-DiT, single-stream, 2.6B; flow matching
- **Text:** Gemma-2-2B (LLM) tokens with a system prompt, in the joint sequence
- **Latent:** FLUX.1 VAE `ae`, 16 ch, 8x, 2x2 patches → multiples of 16
- **Strengths:** small and Apache-2.0, fits a 3090 without offload; long-caption adherence and short bilingual text

## Encoder/VAE

- Repos: HF [Alpha-VLLM/Lumina-Image-2.0](https://huggingface.co/Alpha-VLLM/Lumina-Image-2.0) · ComfyUI [Comfy-Org/Lumina_Image_2.0_Repackaged](https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged) · Accessory [Alpha-VLLM/Lumina-Accessory](https://huggingface.co/Alpha-VLLM/Lumina-Accessory) · Neta [neta-art/Neta-Lumina](https://huggingface.co/neta-art/Neta-Lumina) · NetaYume [duongve/NetaYume-Lumina-Image-2.0](https://huggingface.co/duongve/NetaYume-Lumina-Image-2.0)
- Text encoder: `gemma_2_2b_fp16.safetensors` → `models/text_encoders`, CLIPLoader type `lumina2`
- VAE: `ae.safetensors` (FLUX.1 16-channel VAE) → `models/vae`

## Recommended Defaults (Base)

```text
model:          lumina_2.safetensors (or bf16 DiT + gemma_2_2b_fp16 + ae)
steps:          36
cfg:            4.0  (true CFG; KSampler cfg = 4.0)
sampler:        res_multistep
scheduler:      simple [?]
shift:          6.0  (ModelSamplingAuraFlow)
resolution:     1024x1024 (~1 MP, any side a multiple of 16)
negative:       optional; empty works ("blurry, low quality, ugly" is a sane start)
system prompt:  CLIPTextEncodeLumina2 -> "superior" or "alignment"
extras:         RenormCFG node optional (defaults cfg_trunc 100, renorm_cfg 1.0)
```

## Recommended Defaults (Neta Lumina v1.0)

```text
model:          neta-lumina-v1.0-all-in-one.safetensors
steps:          30
cfg:            4.0-5.5  (true CFG)
sampler:        res_multistep  (alt: euler_ancestral)
scheduler:      linear_quadratic
shift:          [?]  (keep the value from the official Neta workflow)
resolution:     1024x1024 or ~1 MP portrait/landscape
negative:       recommended (anime quality negatives)
system prompt:  "You are an assistant designed to generate anime images based on textual prompts."
```

## Recommended Defaults (NetaYume Lumina)

```text
model:          NetaYume_Lumina_v2_all_in_one.safetensors (or newer)
steps:          40-50
cfg:            4-7  (true CFG)
sampler:        euler_ancestral + normal   OR   res_multistep + linear_quadratic
resolution:     ~1 MP
negative:       recommended
system prompt:  "You are an assistant designed to generate high-quality images based on user prompts and danbooru tags."
```

## Variants

| Variant              | What it is         | License        | Size        | Pick when        |
|----------------------|--------------------|----------------|-------------|------------------|
| Lumina-Image-2.0     | base model         | Apache-2.0     | 10.6 GB AIO | general, text    |
| Lumina-Accessory     | multi-task FT      | Apache-2.0 [?] | [?]         | infill, relight  |
| Neta Lumina v1.0     | anime fine-tune    | FAIPL-1.0 [?]  | [?]         | anime, NL+tags   |
| NetaYume Lumina      | anime fine-tune    | FAIPL-1.0 [?]  | [?]         | booru-tag anime  |

- No official turbo/lightning/distilled checkpoint exists; every variant uses true CFG with a negative pass.
- Commercial use: base weights are Apache-2.0 (commercial allowed). Gemma-2-2B carries Google's Gemma Terms of Use. Neta/NetaYume licenses restrict commercial use differently from the base [?] — read their cards before selling output or hosting.
- Lumina-Accessory is initialized from the base and adds a condition processor; it ships as `.pth` weights for its own repo/Gradio, not as a ComfyUI-native model.
- No official GGUF/fp8; community GGUF (Q2–Q8) exists but is unnecessary on 24 GB.

## Resolution

- Training: 256² low-res stage, then 1024² high-res and 1024² high-quality tuning. Native target ≈ 1 MP.
- No official bucket list; the model accepts arbitrary sizes. Sizes that behave well:

```text
1:1    1024x1024
4:5    896x1120
3:4    896x1152  (or 864x1152)
2:3    832x1248
9:16   768x1344
4:3    1152x896
3:2    1248x832
16:9   1344x768
```

- Required multiple: 16 (VAE ×8, patch 2). Trainers and some UIs snap to 32; use 32 to be safe.
- Practical range: ~768 px short side to ~1536 px long side (official demos cap at 1536).
- Off-spec: below ~0.6 MP detail turns mushy; above ~1.5 MP (e.g. 2048²) duplicated subjects and broken composition, typical of a 1024-trained DiT.

## Parameters

| Setting       | Base               | Neta Lumina      | NetaYume         |
|---------------|--------------------|------------------|------------------|
| steps         | 36 (20–50)         | 30               | 40–50            |
| CFG (true)    | 4.0                | 4–5.5            | 4–7              |
| sampler       | res_multistep      | res_multistep    | euler_ancestral  |
| scheduler     | simple [?]         | linear_quadratic | normal           |
| shift         | 6                  | [?]              | [?]              |

- Fewer steps: lower shift with steps. 36 steps → shift 6; 20 steps → shift 3. Low steps at shift 6 give artifacts.
- Diffusers reference values: guidance 4.0, 50 steps, `cfg_trunc_ratio` 0.25, `cfg_normalization` True, `max_sequence_length` 256, FlowMatch Euler with shift 6.
- RenormCFG (ComfyUI): `cfg_trunc` stops CFG after a timestep threshold (saves time, can reduce burn); `renorm_cfg` caps the guided update norm. Mapping to diffusers' 0.25 ratio is not 1:1 [?]; leave defaults unless you see burn.
- Silent garbage:
  - cfg ≤ 1 skips the negative pass → washed-out, prompt-weak images.
  - cfg ≥ ~7 on the base burns and oversaturates [?].
  - Shift left at the AuraFlow default 1.73 instead of 6 → noisy, unfinished structure [?].
  - A 4-channel VAE (SD/SDXL) instead of the FLUX 16-channel `ae` → error or noise.

## Prompting

- Natural language. Encoder is Gemma-2-2B (a decoder LLM), so long, descriptive captions work best; the model was trained on long, dense captions.
- Structure: `<system prompt> <Prompt Start> <prompt>`. CLIPTextEncodeLumina2 adds this for you:
  - "superior": "You are an assistant designed to generate superior images with the superior degree of image-text alignment based on textual prompts or user prompts."
  - "alignment": "You are an assistant designed to generate high-quality images with the highest degree of image-text alignment based on textual prompts."
  - Plain CLIPTextEncode works without it, with somewhat weaker alignment. The system prompt can also carry style ("You are an impressionist painter.").
- Prompt order that works: subject → appearance/action → setting → lighting → camera/medium → style.
- Token budget: 256 tokens in the official pipeline; longer text is truncated there. ComfyUI truncation behaviour [?] — keep prompts under ~200 words.
- `(word:1.2)` weighting: not reliable with the Gemma encoder [?]; rephrase or repeat instead.
- Negative prompts work (true CFG).
- Bilingual: English and Chinese prompts both work.
- Text rendering: short English/Chinese phrases in quotes are usually legible; long paragraphs garble.
- Fine-tunes: Neta/NetaYume take danbooru tags, NL, or both; quality tags matter there, not on the base.

Example (base, photo):

```text
A close-up photograph of an elderly fisherman mending a bright orange net on a wooden pier at dawn. Deep wrinkles, grey stubble, wool cap, hands calloused. Soft golden side light, mist over calm water behind him, shallow depth of field, 85mm lens, muted natural colours.
```

Example (base, typography):

```text
A vintage travel poster in flat screen-print style showing a red cable car climbing a green mountain above a blue lake. Large bold cream lettering at the top reads "ALPINE EXPRESS", smaller text at the bottom reads "Since 1924". Limited palette, paper grain texture.
```

## Generation Modes

| Mode               | Support                          |
|--------------------|----------------------------------|
| txt2img            | native                           |
| img2img            | native                           |
| inpaint            | community workflow (latent mask) |
| outpaint           | community workflow (latent mask) |
| instruct-edit      | not supported                    |
| reference/identity | not supported                    |
| infill, relighting | Lumina-Accessory (own repo) [?]  |
| depth/palette ctrl | Lumina-Accessory (own repo) [?]  |

- img2img: denoise 0.3–0.5 for refinement, 0.6–0.8 for restyle [?].
- Inpaint: SetLatentNoiseMask / InpaintModelConditioning with the base; denoise 0.7–1.0, feather the mask. No dedicated Lumina-2 inpaint checkpoint in ComfyUI.
- Lumina-Accessory: tasks run through its own inference code with task-specific system prompts (e.g. "...based on textual prompts and a partially masked image."); diffusers integration was proposed but not confirmed merged [?].

## Upscaling and High-Resolution Work

- Single pass degrades past ~1.5 MP; generate at ~1 MP and upscale.
- Hires pass: pixel upscale 1.5×, re-encode, second pass 15–20 steps, denoise 0.3–0.45, same cfg and shift [?].
- Tiled: Ultimate SD Upscale works with any ComfyUI model; tile 1024, overlap 64–128, denoise 0.25–0.35 [?]. No Lumina tile ControlNet.
- ESRGAN pairing: 4x-UltraSharp or 4x_NMKD-Siax for photo; anime fine-tunes pair with 4x-AnimeSharp.
- Tiled VAE decode (VAEDecodeTiled) helps above ~3 MP on 24 GB.

1. txt2img at ~1 MP (36 steps, shift 6, cfg 4).
2. ESRGAN ×2, then downscale to 1.5× original.
3. VAE encode → KSampler 18 steps, denoise 0.35.
4. Ultimate SD Upscale ×2 with tiles of 1024 if a larger final is needed.
5. VAEDecodeTiled for the final decode.

## Quirks and Failure Modes

- Wrong text encoder: Gemma-2-2B is required; a CLIP/T5 file or the wrong CLIPLoader type (not `lumina2`) fails or gives noise.
- Wrong VAE: only the FLUX 16-channel `ae.safetensors`.
- Shift too high for few steps: grainy, artefacted images; drop shift alongside steps.
- No system prompt: still works, but prompt adherence and polish drop a little.
- Too-short prompts give generic, flat compositions; the model expects long captions.
- Hands and complex poses: weaker than larger DiTs (FLUX, Qwen-Image); multi-person anatomy is a typical fail case.
- Anime: the base is mediocre at anime and character knowledge; use Neta/NetaYume.
- Off-bucket sizes much above 1.5 MP → duplicated subjects.
- Fine-tune settings do not transfer: NetaYume at 30 steps / base shift looks underbaked [?].
- VRAM: bf16 DiT + fp16 Gemma + VAE fit comfortably on a 3090 (~11–14 GB peak at 1024² [?]); no offload or quantization needed.
