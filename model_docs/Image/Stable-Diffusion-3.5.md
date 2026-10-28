# Stable Diffusion 3.5 Reference

## Overview

- **Model:** Stability AI; Large and Large Turbo 2024-10, Medium 2024-10. Successor to SD3 Medium (2024-06); shares the SD3 VAE and text encoders. SD3/SD3.5 LoRAs and ControlNets are size-specific: Large assets do not load on Medium and vice versa.
- **Backbone:** MMDiT (dual-stream: separate image and text weights, joint attention). Large and Turbo 8.1B; Medium 2.5B "MMDiT-X" (extra self-attention in the first ~13 blocks). QK-normalization. Rectified flow.
- **Text:** three frozen encoders: CLIP-L + OpenCLIP bigG (pooled vectors drive adaLN modulation; hidden states join the token stream) and T5-XXL (hidden states in the joint-attention sequence).
- **Latent:** 16-channel VAE, 8x spatial compression, patch size 2, so dimensions must be multiples of 16.
- **Positions:** learned 2D absolute embeddings cropped from a larger grid; this is why sizes far outside the trained range break, unlike RoPE models.
- **Strengths:** short typography, prompt adherence for multi-object scenes, very wide style range (painterly, illustration, film looks) without LoRAs; open to fine-tuning.

## Encoder/VAE

- Repos: HF [stabilityai/stable-diffusion-3.5-large](https://huggingface.co/stabilityai/stable-diffusion-3.5-large), [stabilityai/stable-diffusion-3.5-large-turbo](https://huggingface.co/stabilityai/stable-diffusion-3.5-large-turbo), [stabilityai/stable-diffusion-3.5-medium](https://huggingface.co/stabilityai/stable-diffusion-3.5-medium) · ComfyUI [Comfy-Org/stable-diffusion-3.5-fp8](https://huggingface.co/Comfy-Org/stable-diffusion-3.5-fp8)
- Text encoders (`models/text_encoders/`): `clip_l.safetensors`, `clip_g.safetensors`, plus one of `t5xxl_fp16.safetensors`, `t5xxl_fp8_e4m3fn.safetensors`, `t5xxl_fp8_e4m3fn_scaled.safetensors`. Load with `TripleCLIPLoader` (or `CLIPLoader` / `DualCLIPLoader` type `sd3`).
- VAE: built into the official checkpoints; the standalone copy is `vae/diffusion_pytorch_model.safetensors` in the HF repo (rename e.g. `sd3_vae.safetensors`).

## Recommended Defaults (Large)

```text
steps:            28-40
cfg:              3.5-4.5 (true CFG, KSampler cfg = this value)
sampler:          euler (dpmpp_2m also fine)
scheduler:        sgm_uniform (or simple)
shift:            3.0 (ModelSamplingSD3)
resolution:       1024x1024, ~1 MP
negative prompt:  empty or short ("blurry, lowres, watermark")
extras:           none
```

## Recommended Defaults (Large Turbo)

```text
steps:            4 (up to 8)
cfg:              1.0 in KSampler (diffusers guidance_scale 0, no CFG)
sampler:          euler
scheduler:        sgm_uniform (or simple)
shift:            3.0
resolution:       1024x1024, ~1 MP
negative prompt:  ignored at cfg 1.0
extras:           none
```

## Recommended Defaults (Medium)

```text
steps:            40
cfg:              4.5 (true CFG)
sampler:          euler
scheduler:        sgm_uniform
shift:            3.0
resolution:       1024x1024 to 1440x1440, 0.25-2 MP
negative prompt:  empty or short
extras:           SkipLayerGuidanceSD3, layers 7,8,9, scale ~3.0 [?],
                  start 0.01 [?], end 0.15 [?]
```

Skip Layer Guidance is recommended by Stability for Medium to fix structure and anatomy; it costs an extra model pass per step during its active range.

## Variants

| Variant           | What it is           | License   | Size         | Pick when          |
|-------------------|----------------------|-----------|--------------|--------------------|
| Large             | base, 8.1B MMDiT     | Community | ~16.5 GB [?] | best quality       |
| Large Turbo       | ADD step-distilled   | Community | ~16.5 GB [?] | speed, drafts      |
| Medium            | MMDiT-X, 2.5B        | Community | ~5.1 GB [?]  | fast, up to 2 MP   |
| Large fp8_scaled  | fp8 quant, TEs incl  | Community | ~14.9 GB [?] | 32 GB system RAM   |
| Medium + encoders | AIO, T5 fp8 scaled   | Community | ~11 GB [?]   | one-file setup     |

- License: Stability AI Community License. Free for research, non-commercial and commercial use under USD 1M annual revenue; above that an Enterprise license is required. Applies to derivatives and the ControlNets too.
- Large Turbo is Adversarial Diffusion Distillation of Large: no CFG, no negatives, lower diversity, slightly crisper/higher-contrast. No LoRA is needed to run it; Large LoRAs usually load on Turbo with reduced fidelity [?].
- RTX 3090 + 32 GB RAM: Large fp16 (~16.5 GB) + T5 fp16 (~9.8 GB) + CLIPs exceeds VRAM; ComfyUI offloads the text encoders, but system RAM gets tight. Use `t5xxl_fp8_e4m3fn_scaled` or the fp8_scaled all-in-one checkpoint.
- Not supported in Forge Neo: SD3 support was removed from the Neo branch. Use ComfyUI (or original Forge / reForge builds that still carry SD3 [?]).

## Resolution

- Native: ~1 MP (1024x1024) for Large and Turbo; Medium trained progressively up to 1440 px with mixed-scale stages, usable 0.25-2 MP.
- Required multiple: 16 (8x VAE x patch 2); multiples of 64 are the safe habit.
- Stability did not publish an official bucket list; these ~1 MP sizes are widely used and behave well:

```text
1:1    1024x1024
4:3    1152x896  /  896x1152
3:2    1216x832  /  832x1216
16:9   1344x768  /  768x1344
21:9   1536x640  /  640x1536
```

- Practical range: Large ~512 px min side to ~1.5 MP before quality drops [?]; Medium up to ~1440x1440.
- Off-spec: above range gives duplicated subjects and repeated objects; below ~0.25 MP gives mush; extreme ratios beyond ~2.4:1 collapse composition and repeat borders.

## Parameters

| Setting         | Large        | Large Turbo  | Medium        |
|-----------------|--------------|--------------|---------------|
| steps           | 28-40        | 4            | 40            |
| CFG             | 3.5-4.5      | 1.0          | 4.5           |
| sampler         | euler        | euler        | euler         |
| scheduler       | sgm_uniform  | sgm_uniform  | sgm_uniform   |
| shift           | 3.0          | 3.0          | 3.0           |
| negative prompt | works        | ignored      | works         |
| clip skip       | n/a          | n/a          | n/a           |

- CFG above ~6 on Large/Medium burns: oversaturated, plastic skin, crushed shadows. Below ~2.5 prompt adherence drops and images go flat.
- Turbo with CFG > 1 doubles the cost and fries the image quickly; with cfg 1.0 any negative prompt does nothing.
- Shift: higher (4-6) helps composition at >1.5 MP; very low (<1.5) gives noisy, under-resolved results [?].
- Ancestral and SDE samplers work but add grain; Karras/exponential schedulers designed for epsilon models do not suit rectified flow and give soft or broken results.
- ComfyUI's official SD3 workflows zero out the negative conditioning for the first ~10% of steps (`ConditioningZeroOut` + `ConditioningSetTimestepRange`); omitting it is fine for SD3.5.

## Prompting

- Natural language, full sentences; booru tags work only loosely. Put subject first, then composition, then style, lighting and camera/medium.
- Token budget: CLIP-L/G 77 tokens each; T5 trained at 256 tokens. Longer T5 prompts (up to 512) are accepted but can cause edge artifacts, especially on Medium. Keep prompts under ~200 words.
- Encoders can be fed separately in ComfyUI (`CLIPTextEncodeSD3`): short tag-style text to CLIP, full description to T5.
- `(word:1.2)` weighting is applied by ComfyUI but the effect is weak and inconsistent through T5; rephrase or repeat instead of weighting.
- Negative prompts work on Large and Medium (true CFG) but matter less than on SDXL; keep them short.
- No quality tokens or trigger words; "masterpiece, best quality" has little effect. Medium/style words ("35mm film photo", "gouache illustration") matter a lot.
- Text rendering: good for short phrases in quotes ("a sign that reads "OPEN""); long sentences garble; Large is clearly better than Medium.
- Often ignored: exact counts above ~4, left/right placement of many objects, negation inside the positive prompt ("no hat").

```text
"A weathered fisherman in a yellow raincoat mends a net on a wooden pier at dawn,
low fog over the harbor, soft backlight, shallow depth of field, 35mm film photo,
muted teal and amber palette."
```

```text
"Flat vector poster of a red fox sitting on a crescent moon, starry navy sky,
bold geometric shapes, grain texture, the words "NIGHT OWL CAFE" in white
condensed sans-serif lettering at the bottom."
```

## Generation Modes

| Mode               | Support                            |
|--------------------|------------------------------------|
| txt2img            | native                             |
| img2img            | native                             |
| inpaint            | native masked sampling             |
| outpaint           | pad + inpaint workflow             |
| instruct-edit      | not supported                      |
| reference/identity | extra weights (IP-Adapter, Large)  |

- img2img denoise: 0.3-0.5 for refinement, 0.6-0.8 for restyle.
- Inpaint: no official inpaint checkpoint. Use `SetLatentNoiseMask` or `InpaintModelConditioning` with denoise 0.7-1.0; grow and feather the mask 16-32 px.
- Inpaint ControlNet [alimama-creative/SD3-Controlnet-Inpainting](https://huggingface.co/alimama-creative/SD3-Controlnet-Inpainting) targets SD3 Medium (2B); compatibility with SD3.5 Medium is [?].
- Reference: [InstantX/SD3.5-Large-IP-Adapter](https://huggingface.co/InstantX/SD3.5-Large-IP-Adapter) (SigLIP image encoder), loaded through a custom node pack [?]; Large only.

## ControlNet and Structural Control

Thin but official for Large; almost nothing official for Medium.

- Mechanism: classic per-type ControlNets (no Union model from Stability).
- [stabilityai/stable-diffusion-3.5-large-controlnet-canny](https://huggingface.co/stabilityai/stable-diffusion-3.5-large-controlnet-canny): Stability, good. Start at strength 0.8. Preprocess Canny 100/200.
- [stabilityai/stable-diffusion-3.5-large-controlnet-depth](https://huggingface.co/stabilityai/stable-diffusion-3.5-large-controlnet-depth): Stability, good; trained on DepthFM maps, Depth Anything maps also work [?]. Strength ~0.7-0.8 [?].
- [stabilityai/stable-diffusion-3.5-large-controlnet-blur](https://huggingface.co/stabilityai/stable-diffusion-3.5-large-controlnet-blur): Stability; tile-style, for upscaling. Input is a Gaussian-blurred image; tile at 128-512 px.
- All three are compatible only with SD3.5 Large (8B). Use on Turbo works in practice at lower strength [?].
- ComfyUI: `ControlNetLoader` + `ControlNetApplyAdvanced` (Apply ControlNet with the `vae` input connected, which SD3 ControlNets require). Files go in `models/controlnet/` (e.g. `sd3.5_large_controlnet_canny.safetensors`). Not in Forge Neo.
- Over-conditioning: canny gives halos and hard outlines; depth flattens lighting and texture. Fix by lowering strength or ending at 0.6-0.8.
- Each ControlNet is ~8 GB at fp16 [?], so stacking two with Large fp16 on 24 GB needs fp8 weights or offloading.
- InstantX SD3 ControlNets (canny, pose, tile) were built for SD3 Medium and do not load on Large; on SD3.5 Medium results are unreliable [?].
- Bottom line: canny/depth/blur on Large is the only well-supported path.

## Regional and Compositional Prompting

- ComfyUI core `ConditioningSetArea` / `ConditioningSetMask` + `ConditioningCombine` work with SD3 conditioning, since they are model-agnostic [?].
- They rely on true CFG; on Turbo (cfg 1.0) regional separation is weak.
- Attributes bleed beyond about 2-3 subjects; T5 joint attention mixes regions more than SDXL cross-attention.
- More reliable: generate the full scene, then inpaint each subject separately, or composite then img2img at denoise 0.4-0.5.

## Upscaling and High-Resolution Work

- Single pass past ~1.5 MP on Large produces duplication; Medium holds to ~2 MP.
- Hires fix: pixel upscale 1.5-2x with an ESRGAN model, then a second pass at denoise 0.3-0.45, 15-20 steps, same CFG. Latent upscale is not recommended (16-ch latents smear).
- Tiled: Ultimate SD Upscale or ComfyUI-TiledDiffusion with the Blur ControlNet; tile 1024 px with 64-128 px overlap; tiled VAE decode above ~3 MP.
- Upscalers: 4x-UltraSharp, 4x_NMKD-Siax_200k, RealESRGAN_x4plus [?] for photos.
- Medium is a good, cheap refiner for Large output; Stability ships an official Large + Medium upscaling workflow.

1. Generate with Large at ~1 MP, 28-40 steps, CFG 4.
2. Upscale 2x in pixel space with a 4x ESRGAN model downscaled to 2x.
3. Refine with Medium (or Large) at denoise 0.35, 20 steps, CFG 4, tiled VAE decode.
4. For 4K+: Ultimate SD Upscale with the Blur ControlNet, strength ~0.6 [?], denoise 0.3, 1024 px tiles.

## Quirks and Failure Modes

- Hands and limbs: better than SD3 Medium but still worse than Flux-class models; Medium is noticeably weaker, especially at poses like lying down. SLG on Medium helps.
- Black or noise images: missing or mismatched T5, SDXL VAE selected, or wrong checkpoint loader (no encoders in the official file).
- Muddy, low-detail output: Karras scheduler, too few steps on Large/Medium, or CFG on Turbo.
- Oversaturation and plastic skin above CFG ~5.
- Edge artifacts or noise bands: T5 prompts over 256 tokens.
- Large LoRAs on Medium (and vice versa) fail to load or have no effect; the architectures differ.
- Sizes not divisible by 16 crash or get cropped; off-bucket extremes repeat subjects.
- Aesthetic biases: "AI-look" glossy portraits on photo prompts unless the film/camera style is spelled out; less photorealism than Flux by default.
- Forge Neo will not load SD3.5 at all: an "unknown model" error there is not a corrupt file.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
