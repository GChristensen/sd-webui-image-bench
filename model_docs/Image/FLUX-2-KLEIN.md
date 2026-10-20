# FLUX.2 Klein Reference

## Encoder/VAE
- Repos: HF [black-forest-labs/FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B), [black-forest-labs/FLUX.2-klein-9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B) · ComfyUI [Comfy-Org/flux2-klein-4B](https://huggingface.co/Comfy-Org/flux2-klein-4B), [Comfy-Org/flux2-klein-9B](https://huggingface.co/Comfy-Org/flux2-klein-9B) (text encoders; diffusion models from the BFL `*-fp8` repos)
- Text encoder: `qwen_3_8b` (`qwen_3_4b` for the klein 4b)
- VAE: `flux2-vae.safetensors`

## Recommended Defaults (Klein 9b Turbo)

``` text
steps:           4
guidance_scale:  1.0   # no-op on distilled, harmless to leave at default
sampler:         euler
scheduler:       flow-match / normal
resolution:      1024x1024
negative_prompt: none (no-op on distilled variant)
max_sequence_length: 512
```

``` text
klein-9b-kv (multi-reference edit):
steps=4, no guidance_scale param exposed, pass 1-10 reference images
(community default workflows cap at 5)
```

## Recommended Defaults (Klein 9b Base)
``` text
steps:           20–30 (max 50)
guidance_scale:  3.5–5.0 (use 4.0)
sampler:         euler
scheduler:       simple
resolution:      1024x1024
negative_prompt: none (no-op on distilled variant)
max_sequence_length: 512
```

## Recommended Defaults (Klein 4b)

``` text
klein-4B / klein-9B (distilled, txt2img):
  steps=4, guidance_scale=1.0 (ignored anyway), sampler=euler,
  scheduler=normal/flow-match, negative prompt: don't bother, it's a no-op
  resolution=1024x1024

klein-base-4B / klein-base-9B (fine-tuning or when you need true CFG):
  steps=30-50, guidance_scale=4.0, sampler=euler,
  scheduler=normal/flow-match, negative prompt: "" or real negatives both work
  resolution=1024x1024
```

## Variants

| Variant       | What it is                      | License       | 
|---------------|---------------------------------|---------------|
| klein-4B      | 4-step timestep-distilled       | Apache 2.0    |
| klein-base-4B | Undistilled, ~50-step, for FT   | Apache 2.0    |
| klein-9B      | 4-step timestep-distilled       | FLUX Non-Comm |
| klein-base-9B | Undistilled, ~50-step, for FT   | FLUX Non-Comm |
| klein-9b-kv   | klein-9B + KV-cached ref images | FLUX Non-Comm |
| \*-fp8        | Official BFL+NVIDIA fp8 quant   | per base var  |
| \*-nvfp4      | Official BFL+NVIDIA nvfp4 quant | per base var  |
| \*-GGUF       | Community (unsloth, QuantStack) | per base var  |


## Resolution

| Item                    | Value                                    | 
|-------------------------|------------------------------------------|
| Demo/default resolution | 1024x1024                                | 
| Official bucket list    | Not published                            |
| Multiple-of requirement | Not stated; DiT+pixel-shuffle VAE likely <br> wants /16 or /32, unconfirmed            | 
| Native training res     | Unknown                                  | 

No official aspect-ratio bucket table exists yet for klein. Community
reports use standard SDXL-style buckets (1024x1024, 1152x896, 896x1152,
1216x832, 832x1216, 1344x768, 768x1344) successfully, but this is
inference by analogy, not confirmed by BFL \[?\]. Behavior off-spec
(duplication vs. mush at extreme AR): not documented, verify
empirically.


Notes:

- 9b-kv is specifically for **fast** multi-reference editing: caches K/V
  of the reference-image tokens on step 1 and reuses them on later steps
  instead of recomputing, cutting per-step cost when editing with a
  reference image.

## Prompting

- Style: natural language, not booru tags — Qwen3 is a text-only LLM
  encoder, it reads prose, not tag soup , consistent with FLUX.1's
  prompting style.
- Token budget: 512 tokens (max_sequence_length) ;
  behavior past that is truncation, not chunking (standard diffusers
  text-encoder behavior) .
- Weighting syntax (word:1.2): not natively supported by the pipeline
  API; would require a community prompt-weighting wrapper — no evidence
  one exists yet for klein specifically \[?\].
- Negative prompts: no-op on distilled variants, functional on base
  variants.
- Text rendering: BFL markets klein as strong at in-image text; specific
  benchmark numbers not found — treat as \[?\] until you test it.
- caption_upsample_temperature param exists (recommended
  0.15) for the \[dev\] Mistral pipeline to auto-expand short prompts
  — klein's pipeline signature does not expose this param, it's
  dev-only .

Two example prompts (untested by me, standard FLUX-style structure):

- "A weathered brass telescope on a ship's wooden railing at golden
  hour, ocean fog in the background, shallow depth of field,
  photorealistic"
- "Flat vector illustration of a fox reading a book under a lamp, warm
  color palette, clean line art, poster composition"

## Generation modes

| Mode                | Support                               |
|---------------------|---------------------------------------|
| txt2img             | Native, all variants                  |
| img2img             | Native (image param accepts input)    |
| Single-image edit   | Native, unified in same checkpoint    |
| Multi-reference gen | Native, up to ~10 refs (5 in default community workflows)                  |
| Inpaint             | Not a dedicated mode in the pipeline  |
| Outpaint            | Not documented                        |
| Instruct-edit       | Yes — prompt-driven single-image edit |
| Reference/identity  | Yes — the multi-reference mode itself |

No dedicated inpainting checkpoint found (unlike FLUX.1-Fill). Denoise
ranges for img2img/edit: not published by BFL; community reports
0.7–0.85 for reference-guided edits on one third-party doc \[?\] —
verify, that source also had the CFG-range inconsistency noted.

## Edit Modes

- Checkpoint: the same checkpoints edit (4B, 9B, base and distilled); klein-9b-kv caches the
  reference tokens for faster multi-reference edits. The base variants handle complex edits
  better.
- Mechanism: the VAE latents of the references are appended to the image token sequence
  (ReferenceLatent); the Qwen3 text encoder does not see them.

| Edit type                | Support | Refs |
|--------------------------|---------|------|
| Instruction edit         | native  | 1    |
| Multi-reference compose  | native  | 2-10 |
| Subject / identity ref   | native  | 1+   |
| Background swap          | native  | 1    |
| Outfit / object transfer | native  | 2    |
| Style reference          | native  | 2    |

- References: up to ~10; ComfyUI chains ReferenceLatent nodes (the default templates use up
  to 5). Each reference adds tokens and time; 9b-kv pays for them once.
- Prompt: no special token. Refer by position with a noun ("the man in image 1", "the jacket
  from the second image"); a bare index has nothing to attach to.
- Output size: set by the empty latent; keep it at the first image's aspect ratio (~1 MP) to
  avoid shifts.
- Settings: distilled 4 steps, CFG 1.0; base 20-30 steps, CFG 4. Denoise 1.0.
- Forge Neo: toggle img2img / reference (edit) in Settings › Stable Diffusion; several images
  through ImageStitch Integrated.
- Typical failures: the unedited area shifts or recolors, faces drift, the distilled model
  ignores complex multi-step instructions. State what stays unchanged; use base for detailed
  edits.

Example edit prompts:

- "Change the background to a snowy mountain pass, keep the person and the lighting on the face
  unchanged"
- "Make her hair short and red, keep everything else the same"
- "The subject from the first image wearing the jacket from the second image, in the
  environment from the third image"
- "The man in image 1 sitting on the sofa from image 2"
- "Redraw the photo in the watercolor style of the second image"

## ControlNet and Structural Control

Thin and community-only: no ControlNet for klein; structure comes through reference images.

- Native route: pass the depth, pose, canny or lineart map as a reference image (ReferenceLatent,
  or ImageStitch with the edit toggle in Forge Neo) and prompt what to take from it ("follow the
  pose of image 1"). Works on all variants, including the 4-step distilled ones.
- RefControl LoRA:
  [thedeoxen/refcontrol-FLUX.2-klein-9B-reference-depth-lora](https://huggingface.co/thedeoxen/refcontrol-FLUX.2-klein-9B-reference-depth-lora),
  for 9B Base. Trigger `refcontrol`; image 1 is the depth map, image 2 the identity reference;
  weight 0.8-1.0, ~50 steps, guidance 4.0. Trained mostly on humans; the depth map should match
  the reference in scale and proportions. The author mentions pose, lineart and canny siblings.
- [alibaba-pai/FLUX.2-dev-Fun-Controlnet-Union](https://huggingface.co/alibaba-pai/FLUX.2-dev-Fun-Controlnet-Union)
  targets FLUX.2 dev; on klein users report partial effect without strength or timestep control.
- FLUX.1 ControlNets do not load.
- Bottom line: if structural control is a hard requirement, FLUX.1 dev or SDXL have far more
  mature ControlNets.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
