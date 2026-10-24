# Pixel Diffusion Decoder (NVIDIA PiD) Reference

## Overview

- **Model:** NVIDIA research, 2026-05 (v1.5 2026-07); not a generator but a replacement for the VAE decoder of other models
- **Backbone:** pixel-space DiT of the PixelDiT line [?], about 1.3B [?]; DMD2-distilled to 4 steps
- **Text:** Gemma-2-2B caption steers synthesized fine detail; the stage-1 latent (one checkpoint per latent space) sets content, layout and color
- **Latent:** none of its own: denoises RGB pixels directly at 4x the stage-1 image size
- **Strengths:** decode and 4x upscale in one pass (1 MP latent → 16 MP), reused by every model sharing a latent space

## Encoder/VAE

- Repos: HF [nvidia/PiD](https://huggingface.co/nvidia/PiD) · ComfyUI [Comfy-Org/PixelDiT](https://huggingface.co/Comfy-Org/PixelDiT) · prior/T2I base HF [nvidia/PixelDiT-1300M-1024px](https://huggingface.co/nvidia/PixelDiT-1300M-1024px)
- Text encoder (one for every PiD checkpoint): `gemma_2_2b_it_elm_bf16.safetensors` or `gemma_2_2b_it_elm_fp8_scaled.safetensors`, CLIPLoader type `pixeldit`.
- VAE: none for PiD itself. Load VAE → `pixel_space` (built-in option, not a file). Some community workflows ship an 84-byte marker `pixel_space_vae.safetensors` for `models/vae/` when the option is missing.
- Upstream VAE (only to VAE-encode an existing image, or for a baseline decode): the VAE of the latent family you feed in (`ae.safetensors` for Flux.1/Z-Image, Flux.2 VAE, `qwen_image_vae.safetensors`, SDXL VAE, SD3 VAE).
- Diffusion model files, all in `models/diffusion_models/` (pick by latent space, not by generator name):
  - Flux.1 16-ch: `pid_1.5_flux1_1024_to_4096_4step_bf16.safetensors`, `pid_flux1_512_to_2048_4step_bf16.safetensors`
  - Flux.2 128-ch: `pid_1.5_flux2_1024_to_4096_4step_bf16.safetensors`, `pid_flux2_1024_to_4096_4step_2606_bf16.safetensors`, `pid_flux2_512_to_2048_4step_bf16.safetensors`
  - Qwen-Image / Wan 2.1 16-ch: `pid_1.5_qwenimage_1024_to_4096_4step_bf16.safetensors`
  - SDXL 4-ch: `pid_sdxl_1024_to_4096_4step_bf16.safetensors`
  - SD3 16-ch: `pid_sd3_1024_to_4096_4step_bf16.safetensors`, `pid_sd3_512_to_2048_4step_bf16.safetensors`
  - Each v1.5 file also exists as `_int8_convrot`; most v1 files as `_mxfp8`.
- Reuse: the flux1 decoder serves Flux.1 dev/schnell, Z-Image, Z-Image-Turbo, Chroma; the flux2 decoder serves FLUX.2-dev and FLUX.2-klein 4B/9B; the qwenimage decoder serves Qwen-Image, Qwen-Image-2512, Qwen-Image-Edit, Krea 2, Wan 2.1/2.2 latents and Anima [?]. Same Gemma encoder for all.

## Recommended Defaults (PiD v1.5, 4-step, 1024→4096)

```text
checkpoint:     pid_1.5_<family>_1024_to_4096_4step_bf16.safetensors
text encoder:   gemma_2_2b_it_elm_fp8_scaled (CLIPLoader type: pixeldit)
conditioning:   CLIPTextEncode -> PiDConditioning (latent = stage-1 latent)
latent_format:  flux (Flux.1, Flux.2 auto-detected by 128 ch, Z-Image) | sd3 | qwenimage/sdxl [?]
degrade_sigma:  0.0 (clean latent) | 0.1-0.8 (early-exit latent)
negative:       ConditioningZeroOut of the positive
empty latent:   EmptyChromaRadianceLatentImage at exactly 4x the stage-1 size
steps:          4
cfg:            1.0 (distilled; no CFG, negative ignored)
sampler:        lcm
scheduler:      simple
shift:          checkpoint default (no ModelSampling node) [?]
denoise:        1.0
vae decode:     VAE Decode with Load VAE = pixel_space
input size:     ~1 MP stage-1 latent (1024x1024, 1024x768, 1344x768)
output size:    4096x4096, 4096x3072, 5376x3072
```

Recipe: stage-1 model → KSampler → its LATENT goes into PiDConditioning (not into VAE Decode) → second KSampler with the PiD model on an empty 4x pixel-space latent → VAE Decode (pixel_space).

## Recommended Defaults (PiD v1 "2k", 4-step, 512→2048)

```text
checkpoint:     pid_flux1_512_to_2048_4step_bf16 | pid_flux2_... | pid_sd3_...
steps:          4
cfg:            1.0 (distilled)
sampler:        lcm
scheduler:      simple
degrade_sigma:  0.0
negative:       ConditioningZeroOut
input size:     512x512 latent (see 2k buckets)
output size:    2048x2048
```

Sharper than the 2kto4k / v1.5 decoders at exactly 2048 px; no Qwen or SDXL version exists.

## Variants

| Variant                | What it is         | License | Size    | Pick when            |
|------------------------|--------------------|---------|---------|----------------------|
| v1.5 1024→4096 4step   | 4-step distilled   | NSCLv1  | 2.6 GB  | default, 4K output   |
| v1.5 4step int8        | int8_convrot quant | NSCLv1  | [?]     | VRAM/speed           |
| v1.5 1024→4096 (no 4s) | undistilled [?]    | NSCLv1  | [?]     | research only        |
| v1 512→2048 4step      | 4-step distilled   | NSCLv1  | [?]     | 2K output            |
| v1 1024→4096 4step     | 4-step distilled   | NSCLv1  | [?]     | SD3, SDXL            |
| v1 flux2 _2606         | color-fixed v1     | NSCLv1  | 2.7 GB  | v1 Flux.2 only       |
| v1 mxfp8               | mxfp8 quant        | NSCLv1  | [?]     | Blackwell [?]        |
| PixelDiT 1300M 1024px  | pixel-space T2I    | NSCLv1  | [?]     | standalone T2I       |

- All decoders are DMD2-distilled to 4 steps; distillation means fixed 4-step lcm/simple at cfg 1.0. No LoRAs exist or are needed.
- v1.5 exists for flux1, flux2 and qwenimage only; it fixes color drift and corner grid artifacts and was trained on more anime and small-face data. SD3 and SDXL stay on v1.
- The original un-suffixed v1 flux2 1024→4096 checkpoint has a known color drift; use `_2606` or v1.5.
- Commercial use is not allowed: NSCLv1, non-commercial research/evaluation only, derivatives included. The code repo is Apache 2.0, the weights are not.
- PixelDiT 1300M is the related pixel-space T2I model (community defaults: 30 steps, cfg 4.0 [?]); it is not needed to run PiD.

## Resolution

- Output is always exactly 4x the input latent's pixel size. Set the empty latent to 4x the stage-1 width and height.
- v1 "2k" decoders: trained at 2048 px. Buckets:

| Ratio | Input (stage-1) | Output     |
|-------|-----------------|------------|
| 1:1   | 512x512         | 2048x2048  |
| 4:3   | 576x432         | 2304x1728  |
| 3:4   | 432x576         | 1728x2304  |
| 16:9  | 672x384         | 2688x1536  |
| 9:16  | 384x672         | 1536x2688  |

- 2kto4k and v1.5 decoders: trained on 2048-4096 multi-resolution buckets; designed for ~1 MP input → 4K:

| Ratio  | Input (stage-1) | Output     |
|--------|-----------------|------------|
| 1:1    | 1024x1024       | 4096x4096  |
| 4:3    | 1024x768        | 4096x3072  |
| 16:9   | 1344x768        | 5376x3072  |
| 3:2    | 1008x672 [?]    | 4032x2688  |
| 21:9   | 1008x432 [?]    | 4032x1728  |

- Required multiple: 16 px on the stage-1 image (images are center-cropped to multiples of 16 before encoding).
- Practical max single-shot: ~4096 px long edge, ~17 MP output. Beyond that, use latent tiling.
- Off-spec failures: input latent larger than the envelope → blurry, under-denoised output, midtone color collapse (whites turn pink/magenta, chroma noise). Off-bucket aspect ratios on v1 → green band at the bottom or in corners. Mismatched 512 vs 1024 decoder → soft or odd results.

## Parameters

| Setting       | v1.5 4-step         | v1 4-step           | v1.5 undistilled |
|---------------|---------------------|---------------------|------------------|
| steps         | 4                   | 4                   | [?]              |
| cfg           | 1.0                 | 1.0                 | [?]              |
| sampler       | lcm                 | lcm                 | [?]              |
| scheduler     | simple              | simple              | [?]              |
| shift         | default [?]         | default [?]         | [?]              |
| negative      | ConditioningZeroOut | ConditioningZeroOut | [?]              |
| denoise       | 1.0                 | 1.0                 | 1.0              |
| degrade_sigma | 0.0                 | 0.0                 | 0.0              |

- Distilled sigma schedule used by the tiled node: `0.999, 0.866, 0.634, 0.342, 0`. Other sampler/scheduler combos are not expected to work on the distilled students.
- Forge Neo PiD defaults: 4 steps, shift 3.5, LCM, Simple.
- Silent-garbage parameters:
  - cfg above 1.0: double-applies the distilled guidance (oversharpened, burnt).
  - Decoding the PiD output with a real VAE instead of `pixel_space`: channel size-mismatch error.
  - Wrong family checkpoint (flux2 on a 16-ch latent, flux1 on a 128-ch latent): `weight [512, 128, ...]` vs `[1, 16, ...]` mismatch.
  - Flux.1 and Qwen/Wan latents are both 16-ch: a wrong flux1/qwenimage pairing runs without error but gives wrong colors.
  - Empty latent not exactly 4x the stage-1 size: distortion or soft output.
  - degrade_sigma above 0 on a clean latent: PiD reinterprets detail and drifts from the source.
- Early exit: decoding a partially denoised latent works and saves stage-1 steps. Official recommended capture points:

| Stage-1 model    | Steps | Capture at |
|------------------|-------|------------|
| Flux.1 / SD3     | 28    | step 24    |
| SDXL             | 30    | step 26    |
| FLUX.2-dev       | 50    | step 46    |
| Qwen-Image       | 50    | step 44    |
| Z-Image          | 50    | step 46    |
| Z-Image-Turbo    | 9     | final x0   |
| FLUX.2-klein     | 4     | final x0   |

- In ComfyUI, do early exit with KSamplerAdvanced (`end_at_step`, `return_with_leftover_noise` enabled) and set degrade_sigma to the remaining noise level [?].

## Prompting

- The caption goes through Gemma-2-2B (CLIPTextEncode on the `pixeldit` CLIP) into PiDConditioning. Natural language, like the stage-1 prompt.
- An empty prompt works; reusing the stage-1 prompt is the common default (Forge Neo does this when the PiD prompt is empty).
- The prompt steers synthesized fine detail (fur, skin, fabric, foliage), not composition; layout, colors and content come from the latent.
- Negative prompt: does nothing (cfg 1.0, negative is ConditioningZeroOut).
- Weighting `(word:1.2)` and quality tokens: no documented effect [?].
- Text: lettering present in the latent is preserved and sharpened; PiD does not add new text.
- Example prompts:

```text
"A photorealistic half-body portrait of a brown tabby cat on a rustic wooden table, soft morning window light, fine fur detail, sharp amber-green eyes, shallow depth of field"
```

```text
"Close-up of weathered stone wall with moss and lichen, overcast daylight, crisp natural texture, high detail"
```

## Generation Modes

| Mode                       | Support                         |
|----------------------------|---------------------------------|
| txt2img (decode stage)     | native, after any matching LDM  |
| early-exit decode          | native (degrade_sigma)          |
| upscale existing image     | native (VAE encode → PiD)       |
| tiled upscale (>16 MP)     | community nodes                 |
| img2img                    | not supported                   |
| inpaint                    | not supported                   |
| outpaint                   | not supported                   |
| instruct-edit              | not supported                   |
| reference/identity         | not supported                   |

- Upscaling an existing image: VAE Encode with the family VAE → PiDConditioning → PiD. Works best on clean generated images; JPEG artifacts, sensor noise and real-photo degradation are not in its training data.
- Edit-model output (Qwen-Image-Edit, Klein edit) can be decoded like any other latent of that family.

## Upscaling and High-Resolution Work

- Single-shot limit: ~1 MP latent → ~16-17 MP output. A ~2 MP latent through one pass collapses into pink midtones and chroma noise.
- PiD replaces both the VAE decode and the hires pass. Do not run a classic hires-fix before it; generate stage-1 at the model's native ~1 MP.
- Latent tiling: [BennyDaBall930/ComfyUI-Latent-Tiled-PiD](https://github.com/BennyDaBall930/ComfyUI-Latent-Tiled-PiD) (node "Latent-Tiled PiD Decode") crops the generation latent into ≤1024 px tiles with 64 px overlap (256 px in output) and feather-blends. Tile count follows the latent size:

| Stage-1 latent | Tiles | Output      | MP    |
|----------------|-------|-------------|-------|
| 1024x1024      | 1     | 4096x4096   | 16.8  |
| 1920x1088      | 4     | 7680x4352   | 33.4  |
| 2560x1440      | 6     | 10240x5760  | 59.0  |
| 3456x1944      | 8     | 13824x7776  | 107.5 |

- Keep `max_tile` 1024; lower it only for VRAM headroom (output size does not change).
- Image-space tiling (cut pixels → VAE-encode tiles → PiD) exists in [Merserk/ComfyUI-PiD](https://github.com/Merserk/ComfyUI-PiD) ("PiD Upscale"); it is lossier than latent tiling.
- Forge Neo: built-in "PiD Integrated" extension supports PiD 1.5 for sdxl/qwen/flux1/flux2; [aoleg/Neo-PiD](https://github.com/aoleg/Neo-PiD) adds output scale (4x/2x/1.5x/1.25x/1x), histogram color correction and step/shift controls. Checkpoint goes in `models/Stable-diffusion`. Hires fix and inpaint are refused.
- Downscaling the 4x output to 1x-2x (Lanczos) gives a cleaner, more detailed image than a plain VAE decode at the same size.
- ESRGAN-type upscalers are not needed; PiD is the upscaler. It is not a refiner for other models' pixels.
- Speed reference: about 1 MP of output per second on an RTX 5090 when tiled; a 3090 is slower [?]. Expect roughly 2.6 GB (bf16 decoder) + 2.5-5 GB (Gemma) plus activations; 4096x4096 single-shot fits in 24 GB [?].

Pipeline (RTX 3090, Z-Image-Turbo example):

1. Stage-1: Z-Image-Turbo at 1024x1024, 9 steps, cfg 1.0, res_multistep or euler, simple.
2. Do not VAE-decode; take the LATENT output.
3. Load `pid_1.5_flux1_1024_to_4096_4step_bf16` (UNETLoader) and Gemma (`pixeldit`).
4. CLIPTextEncode (same prompt or empty) → PiDConditioning (latent_format `flux`, degrade_sigma 0.0); ConditioningZeroOut → negative.
5. EmptyChromaRadianceLatentImage 4096x4096 → KSampler: 4 steps, cfg 1.0, lcm, simple, denoise 1.0.
6. VAE Decode with `pixel_space` → 4096x4096 PNG.
7. For more than 16 MP: stage-1 at 1920x1088 and replace steps 5-6 with Latent-Tiled PiD Decode → 7680x4352.

## Quirks and Failure Modes

- Checkpoints match the latent space, not the model name. Z-Image uses the flux1 decoder; Krea 2 and Wan use qwenimage; Klein uses flux2.
- Size-mismatch errors (16 vs 128 channels) mean either the wrong family decoder or a real VAE in the final VAE Decode instead of `pixel_space`.
- Older workflows used `latent_format` values `flux1`/`flux2`; current core uses `flux` (Flux.2 auto-detected) and `sd3`. Old JSONs may load with bad widget values.
- v1 flux2: whitish, washed-out or color-shifted output. Use `_2606` or v1.5.
- v1 off-1:1 aspect ratios: green band at the bottom edge or grid artifacts in corners; fixed in v1.5.
- General slight color/tone shift versus the VAE decode; Forge Neo's color-correction toggle and histogram matching compensate. Dark scenes tend to lift toward bright.
- Pushing past the trained envelope: pink/magenta whites, chroma noise, blur. Tile instead.
- Generative decoder: it hallucinates plausible fine detail (pores, threads, leaves). Fine for art, not for forensic or document fidelity; small text it cannot read stays mush.
- Real photos and compressed inputs upscale worse than clean LDM latents.
- `LatentCrop` in core silently mis-crops 5-D Qwen/Wan latents; do not crop Qwen-family latents with it before PiD.
- ComfyUI Desktop / stable builds lagged behind nightly when PiD landed; "Node has no class_type" means the PiD nodes are missing, so update ComfyUI.
- mxfp8 files rely on hardware formats newer than Ampere; on a 3090 prefer bf16 or int8_convrot [?].
