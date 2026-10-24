# Fibo 2.0 Reference

## Overview

- **Model:** Bria AI, 2026-10; successor of FIBO (2025-11), trained only on licensed data with long structured (VGL) captions
- **Backbone:** single-stream DiT, 44 blocks, 8B; flow matching
- **Text:** Qwen3-VL-4B; a Perceiver resampler compresses its output into 256-512 gist tokens prepended to the image tokens, and VLM layers feed 5 blocks by cross-attention
- **Latent:** FLUX.2 VAE, 32 ch, 8x, 2x2 patches → multiples of 16
- **Strengths:** structured JSON prompts with per-object control, editing up to 4 references in the same weights

## Encoder/VAE

- Repos: HF [briaai/Fibo-2.0-dev](https://huggingface.co/briaai/Fibo-2.0-dev), [briaai/Fibo-2.0-edit-turbo](https://huggingface.co/briaai/Fibo-2.0-edit-turbo) · ComfyUI [Comfy-Org/Fibo-2.0](https://huggingface.co/Comfy-Org/Fibo-2.0)
- Text encoder: `qwen3vl_4b_bf16.safetensors` or `qwen3vl_4b_int8_convrot.safetensors` (Qwen3-VL-4B-Instruct), Load CLIP type `fibo2`. Use the bf16 file for edits (see Quirks).
- VAE: `flux2-vae.safetensors` (FLUX.2 VAE).

## Recommended Defaults (Dev, text-to-image)

```text
model:      fibo2_dev_int8_convrot.safetensors   (bf16 if you have the RAM/VRAM headroom)
encoder:    qwen3vl_4b_bf16.safetensors, Load CLIP type fibo2 -> TextEncodeFibo2
steps:      50   (30 = ComfyUI default recipe, faster)
cfg:        5.0  true CFG; KSampler cfg = 5.0
sampler:    euler
scheduler:  simple
shift:      none exposed; schedule is resolution-dependent inside the model [?]
resolution: ~1 MP, multiples of 16 (1024x1024, 1424x800, 1248x832)
negative:   NEGATIVE_T2I JSON from the Dev model card (empty also works, slightly softer)
denoise:    1.0
extras:     strings to render go in the "text_render" field of a VGL JSON prompt
```

## Recommended Defaults (Edit Turbo, editing)

```text
model:      fibo2_edit_turbo_int8_convrot.safetensors
encoder:    qwen3vl_4b_bf16.safetensors (int8 encoder can error on image input)
inputs:     TextEncodeFibo2 <- vae + images (source first, up to 4 total)
steps:      4
cfg:        1.0  distilled, guidance-free; KSampler cfg must be 1.0
sampler:    euler
scheduler:  simple
resolution: width/height 0 = derived from the input image; else ~1 MP, multiples of 16
negative:   ignored (no negative pass at cfg 1)
denoise:    1.0
```

## Recommended Defaults (Dev, editing)

```text
model:      fibo2_dev_int8_convrot.safetensors
encoder:    qwen3vl_4b_bf16.safetensors
inputs:     TextEncodeFibo2 <- vae + images (up to 4)
steps:      50  (30 works)
cfg:        5.0  true CFG; KSampler cfg = 5.0
sampler:    euler
scheduler:  simple
negative:   empty (= the trained null caption, NEGATIVE_EDIT)
denoise:    1.0
```

## Variants

| Variant                 | What it is           | License  | Size          | Pick when          |
|-------------------------|----------------------|----------|---------------|--------------------|
| Dev bf16                | non-distilled base   | CC BY-NC | 16.45 GB      | best t2i, LoRAs    |
| Dev int8 ConvRot        | Comfy-Org int8 quant | CC BY-NC | 8.41 GB       | 3090 default       |
| Edit Turbo bf16         | 4-step distilled     | CC BY-NC | 16.45 GB      | fast edits         |
| Edit Turbo int8 ConvRot | Comfy-Org int8 quant | CC BY-NC | 8.4 GB        | fast edits on 3090 |
| Turbo GGUF Q8/Q6/Q4_K_M | community quant      | CC BY-NC | 9.4/7.5/6.2GB | low VRAM           |
| Dev / Turbo NVFP4       | community quant      | CC BY-NC | 7.27/6.41 GB  | RTX 50 only        |

- Commercial use is not allowed: CC BY-NC 4.0, commercial use needs a separate Bria agreement. Bria's HF repos are gated (form); the Comfy-Org repack downloads without the gate.
- Dev and Edit Turbo share the architecture (8B single-stream DiT, 44 blocks, Perceiver "gist" tokens, FLUX.2 VAE latent). Dev does both generation and editing in one set of weights.
- Edit Turbo is step- and guidance-distilled from Dev: 4 steps, CFG 1, negative prompt has no effect, not meant for fine-tuning. Bria positions it as edit-only, but it also renders text-to-image when given no input image (community-verified).
- No LoRA is required by any variant. LoRAs and fine-tunes target Dev (Bria ships a single-GPU LoRA trainer in the Dev repo). Announced but not shipped: multi-turn editing LoRA, product-shot LoRA, background removal, eraser-by-mask, image expansion.
- GGUF quants: `vantagewithai/Fibo-2.0-Dev-and-Edit-Turbo-ComfyUI-GGUF`, loaded with ComfyUI-GGUF. NVFP4 builds only run fast on Blackwell; on a 3090 they dequantize and are slow, so use int8.

## Resolution

- Native training area: about 1 megapixel; width and height must be multiples of 16.
- Known-good sizes:

| Ratio  | Pixels    |
|--------|-----------|
| 1:1    | 1024x1024 |
| 16:9   | 1424x800  |
| 9:16   | 800x1424  |
| 3:2    | 1248x832  |
| 2:3    | 832x1248  |
| 9:7    | 1152x896  |

- Bria's API exposes 21 aspect ratios at ~1 MP [?]; the exact bucket list is not published on the model card.
- Practical max: 1920x1088 (~2 MP) renders cleanly in community tests; larger is untested. Practical min: stay near 1 MP; well below it composition and text quality drop [?].
- TextEncodeFibo2 rounds non-zero width/height to multiples of 16; 0 means "use the default / input-image size".

## Parameters

| Setting   | Dev                       | Edit Turbo   |
|-----------|---------------------------|--------------|
| Steps     | 50 (30 fast)              | 4            |
| CFG       | 5.0, true CFG             | 1.0, off     |
| Sampler   | euler                     | euler        |
| Scheduler | simple                    | simple       |
| Shift     | none exposed [?]          | none exposed |
| Negative  | NEGATIVE_T2I / empty      | ignored      |

- Edit Turbo as text-to-image: same graph as Dev t2i with the Turbo file, leave TextEncodeFibo2's image and VAE inputs empty, 4 steps, cfg 1.0, euler/simple, ~1 MP.
- Dev at Turbo settings (cfg 1, 4-8 steps) produces broken, unfinished-looking images; Dev needs real CFG and many steps.
- Edit Turbo at cfg > 1 doubles compute and departs from its distillation target (expect over-contrast/burn) [?].
- Style negatives: Bria's optional photographic styles (Kodak Film, Hazy/Dreamy, Hard Flash) each ship their own negative; NEGATIVE_T2I treats blur, haze and flare as defects and erases those looks.
- In ComfyUI an empty negative is encoded as the trained null caption. Pasting NEGATIVE_T2I may currently lose its empty fields until a fix lands (ComfyUI issue 17284) [?].

## Prompting

- Two prompt kinds: VGL structured JSON (trained format, most control) or plain natural-language sentences/paragraphs (also trained, works well). No booru tags.
- VGL top-level fields: `short_description`, `objects` (list, each with `description` and attribute fields), `background_setting`, `lighting`, `aesthetics`, `photographic_characteristics` (e.g. `depth_of_field`, `focus`, `camera_angle`), `style_medium`, `context`, `artistic_style`, `text_render`.
- Structure that works: one `objects` entry per person/animal/item; camera, background and lighting consistent with each other; every string you want visible goes in `text_render` with `text`, `location`, `font`.
- Training captions run to 1,000+ words. The Perceiver compresses the prompt into 256-512 gist tokens (more for longer prompts), so long captions are expected rather than truncated; behavior beyond that budget is not documented.
- Write captions with an LLM: Bria's `bria-vgl` (`create()` / `modify()`, runs on Gemini) or any VLM expanding a short idea into VGL; paste the JSON into TextEncodeFibo2.
- `(word:1.2)` weighting is not part of the training format; do not rely on it. Emphasis goes into explicit field values instead.
- Negative prompts work on Dev (true CFG); ignored on Edit Turbo.
- No quality/trigger tokens. Text rendering is strong: each `text_render` string is also drawn as a small image and shown to the encoder. ComfyUI needs Pillow 10.1+ for this.
- Plain prompts miscount groups (asking for four people can yield six); VGL with one object per person fixes it. Words like "clean, simple shapes" make an auto-written caption strip all detail.

Plain prompt:

```text
"Close-up product photo of a ceramic coffee mug on a weathered oak table, steam rising, soft window light from the left, shallow depth of field, the mug printed with the words MORNING RITUAL in bold black serif letters"
```

VGL prompt:

```text
{"short_description": "A bakery storefront at dawn with a hand-painted sign above the door and one woman carrying a bread basket.",
 "objects": [
  {"description": "a woman in her thirties in a flour-dusted apron, holding a wicker basket of baguettes, walking toward the door"},
  {"description": "a wooden bakery door painted dark green, brass handle, glass panel with condensation"}],
 "background_setting": "a narrow cobblestone street, closed shutters on neighbouring shops, empty sidewalk",
 "lighting": {"conditions": "soft dawn light with warm interior glow", "direction": "from the left"},
 "photographic_characteristics": {"camera_angle": "eye level", "depth_of_field": "moderate", "focus": "sharp on the woman and the sign"},
 "style_medium": "photograph",
 "text_render": [{"text": "FRESH BREAD", "location": "top-center", "font": "hand-painted serif"}]}
```

## Generation Modes

| Mode               | Support                          |
|--------------------|----------------------------------|
| txt2img            | native (Dev; Turbo also works)   |
| img2img            | use instruct-edit instead        |
| inpaint            | native mask; custom node pack    |
| outpaint           | not supported (announced)        |
| instruct-edit      | native (Dev and Edit Turbo)      |
| reference/identity | native, up to 4 images           |
| background removal | not supported (announced)        |
| Inspire            | VLM writes prompt from a ref     |

- Edits always run at denoise 1.0 from the latent TextEncodeFibo2 creates; there is no documented partial-denoise img2img recipe.
- Masked edit (white = regenerate) is native in the Bria pipeline. The core TextEncodeFibo2 node has no mask input [?]; masks work through the custom pack `drphero/ComfyUI-Fibo2` (Edit Turbo, masks, multi-reference). Do not mix its nodes with core Load CLIP.

## Edit Modes

- Which checkpoint edits: both Dev (same weights as t2i) and the separate Edit Turbo checkpoint. No adapter needed.
- Mechanism: reference images go to the Qwen3-VL encoder and are also VAE-encoded; the clean reference latents are appended to the token sequence on their own RoPE planes next to the noisy latent.

| Edit type                   | Support            | Refs |
|-----------------------------|--------------------|------|
| instruction edit            | native             | 1    |
| multi-reference composition | native             | 2-4  |
| virtual try-on              | native             | 2    |
| style / appearance transfer | native             | 2-4  |
| subject/identity reference  | native             | 1-4  |
| text editing                | native             | 1    |
| relighting / time of day    | native             | 1    |
| background swap             | native             | 1    |
| inpaint by instruction      | mask, custom nodes | 1    |

- Number of references: official max 4 (source plus up to three references). In ComfyUI combine several images with Batch Images into TextEncodeFibo2's image input [?]. Each reference adds roughly a full image's worth of tokens, so time and VRAM grow with every extra reference.
- Addressing: `<image_1>`, `<image_2>`, ... in input order; "image 1" style wording is also understood [?].
- Output size: TextEncodeFibo2 width/height 0 takes the size from the (first) input image, snapped to ~1 MP and multiples of 16 [?]; set explicit width/height to change aspect. References are thumbnailed for the VLM internally.
- Settings vs txt2img: Dev keeps 50 steps / cfg 5 but uses the empty negative (null caption); Turbo 4 steps / cfg 1; denoise stays 1.0.
- ComfyUI nodes: Load Diffusion Model, Load CLIP (`fibo2`), Load VAE, TextEncodeFibo2 (prompt, negative_prompt, optional vae, optional images; outputs positive, negative, latent), KSampler, VAE Decode. Requires ComfyUI master after 21 Oct 2026 (PR 17240); v0.42.3 and older lack the node. Forge Neo: not supported [?].
- Failures: vague instructions restyle the whole image; multi-ref identities blend when references are not named. Name what changes and what stays ("keep the face, pose and background unchanged").
- Example edit prompts:
  - Instruction edit: `"Replace the jacket with a red leather jacket, keep the person, pose and background unchanged"`
  - Multi-reference: `"Dress the person in <image_1> in the dress from <image_2>"`
  - Product integration: `"Place the bottle from <image_2> on the kitchen counter in <image_1>, matching the scene's lighting"`
  - Text edit: `"Change the shop sign text to 'OPEN LATE', same font and colors"`
  - Relighting: `"Change the time of day to sunset with warm low light from the right, keep everything else unchanged"`
  - Background swap: `"Replace the background with a snowy mountain valley, keep the subject and its lighting unchanged"`

## Quirks and Failure Modes

- "TextEncodeFibo2 missing" / model not detected: ComfyUI older than the 21 Oct 2026 master build. Update to latest GitHub/nightly.
- Edits crash with `NoCapableBackendError ... dequantize_int8_embedding`: int8 Qwen3-VL encoder on the vision path. Use `qwen3vl_4b_bf16.safetensors` for edits (an fp8-scaled encoder also works).
- Mixing the `ComfyUI-Fibo2` custom pack's conditioning node with core Load CLIP fails with "'Image' object is not subscriptable".
- VRAM on a 24 GB card: bf16 Dev peaked at ~27.9 GB whole-GPU at 1024x1024 in a 5090 test (int8: ~21.3 GB), so bf16 offloads on a 3090. With 32 GB system RAM, bf16 diffusion (16.45 GB) plus bf16 encoder is tight; int8 diffusion + bf16 encoder is the sane combination.
- Anatomy is better than FIBO 1 but piano keys, repeated mechanical patterns and crowded scenes still break.
- Auto-written captions (by any VLM) can contradict the request (adding walls to a top-down shot) or delete detail; read and fix the JSON before blaming the model.
- Off-spec sizes (not multiples of 16, far from 1 MP) degrade composition and text; stay near 1 MP.
