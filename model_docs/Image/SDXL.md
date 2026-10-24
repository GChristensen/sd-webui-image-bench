# SDXL Reference

## Overview

- **Model:** Stability AI, 2023-07; successor of SD 1.5/2.1, base of Pony, Illustrious and NoobAI
- **Backbone:** UNet, 2.6B, plus an optional 6.6B base+refiner pipeline; epsilon prediction (v-prediction in some fine-tunes)
- **Text:** CLIP ViT-L + OpenCLIP ViT-bigG tokens by cross-attention, bigG pooled vector and size/crop micro-conditioning as embeddings
- **Latent:** SDXL VAE, 4 ch, 8x → multiples of 8 (64 for the buckets)
- **Strengths:** the largest ecosystem of fine-tunes, LoRAs, ControlNets and regional tools; (word:1.2) weighting works

## Encoder/VAE
- Repos: HF [stabilityai/stable-diffusion-xl-base-1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0), [stabilityai/stable-diffusion-xl-refiner-1.0](https://huggingface.co/stabilityai/stable-diffusion-xl-refiner-1.0) · ComfyUI: no Comfy-Org repack, loads the official single-file checkpoints
- Text encoder: `CLIP ViT-L/14, OpenCLIP ViT-bigG/14`
- VAE: `sdxl_vae.safetensors`

## Recommended Defaults (Base + Refiner)

``` text
resolution:   1024x1024  (or nearest official bucket for your aspect ratio)
steps:        30         (25 base + 5-8 refiner if using refiner)
sampler:      DPM++ 2M
scheduler:    Karras
cfg:          6.5
clip_skip:    1 (default / last layer — SDXL generally ignores clip-skip>1)
negative:     enabled, standard low-quality/anatomy negatives
attention:    sdpa or xformers

hires pass:
  upscale:    1.5x, pixel-space via 4x-UltraSharp then downscale, or latent upscale
  denoise:    0.4
  steps:      18
  cfg/sampler/scheduler: same as base pass
```

Base + Refiner recipe: base steps 25 @ CFG 7 stopping at ~80% (denoise switch ~0.8), refiner picks up the remaining ~20% at same CFG/sampler, 5-8 refiner steps.

## Variants

| Variant | What it is | License | File size | Pick when |
|----|----|----|----|----|
| Base 1.0 | full base UNet + 2 encoders + VAE | OpenRAIL++-M | ~6.9GB | default, all-purpose |
| Refiner 1.0 | 2nd-stage denoise specialist | OpenRAIL++-M | ~6.1GB | optional polish pass |
| SDXL Turbo | Adversarial Diffusion Distillation | RAIL-M (verify current commercial terms) [?] | ~6.9GB | 1-4 step, 512px, drafts |
| SDXL Lightning | progressive/adversarial distillation | OpenRAIL++-M | ~6.9GB | 4-8 step, 1024px, fast |
| Hyper-SDXL | ByteDance timestep-distilled LoRA/UNet | OpenRAIL++-M | LoRA ~200MB / full ~6.9GB | 1-8 step, tunable speed |
| Inpainting 0.1 | UNet finetune, +5 input channels for mask+masked-image | OpenRAIL++-M | ~6.9GB | dedicated inpaint/outpaint |

"Distilled" here means timestep/step-distilled (fewer steps to converge), not guidance-distilled in the Flux-dev sense — SDXL variants still take a real CFG value, just typically set very low (1-2).

## Resolution

Native training resolution 1024x1024, trained via aspect-ratio bucketing at ~1 megapixel across many aspect ratios. Official bucket list (width x height):

```
512x2048  512x1984  512x1920  512x1856  576x1792  576x1728  576x1664
640x1600  640x1536  704x1472  704x1408  704x1344  768x1344  768x1280
832x1216  832x1152  896x1152  896x1088  960x1088  960x1024  1024x1024
1024x960  1088x960  1088x896  1152x896  1152x832  1216x832  1280x768
1344x768  1408x704  1472x704  1536x640  1600x640  1664x576  1728x576
1792x576  1856x512  1920x512  1984x512  2048x512
```

Practical min ~768px short side (below that composition degrades). Practical max (single pass) ~1536px long side before artifacts creep in. Multiples-of-8 is the latent-space minimum; multiples of 64 are safer in practice (matches training buckets more closely). Off-spec failures: well below 1024 total area → mushy detail/blurry faces; well above native res in one pass → duplication (extra heads/limbs), tiling-like repeats, broken global composition; extreme aspect ratios outside the bucket list → stretched anatomy, compressed/duplicated subjects at frame edges.

Hires-fix/two-pass works well and is the recommended path past native res — see Upscaling below.

## Parameters

| Variant | Steps | CFG | Sampler | Scheduler | Neg. prompt | Clip skip |
|----|----|----|----|----|----|----|
| Base 1.0 | 20-35 | 5-8 | DPM++ 2M / Euler a | Karras | yes, useful | 1 (last layer) |
| +Refiner | +5-15 | same as base | same as base | Karras | yes | 1 |
| SDXL Turbo | 1-4 | 0 (ancestral, no CFG) | Euler A/LCM | trailing/simple | ignored — omit | n/a |
| SDXL Lightning | 4-8 | 1-2 | DPM++ SDE / Euler | Karras | weak, low weight | n/a |
| Hyper-SDXL | 1-8 | 1-2 (8-step), 0 (1-step "unified") | DPM++ 2M SDE / LCM | SGMUniform/Karras | weak at low step | n/a |

Recipes: **SDXL Lightning 8-step** — steps 8, CFG 1.5-2.0, DPM++ SDE, Karras, 1024x1024. **Hyper-SDXL 8-step LoRA on base** — LoRA strength 0.7-0.8, steps 8, CFG 1.5-2.0, DPM++ SDE Karras or LCM. **SDXL Turbo** — steps 1 (up to 4), CFG 0 or 1 (do NOT raise — breaks the distillation), Euler ancestral, res 512x512 native.

Silent-garbage traps: CFG 6-8 on Turbo/Lightning/Hyper checkpoints → burnt, oversaturated, contrast-blown images (treat "CFG 1-2" as load-bearing, not optional); using SD1.5's VAE scaling factor (0.18215) on SDXL latents → visibly wrong colors/contrast; running the fp16-unsafe original VAE in fp16 → black/NaN images.

## Prompting

- Style: hybrid works best — SDXL's ViT-bigG/pooled conditioning responds to natural-language structure/scene description, while its CLIP-L path and most anime/illustration finetunes (booru-tagged training data) respond well to comma-separated tags. Base SDXL leans more natural-language than SD1.5; booru-tag finetunes (Pony, Illustrious, Animagine) lean tag-first.
- Structure that works: subject, then descriptors, then setting/lighting, then style/quality tags, then camera/composition — front-load what matters most.
- Token budget: 77 tokens per encoder. Most UIs (ComfyUI, Forge) auto-chunk beyond 77 into multiple encoder passes concatenated/averaged rather than hard-truncating — but a chunk boundary can split a concept and weaken it, so keep the important part in the first 75 tokens where possible.
- Weighting syntax `(word:1.2)` / `(word)` / `[word]` is respected in ComfyUI and Forge (A1111-style prompt weighting) — a UI-layer feature, but works reliably on SDXL.
- Negative prompts: fully functional/useful on base/refiner (real CFG); much weaker/counterproductive on Turbo (CFG≈0), reduced effect on Lightning/Hyper at low CFG.
- Quality/trigger tokens: base SDXL was not trained with a strong "magic word" culture like SD1.5's "masterpiece, best quality" — those tags do less here and can even hurt on base; they matter much more on booru-trained finetunes.
- Text rendering: notably better than SD1.5 at short legible text (signs, logos, single words) but still unreliable for sentences.

Example prompts:
1. Natural-language style (base SDXL): "A weathered lighthouse on a rocky Atlantic coastline at dusk, storm clouds breaking apart, warm lamplight in the tower window, cinematic wide shot, volumetric light, photographic detail"
2. Hybrid/tag style (booru-finetune): "1girl, silver hair, blue eyes, standing in a rain-soaked neon-lit alley, cyberpunk city background, detailed fabric, dynamic pose, (rain:1.1), cinematic lighting, masterpiece"

## Generation Modes

| Mode | Support |
|----|----|
| txt2img | native |
| img2img | native, denoise 0.3-0.6 for style-preserving edits, 0.6-0.85 for heavier restyle |
| inpaint | native via masked latent blending on any checkpoint, but noticeably better edge-blending on the dedicated inpainting checkpoint (`diffusers/stable-diffusion-xl-1.0-inpainting-0.1`, +5 UNet input channels). Denoise 0.6-1.0 depending on how much of the masked region should change; 0.75-0.85 is a common default |
| outpaint | community technique (extend canvas, mask new area, inpaint) — no dedicated checkpoint; works acceptably with the inpainting checkpoint plus a generous mask feather |
| instruct-edit | not native — requires a separate instruct-pix2pix-style finetune; coverage/quality thin compared to SD1.5's original InstructPix2Pix or newer FLUX Kontext-style models [?] |
| reference/identity | not native, requires extra weights — IP-Adapter SDXL and IP-Adapter-FaceID SDXL exist and are well-supported |

## ControlNet and Structural Control

Mature: good coverage in several formats, less exhaustive than SD1.5 and split across
publishers.

- Mechanisms, not interchangeable: classic ControlNets, Union / ProMax (one model, a control type
  selector), T2I-Adapters (lighter, less precise) and ControlNet-LLLite (small, LoRA-like).
- Union: [xinsir/controlnet-union-sdxl-1.0](https://huggingface.co/xinsir/controlnet-union-sdxl-1.0)
  (openpose, depth, thick lines for scribble/HED/soft edge, thin lines for canny/MLSD/lineart,
  normal, segmentation); its ProMax file adds tile, inpaint and outpaint. The practical default
  for VRAM and stacking. ComfyUI: SetUnionControlNetType picks the type.
- xinsir single-type models: [openpose](https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0),
  [canny](https://huggingface.co/xinsir/controlnet-canny-sdxl-1.0),
  [scribble](https://huggingface.co/xinsir/controlnet-scribble-sdxl-1.0),
  [tile](https://huggingface.co/xinsir/controlnet-tile-sdxl-1.0); the strongest SDXL pose and
  lineart models.
- Others: [diffusers/controlnet-canny-sdxl-1.0](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0),
  [diffusers/controlnet-depth-sdxl-1.0](https://huggingface.co/diffusers/controlnet-depth-sdxl-1.0),
  [TheMistoAI/MistoLine](https://huggingface.co/TheMistoAI/MistoLine) (any line art),
  [TTPlanet/TTPLanet_SDXL_Controlnet_Tile_Realistic](https://huggingface.co/TTPlanet/TTPLanet_SDXL_Controlnet_Tile_Realistic).
- T2I-Adapters: [TencentARC/t2i-adapter-canny-sdxl-1.0](https://huggingface.co/TencentARC/t2i-adapter-canny-sdxl-1.0)
  and its depth, lineart, sketch and openpose siblings.
- LLLite: [bdsqlsz/qinglong_controlnet-lllite](https://huggingface.co/bdsqlsz/qinglong_controlnet-lllite)
  (anime models: canny, depth, lineart, tile, AnyTest); ComfyUI through
  kohya-ss/ControlNet-LLLite-ComfyUI.
- Quality: pose and canny/lineart are the most reliable; tile and segmentation are weaker than
  their SD1.5 counterparts.
- Strength and timing: canny/lineart 0.6-0.9, end 0.7-1.0; depth 0.5-0.8, end 0.8; pose 0.7-1.0,
  end 1.0; start 0.0 for all. Over-conditioning: flattened lighting, lost prompt detail and
  control artifacts (visible canny edges) baked in.
- Preprocessors: comfyui_controlnet_aux or Forge's built-in ones; keep the control image at the
  generation resolution, or control goes soft and misaligned.
- ComfyUI: ControlNetLoader → ControlNetApplyAdvanced. Forge Neo: classic, Union and LLLite models
  in the built-in ControlNet.
- Stacking: 2-3 ControlNets fit a 24 GB card; each costs 1.3-2.5 GB depending on type and
  precision. With Lightning, Hyper or Turbo, lower the weight and start later.
- They work on SDXL finetunes (Pony, Illustrious, NoobAI; the anime models do better with
  anime-trained ones); they do not load on SD1.5, SD3 or FLUX.

## Regional and Compositional Prompting

Working methods: masked/area conditioning, Forge Couple, latent-couple-style extensions, GLIGEN (SDXL-compatible weights exist), attention coupling, prompt scheduling — all work because SDXL is CLIP-conditioned with real cross-attention maps, the same mechanism these methods were built around for SD1.5. Concrete implementations: ComfyUI's native `ConditioningSetArea`/`ConditioningCombine` nodes, "Attention Couple" custom node, Forge's built-in Couple/Region extension, GLIGEN box-conditioning nodes.

This is one of the strongest regional-prompting ecosystems among current open models precisely because CLIP-attention masking is mature and well-understood. These methods rely on real classifier-free guidance to keep regions distinct; they weaken substantially on CFG≈1-2 distilled variants (Turbo/Lightning/Hyper) — do regional work on base+refiner.

Practical guidance: feather masks 15-40px at 1024 res to avoid hard seams; 2-4 distinct subjects hold reasonably before attribute bleed becomes visible; each region still needs a short piece of the global prompt (style/lighting/quality terms) or regions look stylistically disjointed. Per-region LoRA is supported in Forge Couple and some ComfyUI regional setups but is less mature/more fragile than global LoRA — for a 2nd character with a different LoRA, generate-then-inpaint-per-region is generally more reliable.

## Upscaling and High-Resolution Work

SDXL does not extrapolate cleanly past ~1.5x its native bucket res in a single pass — composition collapse (duplicate subjects, repeated backgrounds) sets in progressively above that.

Hires-fix two-pass: generate at native bucket (e.g. 1024x1024), upscale latent or pixel 1.5-2x, second pass denoise 0.35-0.55, steps 15-20 at same CFG/sampler as first pass. Latent upscale is faster but softer; pixel upscale (via an ESRGAN model) then VAE-encode back to latent preserves more detail before the second pass.

Tiled approaches: Tiled Diffusion/MultiDiffusion works well for pushing well past 2x without VRAM blowup. Ultimate SD Upscale is widely used, straightforward tile+seam-blend workflow. Tiled VAE decode is recommended above ~1536px to avoid VAE VRAM spikes on a 24GB card. Tile ControlNet for SDXL exists (community, quality tier below SD1.5's) — without it, expect faint tile seams on heavier upscales, mitigated by sufficient tile overlap. Typical tile size 768-1024px, 64-128px overlap.

Pair with ESRGAN-family upscalers (4x-UltraSharp, 4x_NMKD-Siax, RealESRGAN_x4plus) before the diffusion refinement pass. The dedicated SDXL Refiner is built for polishing SDXL-base latents specifically (matched noise schedule/microconditioning); using it on other models' output is possible via img2img but not its designed use case.

Recommended end-to-end pipeline (24GB card):
1. Base txt2img at native bucket, 1024x1024 or closest matching aspect, 25-30 steps
2. Optional: refiner pass for final ~15-20% of steps
3. Pixel upscale 2x with an ESRGAN model
4. img2img second pass at the upscaled res, denoise 0.35-0.45, 15-20 steps, tiled VAE decode if >1536px on the long side
5. Optional: Ultimate SD Upscale tiled pass for a further 1.5-2x if going well beyond ~2048px

## Quirks and Failure Modes

- Hands/fingers: improved vs. SD1.5 but still a known weak point — extra or fused fingers common at smaller subject scale or complex poses.
- Text: short words legible, sentences/paragraphs reliably garbled.
- CFG burn: pushing CFG above ~9-10 on base/refiner produces oversaturated, crunchy, high-contrast artifacts — the single most common "why does my SDXL look fried" cause.
- Distilled-variant CFG misconfiguration: the most common "this model is broken" report is actually using base-model CFG (5-8) on Turbo/Lightning/Hyper checkpoints — always check which variant a checkpoint actually is before copying settings.
- Aesthetic bias: base SDXL leans toward a generic "stock-photo/concept-art" look without a finetune; strong photorealism or strong anime style typically need a derivative checkpoint.
- Off-bucket resolution: composition collapse/duplication is frequently misdiagnosed as "the model can't do faces/anatomy" when it's actually a resolution/aspect-ratio problem.
- VAE NaN/black-image bug: still catches new users who load the original SDXL-VAE in fp16 without the fp16-fix — presents as fully black or fully noise output despite a sane-looking latent.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
