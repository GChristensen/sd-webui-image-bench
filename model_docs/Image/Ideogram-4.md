# Ideogram 4 Reference

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
prompt_format     : structured JSON (description/style/bbox/palette)
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

- Native format: structured JSON. Ideogram's docs describe the model as trained exclusively on JSON captions — fields include a description, a style block, a compositional breakdown, bounding boxes (normalized 0-1000 coords), and a color palette (up to 16 hex values total, 5 per element).
- Natural-language prompts are also accepted, but given the JSON-only training claim, expect natural language to underperform JSON for precise layout/text/palette control — treat plain prose as a fallback, not the primary interface [?].
- Token budget: 2048 on the Qwen3-VL encoder; truncation behavior past that isn't documented [?].
- Weighting syntax `(word:1.2)`: no evidence either way; treat as unsupported until verified in your UI.
- Negative prompts: unclear whether/how they function given the dual-branch guidance design — don't assume SDXL-style behavior [?].
- Text rendering: marketed as best-in-class multilingual, but independent reviews report it degrading past ~25-30 rendered words, unreliable on Cyrillic/Arabic/CJK, and fragile diacritics (Polish/Turkish/Vietnamese). Good at 2-3 distinct text regions at different scales in one composition.
- Built-in safety filter is baked into the weights and cannot be disabled from ComfyUI; structured JSON prompts reportedly trigger it less often than free-text prompts.

Two example prompts:
1. Natural language: "A weathered fisherman mending a net on a wooden dock at golden hour, photorealistic, shallow depth of field, warm rim light"
2. Structured JSON (illustrative — verify exact key names against the official prompting guide) [?]:
```
{
  "description": "retro diner poster, bold sans-serif headline text",
  "style": "flat vector illustration, warm orange and teal palette, no gradients",
  "palette": ["#E8622C", "#1F7A72", "#F4E3C1"],
  "elements": [
    {"type": "text", "content": "OPEN LATE", "bbox": [100, 60, 900, 220]}
  ]
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
- Baked-in safety filter can block generations with no override in ComfyUI; structured JSON prompts reportedly trigger it less often than free-text — if generations get refused unexpectedly, that's the likely cause, not a workflow bug.
- Guidance-field misuse: setting guidance to 0/1 silently switches to a cheaper single-pass mode rather than "turning CFG off" the way it would on a classic model — don't copy a CFG value from another model's recipe.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
