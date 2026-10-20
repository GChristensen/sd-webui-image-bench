# FLUX.2 dev Reference

## Encoder/VAE
- Repos: HF [black-forest-labs/FLUX.2-dev](https://huggingface.co/black-forest-labs/FLUX.2-dev) · ComfyUI [Comfy-Org/flux2-dev](https://huggingface.co/Comfy-Org/flux2-dev)
- Text encoder: `Mistral-Small-3.2-24B-Instruct`
- VAE: `flux2-vae.safetensors`

## Recommended Defaults

``` text
steps:               28          (50 is pipeline default; 28 is BFL's stated good tradeoff)
guidance_scale:      2.5-4.0     (embedded guidance, not true CFG)
resolution:          1024x1024
scheduler:           FlowMatchEulerDiscreteScheduler (ComfyUI: native Flux2 nodes)
negative_prompt:     none (not supported on dev)
max_sequence_length: 512
```

## Resolution

- Default/best-tested: 1024x1024.
- Stated ceiling: image editing supported "up to 4MP".
- Per-side range roughly 256-1440px [?], aspect ratio range claimed 1:1 to 21:9 [?] — both from secondary sources, verify before relying on extreme ratios.
- Divisibility: no official statement; multiples of 16px is the safe community default (2x2 patchify over the VAE's spatial downsample), same convention as FLUX.1.
- Expect the usual flow-matching failure modes (composition collapse/duplication) far off native res, by analogy with FLUX.1 — not confirmed for FLUX.2 specifically [?].

## Prompting

- Style: natural language/descriptive prose, not booru tags — the encoder is an instruction-tuned 24B VLM, not a CLIP/T5 pairing [?].
- Token budget: 512 tokens (`max_sequence_length`); behavior past that is undocumented, assume truncation.
- Caption upsampling: set `caption_upsample_temperature` (BFL recommends 0.15) to have the model expand a terse prompt before encoding.
- Weighting syntax `(word:1.2)`: not documented, architecturally unlikely to be respected the way CLIP-based weighting is, since conditioning comes from an autoregressive LLM's hidden states [?].
- Negative prompts: not usable on dev at all. Usable on klein-base only.
- Text rendering: explicitly marketed strength — strong control over layout, logos, and typography.

Two example prompts:
1. "A weathered leather-bound notebook lying open on a rain-speckled café table, soft overcast daylight from a window on the left, shallow depth of field, the page reads 'August 19' in handwritten ink."
2. "Studio product photo of a matte black ceramic mug on a marble surface, three-point softbox lighting, subtle rim light, logo on the mug reads 'ATELIER', 45-degree angle, commercial photography style."

## Generation Modes

| Mode | Support |
|----|----|
| txt2img | native |
| img2img / reference editing | native, central to the model — single/multi-reference editing via the `image` argument; up to 10 reference images for dev, 4 for klein-9B-kv |
| inpaint | no dedicated checkpoint/pipeline parameter found [?] |
| outpaint | not documented [?] |
| instruct-edit | yes — this is the model's edit mode: natural-language instruction + reference image(s) in one forward pass |
| reference/identity | native multi-reference conditioning |

## Edit Modes

- Checkpoint: the same FLUX.2 [dev] checkpoint does generation, editing and multi-reference.
- Mechanism: the VAE latents of the references are appended to the image token sequence
  (ReferenceLatent); the Mistral text encoder does not see them.

| Edit type               | Support | Refs |
|-------------------------|---------|------|
| Instruction edit        | native  | 1    |
| Multi-reference compose | native  | 2-10 |
| Subject / identity ref  | native  | 1+   |
| Product consistency     | native  | 1+   |
| Style reference         | native  | 1+   |
| Text editing            | native  | 1    |

- References: up to 10; ComfyUI chains one ReferenceLatent per image. Each reference adds its
  tokens, so time and VRAM grow with every one; 4-6 is the practical range on 24 GB.
- Prompt: refer by position with a noun ("the subject from the first image", "the jacket from
  the second image"). Do not redescribe what a reference already shows; describe the scene,
  lighting and camera.
- Output size: set by the empty latent; the template scales references to ~1 MP. Editing is
  supported up to 4 MP.
- Settings: as txt2img (28-50 steps, guidance 2.5-4), denoise 1.0.
- ComfyUI: LoadImage → ImageScaleToTotalPixels → VAEEncode → ReferenceLatent (one per image)
  → FluxGuidance. Forge Neo does not support FLUX.2 [dev] (only klein).
- Typical failures: identity drift on faces, too many references dilute each other, the prompt
  contradicting a reference wins over it.

Example edit prompts:

- "Turn this cat into a dog"
- "Change the jacket to dark green leather, keep the person, pose and background unchanged"
- "The subject from the first image wearing the jacket from the second image, standing in the
  street from the third image"
- "Place the product from the first image on a marble counter in soft morning light"
- "Repaint the scene in the style of the second image, keep the composition of the first"
- "Change the text on the mug to 'ATELIER'"

## ControlNet and Structural Control

Thin: one Union ControlNet from Alibaba PAI, run through custom nodes.

- [alibaba-pai/FLUX.2-dev-Fun-Controlnet-Union](https://huggingface.co/alibaba-pai/FLUX.2-dev-Fun-Controlnet-Union):
  VideoX-Fun Union side branch; canny, HED, depth, pose and MLSD, plus scribble and gray in the
  `2602` file; an inpaint mode. FLUX non-commercial license.
- Scale (`controlnet_conditioning_scale`) 0.65-0.80 per the card, a narrow window; a detailed
  prompt keeps it stable.
- ComfyUI core does not load it (ControlNetLoader reports an invalid file). Custom nodes:
  - [bryanmcguire/comfyui-flux2fun-controlnet](https://github.com/bryanmcguire/comfyui-flux2fun-controlnet):
    Load + Apply pair, strength 0-2, optional mask and inpaint image; reported to work with fp8
    scaled and GGUF Q4_K_M dev.
  - [Damkohler/JLC-Flux2-ControlNet](https://github.com/Damkohler/JLC-Flux2-ControlNet): several
    ControlNets composed in one pass, loads the mixed fp8/bf16 `2602` checkpoint.
- Forge Neo: FLUX.2 dev is not supported.
- On a 3090 the 32B transformer already offloads; the control branch adds more.
- Without a ControlNet: pass the pose, depth or canny map as a reference image (ReferenceLatent)
  and say what to take from it ("use the pose of image 2").
- It does not work on klein (different transformer).
- Bottom line: for production structural control, FLUX.1 dev or SDXL remain more dependable.

## Upscaling and High-Resolution Work

FLUX.2-specific guidance is sparse; most of this is carried over from general FLUX/flow-matching practice, not confirmed against FLUX.2 [?].

- Native ceiling: editing works "up to 4MP"; behavior generating natively far past that isn't documented.
- Two-pass hires-fix: no FLUX.2-specific values found. Starting point by analogy with FLUX.1: ~1.5x latent upscale, second-pass denoise 0.3-0.5, same steps/guidance as base pass — verify empirically.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
