# FLUX.1 dev Reference

## Overview

- **Model:** Black Forest Labs, 2024-08; guidance-distilled from the closed FLUX.1 [pro]
- **Backbone:** hybrid MMDiT, 19 double-stream + 38 single-stream blocks, 12B; rectified flow
- **Text:** T5-XXL tokens in joint attention, CLIP-L pooled vector as modulation alongside the timestep and guidance embedding
- **Latent:** FLUX.1 VAE `ae`, 16 ch, 8x, 2x2 patches → multiples of 16
- **Positions:** 2D RoPE on image tokens, so any size near 1 MP works without buckets
- **Strengths:** the largest open LoRA / ControlNet ecosystem after SDXL; Fill, Canny, Depth, Redux and Kontext variants on one architecture

## Encoder/VAE

- Repos: HF [black-forest-labs/FLUX.1-dev](https://huggingface.co/black-forest-labs/FLUX.1-dev) · ComfyUI [Comfy-Org/flux1-dev](https://huggingface.co/Comfy-Org/flux1-dev)
- VAE: `ae.safetensors`
- Text encoders: CLIP-L, T5-XXL

## Recommended Defaults

``` text
sampler:                      euler
scheduler:                    simple
steps:                        20        # 28-30 for final renders
guidance (FluxGuidance node): 3.5
cfg (KSampler):               1.0       # do NOT raise this
max_sequence_length:          512

width x height: 1024 x 1024   # or any 1mp bucket, multiples of 16

# Hires (optional second pass)
upscale: 1.5x latent
denoise (pass 2): 0.4
steps (pass 2): 12
```

## Variants

| Variant | What it is | License | Size |
|----|----|----|----|
| dev | guidance-distilled base | Non-commercial | ~23.8GB |
| schnell | timestep-distilled (4-step), from pro | Apache-2.0 | ~23.8GB |
| pro | full model, API-only, not open weight | closed/API | n/a |
| pro (Ultra/Raw) | API-only, higher res / less "AI look" | closed/API | n/a |
| Fill-dev | dev fine-tune for inpaint/outpaint | Non-commercial | ~23.8GB |
| Canny-dev | dev fine-tune, canny structural control | Non-commercial | ~23.8GB |
| Depth-dev | dev fine-tune, depth structural control | Non-commercial | ~23.8GB |
| Canny-dev-lora | LoRA version of Canny control | Non-commercial | ~1.5GB |
| Depth-dev-lora | LoRA version of Depth control | Non-commercial | ~1.5GB |
| Redux-dev | image-prompt adapter (not a checkpoint) | Non-commercial | ~130MB |
| Kontext-dev | instruction-based image editing model | Non-commercial | ~23.8GB |
| fp8 (Comfy-Org) | official-ish fp8 weight-only quant | Non-commercial | ~11.9GB |
| GGUF (city96) | community llama.cpp-style quant, Q2-Q8 | Non-commercial | 4-13GB |
| NF4 | bitsandbytes 4-bit quant, Forge/A1111 | Non-commercial | ~6.7GB |


## Resolution

Native training resolution 1024×1024, with multi-aspect-ratio bucket training so it
generalizes across ratios better than SD1.5/SDXL did without explicit
bucket conditioning.

Practical range: claimed working range `256² to 2048²`, but **optimal** quality is
at `1024² total pixels`; both much smaller and much larger resolutions
measurably degrade quality \[?\]

- Common aspect buckets in use (all ≈1024² pixel budget) :

  | Ratio | Pixels    |
    |-------|-----------|
  | 1:1   | 1024x1024 |
  | 4:3   | 1152x896  |
  | 3:2   | 1216x832  |
  | 16:9  | 1344x768  |
  | 21:9  | 1536x640  |
  | 3:4   | 896x1152  |
  | 2:3   | 832x1216  |
  | 9:16  | 768x1344  |

Parameters that silently produce garbage if wrong: real CFG left above
1.0 while also using a guidance-embedding value (double-application of
guidance → burnt/oversaturated images) ; resolution not a multiple
of 16 on some older nodes \[?\]; T5 max<sub>sequence</sub>\_length below
what your prompt needs → silent truncation, not an error.

## Prompting

Style  
Natural language prompting is what FLUX was trained for — T5-XXL gives
it real sentence-level comprehension, closer to a captioning model than
a booru-tag soup. Danbooru/booru tag strings still work
(CLIP-L parses them) but under-use the T5 pathway and tend to produce
flatter results than a well-formed sentence.

Structure that works  
Front-load subject and composition, follow with style/lighting/camera
detail, keep it as coherent prose rather than a comma-stack of
disconnected tags.

Attention/weighting syntax  
`(word:1.2)`-style weighting is NOT natively understood by the T5/CLIP
encoders the way SD's CLIP weighting hacks work; ComfyUI's `(word:1.2)`
node syntax still function mechanically (it reweights the embedding) but
effectiveness is weaker/less predictable than on SD1.5/SDXL, and many
users report inconsistent results.

What it reliably ignores  
Very long negative-style instructions embedded in the positive prompt
("no X", "avoid Y") are inconsistently honored since there's no true
negative channel — better handled by inpainting the unwanted region than
by prompting around it.

Example prompts
1.  `A weathered fisherman in an oilskin coat standing on a fog-covered dock at dawn, holding   a lantern, cinematic lighting, shallow depth of field, shot on 35mm film`
2.  `Overhead flat-lay of a minimalist desk setup: matte black keyboard, ceramic coffee cup   with steam, small potted succulent, soft morning window light, muted color palette`

## Generation Modes

| Mode               | Support                   |
|--------------------|---------------------------|
| txt2img            | native                    |
| img2img            | native                    |
| inpaint            | flux-fill checkpoint      |
| outpaint           | same as inpaint           |
| instruct-edit      | flux-kontext              |
| reference/identity | redux-dev/flux ip-adapter |

## Edit Modes

- Checkpoint: the separate FLUX.1 Kontext [dev] (`flux1-kontext-dev.safetensors`, same 12B
  architecture and text encoders, FLUX non-commercial license).
- Mechanism: the VAE latent of the input image is appended to the image token sequence with
  offset positions; the text encoders do not see the image.

| Edit type             | Support  | Refs |
|-----------------------|----------|------|
| Instruction edit      | native   | 1    |
| Style transfer        | native   | 1    |
| Character consistency | native   | 1    |
| Text editing          | native   | 1    |
| Background change     | native   | 1    |
| Object removal        | native   | 1    |
| Multi-reference       | stitched | 2-3  |

- References: trained on one image. More go in as one stitched image (ImageStitch) or as
  chained ReferenceLatent nodes; each adds its tokens, so time grows with every reference.
- Prompt: no image syntax. Name the subject explicitly ("the woman with short black hair", not
  "she"); stitched inputs are "the left / right image".
- Output size: FluxKontextImageScale resizes the input to the nearest Kontext training
  resolution (~1 MP); the latent comes from that image.
- Settings: FluxGuidance 2.5 (instead of 3.5), 20 steps, euler / simple, KSampler cfg 1.0,
  denoise 1.0.
- ComfyUI: LoadImage → FluxKontextImageScale → VAEEncode → ReferenceLatent → FluxGuidance.
  Forge Neo: supported when the checkpoint path contains `kontext`; several images through
  ImageStitch Integrated.
- Typical failures: "transform" rewrites the whole image, identity drifts over chained edits,
  slight zoom or shift, a short prompt is ignored by [dev]. State what changes and what stays
  ("while keeping ... unchanged"), and edit in several small steps.

Example edit prompts:

- "Change the car color to red while keeping everything else unchanged"
- "Change to Bauhaus style while maintaining the original composition"
- "Replace 'OPEN' with 'CLOSED' on the sign"
- "Change the background to a beach while keeping the person in the exact same position, scale
  and pose"
- "The woman with short black hair is now sitting in a café, while maintaining the same facial
  features, hairstyle and expression"
- "Remove the person in the background"


## ControlNet and Structural Control

Mature: the widest open control set after SDXL, from several publishers, in three formats that
do not replace each other.

- Mechanisms:
  - Union ControlNets: one model, several control types.
  - Single-type ControlNets.
  - BFL's dedicated Canny and Depth checkpoints and LoRAs: the control image is concatenated to
    the latent (ComfyUI InstructPixToPixConditioning), no ControlNet node.
- Union: [Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0](https://huggingface.co/Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0)
  (3.98 GB; canny, soft edge, depth, pose, gray; no tile; the best general choice), fp8
  [ABDALLALSWAITI/FLUX.1-dev-ControlNet-Union-Pro-2.0-fp8](https://huggingface.co/ABDALLALSWAITI/FLUX.1-dev-ControlNet-Union-Pro-2.0-fp8).
  The older [Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro](https://huggingface.co/Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro)
  (6.15 GB) adds tile, blur and low-quality modes;
  [InstantX/FLUX.1-dev-Controlnet-Union](https://huggingface.co/InstantX/FLUX.1-dev-Controlnet-Union)
  is the original, with weak pose.
- Union Pro 2.0 settings from its card:

| Type      | Preprocessor     | Strength | End  |
|-----------|------------------|----------|------|
| Canny     | cv2.Canny        | 0.7      | 0.8  |
| Soft edge | AnylineDetector  | 0.7      | 0.8  |
| Depth     | Depth-Anything-V2 | 0.8     | 0.8  |
| Pose      | DWPose           | 0.9      | 0.65 |
| Gray      | grayscale        | 0.9      | 0.8  |

- Single-type: [jasperai/Flux.1-dev-Controlnet-Upscaler](https://huggingface.co/jasperai/Flux.1-dev-Controlnet-Upscaler)
  (tile/upscale), [jasperai/Flux.1-dev-Controlnet-Depth](https://huggingface.co/jasperai/Flux.1-dev-Controlnet-Depth),
  [jasperai/Flux.1-dev-Controlnet-Surface-Normals](https://huggingface.co/jasperai/Flux.1-dev-Controlnet-Surface-Normals),
  [XLabs-AI/flux-controlnet-collections](https://huggingface.co/XLabs-AI/flux-controlnet-collections)
  (canny, depth, HED v3; trained at 1024).
- Inpaint: [alimama-creative/FLUX.1-dev-Controlnet-Inpainting-Beta](https://huggingface.co/alimama-creative/FLUX.1-dev-Controlnet-Inpainting-Beta);
  FLUX.1 Fill is the stronger inpaint route.
- BFL: [black-forest-labs/FLUX.1-Canny-dev](https://huggingface.co/black-forest-labs/FLUX.1-Canny-dev)
  (guidance 30), [black-forest-labs/FLUX.1-Depth-dev](https://huggingface.co/black-forest-labs/FLUX.1-Depth-dev)
  (guidance 10), and the LoRAs [FLUX.1-Canny-dev-lora](https://huggingface.co/black-forest-labs/FLUX.1-Canny-dev-lora)
  and [FLUX.1-Depth-dev-lora](https://huggingface.co/black-forest-labs/FLUX.1-Depth-dev-lora) on
  the normal dev checkpoint. Tightest adherence, but no strength or end control.
- ComfyUI: ControlNetLoader → ControlNetApplyAdvanced (strength, start/end percent) for
  the Union and single-type models; preprocessors from comfyui_controlnet_aux. Forge Neo lists
  ControlNet support for the SDXL family and Anima only.
- Control image at the output resolution; Union Pro 2.0 was trained at 512 but follows
  1024-class maps.
- Over-conditioning: plastic skin, flat lighting, edge lines and depth banding baked into the
  image; an end of 0.6-0.8 fixes most of it before the strength needs lowering.
- VRAM: each ControlNet adds about its file size (Union Pro 2.0: 4 GB bf16, 2 GB fp8); one
  Union beside fp8 dev fits a 24 GB card.
- They load on dev finetunes and with step-reduction LoRAs (lower the strength). FLUX.1 schnell
  is not a target, and FLUX.2 / klein cannot load them.

## Upscaling and High-Resolution Work

Native above-resolution behavior  
Pushing base generation resolution past ~1.5-2x training res (roughly
\>1536-1600px side) starts producing duplication/tiling artifacts and
composition collapse rather than just softness  (§3)

Hires-fix two-pass  
Generate at a training-bucket resolution, then img2img the upscaled
latent/pixel image. Typical: upscale 1.5-2x, denoise 0.3-0.5 for the
second pass (lower = closer fidelity, higher = more re-generation/detail
add but more drift), same sampler/ scheduler as base pass, steps 10-20
for the refine pass \[?\]

Tiled approaches  
**Ultimate SD Upscale** is the dominant tool in the community for FLUX,
tiling the image and re-diffusing each tile with a low-medium denoise
. Tiled Diffusion/ MultiDiffusion also used. No dedicated "tile
ControlNet" specifically validated for FLUX was confirmed in this pass
\[?\] — Union-Pro's "tile" mode (§8) is the closest official-ish option
and can help tile coherence at the seams. Typical tile size 768-1024px
with 64-128px overlap; without any tile-coherence aid, seams are visible
at high denoise (\>0.4) on tiles \[?\]

Dedicated upscalers  
Standard ESRGAN-family models (4x-UltraSharp, 4x<sub>NMKD</sub>-Siax,
RealESRGAN) are commonly paired as a pre-upscale pass before the
diffusion refine pass, not standalone final output \[?\]. No
FLUX-specific diffusion-based restorer confirmed as a standard choice in
this pass — flag as unverified \[?\]

Recommended end-to-end pipeline
1.  Base txt2img at a 1024²-budget bucket (§3), 20-30 steps
2.  Latent upscale 1.5x (or pixel upscale + VAE re-encode), img2img pass
    at denoise 0.35-0.45, 10-15 steps
3.  Optional: Ultimate SD Upscale tiled pass for final detail at denoise
    0.2-0.35
4.  ESRGAN-family pre-sharpen/upscale before step 2 if starting
    resolution is low \[?\]

## Quirks and Failure Modes

"Flux chin" / plastic-waxy skin  
A widely-reported aesthetic bias — skin often renders overly smooth,
plastic/waxy, lacking pore-level detail, and a recognizable chin/jaw
shape recurs across generations; attributed by the community to the
breadth/mix of the training data (heavy 2D/3D-render content) rather
than a bug . LoRAs targeting "skin realism" are the common
community fix, though several reports note the fix degrades again once
you upscale past ~1024px \[?\]

Oversaturation/burn  
Setting real sampler CFG above 1.0 on top of the guidance-embedding
value (§5) is the most common cause of washed-out, over-contrasted,
"fried" output — often mistaken by users for the model being broken

Negative prompts appearing to "do nothing"  
Expected behavior on dev's distilled pipeline, not a bug (§6) —
frequently reported as confusion in community threads

Weak native inpainting  
Using base dev (rather than Fill-dev) for inpainting produces visible
seams/context mismatch; commonly misread as a general model flaw rather
than "wrong checkpoint for the task" (§7)

Hands/anatomy  
Meaningfully better than SD1.5-era models but still not solved — extra/
fused fingers and anatomical errors persist, especially at unusual poses
or with multiple subjects \[?\]

Off-bucket resolution collapse  
Rendering far outside trained aspect buckets or resolution causes
duplication/tiling rather than graceful degradation (§3) — often
misdiagnosed as a sampler/seed problem

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
