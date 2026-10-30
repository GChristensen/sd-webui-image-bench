# Ideogram 4 Reference

## Overview

- **Model:** Ideogram, 2026-06; trained from scratch, first open-weight Ideogram model
- **Backbone:** single-stream DiT, 34 layers, 9.3B; flow matching; dual-branch guidance (separate conditional and unconditional branches)
- **Text:** Qwen3-VL-8B-Instruct, hidden states of 13 intermediate layers concatenated
- **Latent:** FLUX.2 VAE, 32 ch, 8x, 2x2 patches → multiples of 16
- **Strengths:** typography, bounding-box layout and hex palettes from JSON captions (its only training format); up to 2048 px and 6:1

## Encoder/VAE
- Repos: HF [ideogram-ai/ideogram-4-fp8](https://huggingface.co/ideogram-ai/ideogram-4-fp8), [ideogram-ai/ideogram-4-nf4](https://huggingface.co/ideogram-ai/ideogram-4-nf4) · ComfyUI [Comfy-Org/Ideogram-4](https://huggingface.co/Comfy-Org/Ideogram-4)
- Text encoder: `Qwen3-VL-8B-Instruct`
- VAE: `flux2-vae.safetensors`

## Recommended Defaults

``` text
steps             : 48 (V4_QUALITY_48 preset)
guidance          : 7.0 steps 1-45, 3.0 steps 46-48
sampler           : euler
scheduler         : Ideogram4Scheduler (logit-normal, auto mu-shift)
resolution        : 1024x1024 to start; native ceiling ~2048px/side
prompt_format     : structured JSON caption (high_level_description / style_description / compositional_deconstruction)
negative_prompt   : unclear if applicable — don't rely on it
fallback for speed: steps=12, V4_TURBO_12 preset, exact guidance schedule unconfirmed [?]
```

## Resolution

- Native range: 256-2048px per side. Alignment: multiples of 16.
- Aspect ratios flexible, up to 6:1 reported. Example formats seen: 1024x1024, 1536x1024, 2048x768 [?].
- Off-spec behavior (duplication/mush/composition collapse outside this range): not documented anywhere found [?] — no data, don't assume graceful degradation.

## Parameters

Ideogram 4 does not use classic single-value CFG or embedded distilled guidance. It uses **dual-branch/asymmetric guidance**: a second "unconditional" DiT checkpoint runs alongside the main one, and skips text-padding tokens (cheaper compute, not a quality shortcut). Setting guidance to 0 or 1 disables that second transformer outright — a turbo-style single-pass mode trading quality for VRAM/speed. Treating the "guidance weight" field like ordinary CFG will silently misconfigure the run.

| Setting | Value |
|----|----|
| Steps (Turbo) | 12 — `V4_TURBO_12` |
| Steps (Default) | 20 — `V4_DEFAULT_20` |
| Steps (Quality) | 48 — `V4_QUALITY_48` |
| Guidance weight | ~7 main phase, ~3 polish phase |
| Sampler | Euler |
| Scheduler | logit-normal (custom), ComfyUI node `Ideogram4Scheduler` |
| Negative prompt | unclear if applicable [?] |
| Clip skip | n/a, no CLIP encoder |

- Quality-48 runs guidance=7 for steps 1-45, then guidance=3 for the final 3 "polish" steps.
- The unconditional branch has no text input at all, not a "negative text" slot — classic SDXL-style negative prompting may not apply the same way [?].
- Turbo-12's exact guidance schedule is unconfirmed [?] — everything else same as the Quality recipe above, with a lower (unpublished) guidance value.

## Prompting

- Native format: structured JSON captions, the only training format ([official prompting guide](https://github.com/ideogram-oss/ideogram4/blob/main/docs/prompting.md)). Plain-text prompts are officially said not to work and often trigger the safety filter; the reference pipeline turns them into JSON first with an LLM "magic prompt" (`ideogram-4-v1` through the Ideogram API by default, or `claude-opus-v1` / `claude-sonnet-v1` through OpenRouter; the open-source one differs from ideogram.ai's).
- Top-level keys, in this order:
  - `high_level_description`: optional, strongly recommended; a one-to-two-sentence summary.
  - `style_description`: optional object. When present, `aesthetics`, `lighting` and `medium` are required, plus exactly one of `photo` (camera, lens, film; with `medium: "photograph"`) or `art_style` (non-photo work). Key order: photo `aesthetics, lighting, photo, medium, color_palette`; non-photo `aesthetics, lighting, medium, art_style, color_palette`.
  - `compositional_deconstruction`: required object; `background` (a string, first), then `elements`.
- Elements: `{"type": "obj", "bbox", "desc", "color_palette"}` or `{"type": "text", "bbox", "text", "desc", "color_palette"}`, keys in that order; `bbox` and `color_palette` are optional. `text` holds the literal string to render, `desc` its typography (font, weight, size, colour) or the object's description. Order the elements background to foreground.
- Bounding boxes: `[y_min, x_min, y_max, x_max]`, normalized 0-1000, origin at the top left, independent of the resolution; rough values suffice. Give each text block its own non-overlapping box.
- Palettes: uppercase `#RRGGBB` only (no `#fff`); up to 16 colours in `style_description.color_palette`, up to 5 per element. Describing colours only in words works worse.
- Serialization: compact JSON (`separators=(",", ":")`) with literal non-ASCII characters (`ensure_ascii=False`). The pipeline's `CaptionVerifier` checks every prompt and warns on unknown keys, missing required keys and out-of-order keys.
- Token budget: 2048 on the Qwen3-VL encoder; truncation behavior past that isn't documented [?].
- Weighting syntax `(word:1.2)`: no evidence either way; treat as unsupported until verified in your UI.
- Negative prompts: unclear whether/how they function given the dual-branch guidance design — don't assume SDXL-style behavior [?].
- Text rendering: marketed as best-in-class multilingual, but independent reviews report it degrading past ~25-30 rendered words, unreliable on Cyrillic/Arabic/CJK, and fragile diacritics (Polish/Turkish/Vietnamese). Good at 2-3 distinct text regions at different scales in one composition.
- Built-in safety filter is baked into the weights and cannot be disabled from ComfyUI; NSFW prompts return a gray "Image blocked by safety filter" image, and false positives are common for non-JSON prompts.

Two example prompts (shown indented for reading; send them compact):

Graphic design:
```
{
  "high_level_description": "A retro diner poster with a bold headline above a neon coffee cup.",
  "style_description": {
    "aesthetics": "retro, bold, playful",
    "lighting": "flat, even",
    "medium": "graphic_design",
    "art_style": "flat vector illustration, no gradients",
    "color_palette": ["#E8622C", "#1F7A72", "#F4E3C1"]
  },
  "compositional_deconstruction": {
    "background": "A flat cream background with a thin teal border.",
    "elements": [
      {"type": "obj", "bbox": [300, 250, 820, 750], "desc": "A neon-style coffee cup with rising steam lines.", "color_palette": ["#E8622C", "#1F7A72"]},
      {"type": "text", "bbox": [60, 100, 220, 900], "text": "OPEN LATE", "desc": "Huge bold condensed sans-serif headline in orange, centered.", "color_palette": ["#E8622C"]}
    ]
  }
}
```

Photograph:
```
{
  "high_level_description": "A weathered fisherman mending a net on a wooden dock at golden hour.",
  "style_description": {
    "aesthetics": "documentary, warm, quiet",
    "lighting": "low golden-hour sun, warm rim light",
    "photo": "85mm, f/1.8, shallow depth of field, eye level",
    "medium": "photograph"
  },
  "compositional_deconstruction": {
    "background": "A calm harbour with blurred fishing boats.",
    "elements": [
      {"type": "obj", "bbox": [250, 300, 1000, 750], "desc": "An elderly fisherman in a knit sweater, sitting and mending a green net across his knees."}
    ]
  }
}
```

## Generation Modes

| Mode | Support |
|----|----|
| txt2img | native |
| img2img | likely, unofficial [?] — mechanically plausible via a standard denoise pass, no official denoise-range guidance found |
| inpaint | community hack only (SAM2 mask + partial denoise); no dedicated inpaint checkpoint |
| outpaint | community crop+stitch hack, unconfirmed |
| instruct-edit | no evidence found |
| reference/identity | not supported — no IP-Adapter; LoRA training is the identity-transfer route instead |

Ideogram's hosted app has "Canvas/Magic Fill/Extend" inpaint/outpaint tools, but these are the closed API product — don't assume they transfer to the open-weight release [?].

## Quirks and Failure Modes

- Text rendering degrades past ~25-30 rendered words; word boundaries break down first.
- Non-Latin scripts (Cyrillic, Arabic, CJK) render unreliably; diacritics in Polish/Turkish/Vietnamese drop or duplicate.
- Hands are a weak point relative to top photoreal models, worse when interacting with rendered text in the same composition.
- Mixing photorealistic-portrait and graphic-poster style cues in one prompt produces uncanny/doll-like faces.
- Occasionally misses exact counts or ignores requested orientation in complex prompts.
- Baked-in safety filter can block generations with no override in ComfyUI; plain-text prompts trigger it far more often than JSON captions — if generations get refused unexpectedly, that's the likely cause, not a workflow bug.
- Unknown, missing or out-of-order caption keys are only warned about by the reference pipeline's verifier; whether ComfyUI checks captions at all is undocumented, so expect a malformed caption to fail silently [?].
- Guidance-field misuse: setting guidance to 0/1 silently switches to a cheaper single-pass mode rather than "turning CFG off" the way it would on a classic model — don't copy a CFG value from another model's recipe.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
