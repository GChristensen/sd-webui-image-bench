# Anima Reference

## Encoder/VAE
- Repos: HF [circlestone-labs/Anima](https://huggingface.co/circlestone-labs/Anima) · ComfyUI: same repo, `split_files/`
- Text encoder: `qwen_3_06b_base.safetensors`
- VAE: `qwen_image_vae.safetensors`

## Recommended Defaults (Anima-Base v1.0)
    steps           : 32 (drafts) / 40 (finals)
    cfg             : 4.5
    sampler         : er_sde
    scheduler       : normal
    shift           : unconfirmed
    resolution      : 1024x1024
    positive_prefix : masterpiece, best quality, score_7, safe,
    negative_prompt : worst quality, low quality, score_1, score_2, score_3, artist name, blurry, jpeg artifacts, chromatic aberration
    prompt_style    : tag/prose hybrid, [quality][count][character][series][@artist][tags]
    weighting       : (word:2) style — SDXL-habit (word:1.2) under-weights on this model

## Recommended Defaults (Turbo, official) :
    steps           : 10
    cfg             : 1.0
    sampler         : euler
    scheduler       : normal
    resolution      : 1024x1024
    negative_prompt : (optional, weak effect)

## Variants

| Variant   | Kind              | License    | Size     | Pick when                  |
|-----------|-------------------|------------|----------|----------------------------|
| Base v1.0 | foundation ckpt   | CC-Labs NC | unk\[?\] | flexibility, LoRA training |
| Aesthetic | curated fine-tune | CC-Labs NC | unk\[?\] | default look, less prompt  |
| Turbo     | distilled         | CC-Labs NC | unk\[?\] | speed, CFG-1, 8-12 steps   |
| Preview3  | dev snapshot      | CC-Labs NC | unk\[?\] | superseded by v1.0         |

## Resolution

- Officially supported range: 512x512 to 1536x1536 No official
  native/default resolution number or exact aspect-ratio bucket list was
  published in the sources.
- Above 1536px: community reports 2048x2048+ is reachable via a
  dedicated "Anima Highres LoRA" in Forge Neo rather than the base model
  alone.
- Hires-fix / two-pass: no official guidance found

## Parameters

| Setting | Base / Aesthetic           | Turbo |
|----|----------------------------|----|
| Steps | 30-50                      | 8-12  |
| CFG | 4-5, true CFG              | 1, distilled  |
| Sampler | er_sde (default)           | euler  |
| Sampler alt | euler_a, dpmpp_2m\_sde_gpu | \- |
| Scheduler | normal (assumed) \[?\]     | normal (assumed)\[?\] |
| Scheduler alt | beta57, for painterly look | \- |
| Shift | not documented \[?\]       | not documented \[?\] |
| Negative pr. | supported, useful          | weak/optional  |
| Clip skip | n/a (Qwen3 encoder)        | n/a  |


## Prompting

- Style: hybrid, tag-first with prose allowed . Structure per the
  official card:
  `[quality/meta/year/safety] [character count] [character] [series] [@artist] [general tags]`.
- Natural language works too — official guidance says mix tags and prose
  freely, and for "purity" of style use at least two full sentences
  describing the subject .
- Quality tags: two competing systems exist — human-scored
  (`masterpiece` … `worst  quality`) or aesthetic-model scored
  (`score_9` … `score_1`). Pick one system, don't mix them .
  Aesthetic variant: omit quality tags entirely, or use only
  "masterpiece, best quality," — avoid `score_*` tags on that variant
  .
- Artist tags: prefix with `@` (e.g. `@artistname`) — without the `@`
  the effect is weak .
- Tag formatting: lowercase, spaces not underscores .
- Two example prompts (Base recipe, tag/prose hybrid per official
  structure):
  1.  "masterpiece, best quality, score<sub>7</sub>, safe, 1girl, solo,
      @wlop, standing on a rain-soaked city street at night, neon
      reflections, holding a red umbrella, detailed folds in a long
      coat, looking back over shoulder"
  2.  "masterpiece, best quality, score<sub>7</sub>, safe, no humans,
      scenery, an old lighthouse on a cliff at dawn, dramatic clouds,
      painterly brushwork, wide shot, muted teal and orange palette"

## Generation modes

| Mode               | Support                 |
|--------------------|-------------------------|
| txt2img            | native             |
| img2img            | community workflow |
| inpaint            | community workflow |
| outpaint           | not documented     |
| instruct-edit      | community LoRA/IC  |
| reference/identity | not documented |

## Edit Modes

- Checkpoint: the base model (Anima Base v1.0) plus a community Edit LoRA trained on before/after
  pairs, e.g. Anima Edit v2.0 (Civitai). Edit quality depends mostly on the LoRA.
- Mechanism: Cosmos-Predict2 reference latent — the VAE latent of the input image conditions the
  generation; the Qwen3 text encoder does not see the image.

| Edit type              | Support    | Refs |
|------------------------|------------|------|
| Instruction edit       | Edit LoRA  | 1    |
| Attribute / color      | Edit LoRA  | 1    |
| Object removal         | Edit LoRA  | 1    |
| Outfit change          | Edit LoRA  | 1    |
| Expression change      | Edit LoRA  | 1    |
| Restyle (split screen) | workaround | 1    |

- References: one image.
- Prompt: quality tags, then the edits as short tag-like phrases, then the LoRA tag. No image
  index syntax.
- Output size: the size of the input image (e.g. 1024x1024), denoise 1.0.
- Settings: 30 steps, CFG 4, er_sde, simple, shift 3, Edit LoRA strength 1.0 (check the LoRA's
  card). Masks are not needed, but help when an edit is ignored.
- Forge Neo (2.27+): Settings › Stable Diffusion › [Anima] Enable Reference
  (`anima_do_reference`, worth adding to the Quicksettings), then generate from the img2img tab
  with the image as input; normal img2img is off while it is enabled. UI preset `anima`.
- Restyle workaround: join a solid-color canvas to the right of the image, mask it and add
  `(split screen, multiple views:1.2)`; it doubles the pixel count.
- Typical failures: large or structural changes do not happen, fingers and small prints break as
  in normal generation, photorealistic inputs edit poorly; reroll the seed before rewording.

Example edit prompts (append the edit LoRA, e.g. `<lora:AnimaEditV2:1>`):

```text
masterpiece, best quality, score_7, black hair, black eyes, <lora:AnimaEditV2:1>
masterpiece, best quality, score_7, delete her cat ears, <lora:AnimaEditV2:1>
masterpiece, best quality, score_7, t-shirt with a cat logo, <lora:AnimaEditV2:1>
masterpiece, best quality, score_7, smile, <lora:AnimaEditV2:1>
```

## ControlNet and Structural Control

Young but usable: three community mechanisms, all trained on Anima-Base v1.0, none from
CircleStone Labs.

- Mechanisms, not interchangeable:
  - ControlNet-LLLite: small LoRA-like conditioning modules (kohya-ss); ComfyUI and Forge Neo.
  - VACE ControlNet: spaced copies of DiT blocks with zero-convs, adapter weights only;
    ComfyUI through forks of ComfyUI-Advanced-ControlNet.
  - Regional LLLite: color-mask regions for placing several characters.
- LLLite, [kohya-ss/Anima-LLLite](https://huggingface.co/kohya-ss/Anima-LLLite), nodes
  [kohya-ss/ComfyUI-Anima-LLLite](https://github.com/kohya-ss/ComfyUI-Anima-LLLite) (keep it
  updated):
  - `anima-lllite-any-test-like-v2`: general control from lineart, scribble (HED, PiDiNet) or
    grayscale images; the most useful one.
  - `anima-lllite-inpainting-v2`: masked inpaint (RGB with the masked area black, plus the
    mask); shifts colors without a mask, so use it in img2img with a mask.
  - Preview3 lineart, depth, pose and fake scribble (listed in `PREVIEW3.md`): not retrained,
    they load on v1.0 with lower quality.
- Tile & Repair LLLite (L_A_X, [Civitai](https://civitai.com/models/2708551),
  `anima_tile_taskplus_v2`, 90 MB): upscaling detail, artifact and blurry-lineart repair while
  keeping the composition; multiplier 0.8-1.0; a slight color shift in the ComfyUI node.
- Regional:
  [Sen-sou/Anima-LLLite-Regional-Controlnet](https://huggingface.co/Sen-sou/Anima-LLLite-Regional-Controlnet).
  Solid colors on a white background mark the regions; it cannot tell which prompt belongs to
  which color, so the prompt still places subjects (left, right, foreground). Pair it with Forge
  Couple or Attention Couple using the same colors; end around 0.45.
- VACE depth: [TaihoC/Anima-ControlNet-VACE-Depth](https://huggingface.co/TaihoC/Anima-ControlNet-VACE-Depth),
  20k steps at 1024², DepthAnything V2 maps work best; nodes
  [TaihoC/ComfyUI-Advanced-ControlNet-Anima](https://github.com/TaihoC/ComfyUI-Advanced-ControlNet-Anima/tree/feat/anima-vace-controlnet)
  (branch `feat/anima-vace-controlnet`).
- VACE canny: [khanghy1000/Anima-ControlNet-VACE-Canny](https://huggingface.co/khanghy1000/Anima-ControlNet-VACE-Canny),
  4 control blocks (at DiT blocks 0, 7, 14, 21), 3k steps, `cv2.Canny` 100/200 maps; use the
  `fix/anima-vace-hardening` branch of PineCookie/ComfyUI-Advanced-ControlNet, since the TaihoC
  fork applies the control hook twice.
- Strength: no card gives values; start at 1.0 and lower it when the control image's lines or
  flat depth show through or the style stiffens.
- Forge Neo: the built-in ControlNet loads the Anima LLLite models and the Regional model (its
  Region mode draws the color masks); the VACE ControlNets are ComfyUI only.
- License: all of them follow the CircleStone Labs Non-Commercial License.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
