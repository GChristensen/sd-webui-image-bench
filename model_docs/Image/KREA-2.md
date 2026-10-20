# Krea 2 Reference

## Encoder/VAE
- Repos: HF [krea/Krea-2-Raw](https://huggingface.co/krea/Krea-2-Raw), [krea/Krea-2-Turbo](https://huggingface.co/krea/Krea-2-Turbo) · ComfyUI [Comfy-Org/Krea-2](https://huggingface.co/Comfy-Org/Krea-2)
- Text encoder: `Qwen3-VL-4B`
- VAE: `qwen_image_vae.safetensors`

## Recommended Defaults (Krea 2 Turbo)
    Steps:      8
    CFG:        1.0
    Sampler:    euler
    Scheduler:  simple
    Denoise:    1.0
    Resolution: 1024x1024 (up to 2048x2048)
    Negative:   empty / minimal


## Recommended Defaults (Krea 2 Raw)
    Steps:      ~52
    CFG:        3.5
    Sampler:    [?] not documented — try euler/simple as a starting point, verify
    Resolution: 1024x1024

# Variants

| variant | what it is                                          | license | picks |
|----|-----------------------------------------------------|----|----|
| Raw | undistilled base, full-step (52-step recipe)                        | Krea 2 Comm. License  | LoRA/finetune train, max diversity  |
| Turbo | TDM-distilled, 8-step                               | Krea 2 Comm. License | fast local gen  |
| FP8 scaled | community fp8 quant of both                         | inherits above | fits 24GB w/ margin |
| GGUF (Q3-Q8) | community llama.cpp-style quant                     | inherits above | 8-12GB cards |
| NVFP4/INT8/MXFP8 | community quants on HF (mxfp8, nvfp4, int8_convrot) | inherits above | untested here, \[?\] |

Notes:

- No official "lightning/hyper/schnell/dev/pro/lite" split — Krea only
  ships Raw and Turbo. There is a "Krea 2 Identity Edit" LoRA/adapter
  (`conradlocke/krea2-identity-edit`) and community inpaint/outpaint
  adapters (`krea2-outpaint`, `krea2-anypaint`) — these are add-on
  LoRAs/adapters, not separate base checkpoints .
- Turbo is **not** guidance-distilled in the FLUX-schnell sense of
  "baked-in CFG embed" — it's TDM (Trajectory Distribution Matching)
  trajectory-distilled, and is run at CFG≈1.0 (effectively off).

## Resolution

- Training: progressive curriculum 256px -\> 512px -\> 1024px
- Native*practical output: designed and marketed for up to 2048x2048
  (2K); ComfyUI workflow examples use "megapixels" target of 2.0 for 2K
  output
- Exact aspect-ratio bucket list: \[?\] not published; workflows use a
  target-megapixel
  - aspect-ratio input rather than a fixed bucket table (DiT-style
    flexible framing)
- Multiples requirement: \[?\] not explicitly documented; DiT/RoPE
  designs of this kind typically want multiples of 16 or 32 — verify
  before relying on it
- Hires-fix / two-pass: no official guidance found

## Parameters

| variant | steps | CFG         | sampler | scheduler | shift/mu       | neg prompt   |
|---------|-------|-------------|---------|-----------|----------------|--------------|
| Raw     | ~52   | 3.5 (true CFG)  | \[?\]   | \[?\]     | \[?\]          | \[?\]        |
| Turbo   | 8     | 1.0-ish, effectively disabled    | euler   | simple    | mu=1.15 (official interface example)        | minimal/none - model is disabled for it     |

- CFG on Turbo is the single most important trap: "Krea 2 Turbo is
  distilled for CFG ≈ 1.0 — higher values (7, 15) degrade output" per
  hands-on ComfyUI testing . This is analogous to
  FLUX-schnell/turbo guidance collapse — do not bring SDXL-style CFG 7
  habits over.
- clip skip: not applicable — this is a single VLM-based text encoder,
  not a CLIP stack with layer-skip conventions

## Prompting

- Natural language prose is the primary/intended mode — Krea explicitly
  moved away from comma-separated tag clouds toward long descriptive
  prose (composition, lighting, materiality), especially at 2K
  /
- Effective token budget: ~512 tokens reliable; 640+ produces
  black/corrupted output in reported ComfyUI testing  — this reads
  as a hard failure, not graceful truncation, so stay well under 512 for
  safety margin
- Attention weighting syntax `(word:1.2)`: \[?\] not documented/tested —
  Qwen3-VL is a VLM-derived encoder, not classic CLIP, so classic
  emphasis syntax is not guaranteed to parse the same way. Verify
  empirically before relying on it.
- Negative prompts: minimal/no effect reported on Turbo (distilled,
  low/no CFG) ; presumably more meaningful on Raw at CFG 3.5 but
  not explicitly confirmed \[?\]
- Quality/trigger tokens: none documented — no magic keyword list found
  \[?\]
- Text rendering: not specifically benchmarked in sources found;
  Qwen-Image (sibling model, shares VAE/encoder family) is noted
  elsewhere as the strong text-renderer of this generation, with Krea 2
  positioned instead around aesthetic/style control  — don't assume
  Krea 2 inherits Qwen-Image's text-rendering strength
- What it reliably ignores: \[?\] no confirmed data

Two example prompts (style, not verified output — construct per the
prose guidance above):

1.  "A wide-angle photograph of a rain-slicked city street at night,
    neon signage reflected in puddles, a lone figure under a translucent
    umbrella, shot on 35mm film with visible grain and soft chromatic
    aberration at the edges."
2.  "Editorial illustration, gouache texture, a ceramic teapot and
    citrus fruit on a linen tablecloth, warm afternoon light from
    camera-left, flat graphic shadows, muted earth-tone palette."

## Generation modes

| Mode               | Support                 |
|--------------------|-------------------------|
| txt2img            | native                  |
| img2img            | native                  |
| inpaint            | handled via community adapters |
| outpaint           | semi-reliable   |
| instruct-edit      | community "Krea 2 Identity Edit" LoRA |
| reference/identity | native — up to 4 style reference images or a moodboard <br/>each with an independent  strength slider   |

## Edit Modes

- Checkpoint: Krea 2 has no official edit model. Editing is done with community LoRAs:
  - Krea 2 Identity Edit (`conradlocke/krea2-identity-edit`, v1.2 recommended, trained on Raw,
    run on Turbo), node pack ComfyUI-Krea2Edit.
  - Turbo Style Reference (`ostris/krea2_turbo_style_reference`, 1-2 references, no trigger
    word), node pack ComfyUI-Krea2-Ostris-Edit.
- Mechanism: the references enter twice, as in-context VAE tokens and through the Qwen3-VL
  encoder, which sees the image; stock nodes provide neither, hence the node packs.

| Edit type                     | Support        | Refs |
|-------------------------------|----------------|------|
| Re-stage person (likeness)    | Identity Edit  | 1    |
| Local edit (recolor/add/swap) | Identity Edit  | 1    |
| Outfit change                 | Identity Edit  | 1    |
| Restyle                       | Identity Edit  | 1    |
| Person into scene             | Identity Edit  | 2    |
| Head / face swap              | Identity Edit  | 2    |
| Virtual try-on                | Identity Edit  | 2    |
| Inpaint / outpaint            | Identity Edit  | 1    |
| Removal                       | Identity Edit  | 1    |
| Style reference               | Style Ref LoRA | 1-2  |

- References: two at most. In two-input edits the scene is image 1 (`image`) and the person
  image 2 (`image_b`); swapping them degrades the result badly.
- Prompt: plain-language instructions with "this person", "the woman"; no index syntax.
- Output size: 2 MP or less; ~1-1.5 MP for two-person edits, then upscale. v1.2 `fit` geometry
  handles a different aspect ratio; with older weights match the source.
- Settings: Turbo, 8-12 steps (10 balanced: 8 favors composition, 12 face detail), CFG 1.0,
  LoRA 1.0, denoise 1.0. Removals: Raw, 20 steps, CFG 3.0. `ref_boost` ~4 for strong likeness
  (above 10 breaks removals); `grounding_px` 384-768: lower follows the edit, higher keeps the
  likeness.
- Forge Neo: toggle img2img / reference (edit) in Settings › Stable Diffusion; needs the
  Identity Edit LoRA.
- Typical failures: distinctive faces regress toward average proportions, two faces in one edit
  blend (chain single-reference inserts instead), removals re-render instead of deleting,
  outfit swaps sometimes ignored, local edits shift the color grade, duplicated "double
  pictures" with `grounding_px` far above the trained range.

Example edit prompts:

- "create a photo of this person at a night market"
- "create a photo of this man next to the tractor"
- "replace the woman with a big orangutan"
- "change her coat to a yellow raincoat"
- "turn the photo into a flat gouache illustration"
- "remove the bicycle from the street"

## ControlNet and Structural Control

Thin and community-only: control LoRAs, each with its own node pack; no classic ControlNet.

- Mechanisms, not interchangeable:
  - Control LoRAs with an expanded input projection: the VAE-encoded control image is
    concatenated to the noisy latent by channel (64 → 128), and a LoRA on all 28 blocks follows
    it.
  - Edit-style LoRAs: the control map enters as a reference image of the Ostris edit nodes.
- Depth: [Patil/Krea-2-depth-controlnet](https://huggingface.co/Patil/Krea-2-depth-controlnet)
  (Tanmay Patil, `depth-control-lora.safetensors`, 862 MB). Trained on Raw, works on Raw and
  Turbo; Depth-Anything-V2-Large maps; scale 1.0, lower loosens the structure, higher tightens it
  at a quality cost. Card recipes: Turbo 8 steps, CFG 0; Raw 28-52 steps, CFG 3.5. Outputs up to
  ~1 MP.
- ComfyUI for channel-concat LoRAs:
  [facok/comfyui-krea2-controlnet](https://github.com/facok/comfyui-krea2-controlnet) (Krea2
  Control LoRA Loader → Krea2 Control Image Encode → Krea2 Control Apply; sampling fails if the
  control latent is not attached).
- Loose composition and silhouette:
  [tori29umai/krea2-controlnet](https://huggingface.co/tori29umai/krea2-controlnet)
  `krea2-anythng` (Raw, rank 64), nodes comfyui-krea2-controlnetPlus (Krea2 Control Plus Image
  Encode, LoRA Loader, Apply), start/end percent; a lineart model is announced.
- Pose: [thedeoxen/Krea-2-pose-controlnet](https://huggingface.co/thedeoxen/Krea-2-pose-controlnet),
  for Turbo. The DWPose/OpenPose map (black background) is image 1 of TextEncodeKrea2OstrisEdit
  ([ostris/comfyui-krea2-ostris-edit](https://github.com/ostris/comfyui-krea2-ostris-edit));
  weight 0.8-1.0, 0.6-0.8 if the pose is too rigid; ~10 steps, CFG 1.0, euler/simple. Trained
  mostly on humans; subject scale in the map matters.
- Lineart: [Cierpliwy/krea2_lineart_edit](https://huggingface.co/Cierpliwy/krea2_lineart_edit),
  for Raw, through the Ostris edit nodes: `krea2_lineart_edit_v1` follows the sketch,
  `krea2_lineart_coarse_edit_v1` takes freedom; Realistic Lineart preprocessor for photos.
- Over-conditioning: rigid, mannequin poses and flattened lighting; lower the weight first.
- Forge Neo: not supported; FLUX and Qwen-Image ControlNets do not load.
- Bottom line: depth, pose and lineart work, but canny, tile and multi-control stacking need
  SDXL or FLUX.1.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
