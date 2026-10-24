# Ernie-Image Reference

## Overview

- **Model:** Baidu, 2026-04; trained in-house, Turbo distilled from the SFT base with DMD + RL
- **Backbone:** single-stream DiT, 8B; flow matching [?]
- **Text:** Ministral 3 3B (LLM) in the joint token sequence [?]; optional 3B prompt enhancer of the same family
- **Latent:** FLUX.2 VAE, 32 ch, 8x, 2x2 patches → multiples of 16
- **Strengths:** dense, layout-sensitive text in Chinese and English (posters, comics, infographics) under an Apache-2.0 license

## Encoder/VAE

- Repos: HF [baidu/ERNIE-Image](https://huggingface.co/baidu/ERNIE-Image) · HF [baidu/ERNIE-Image-Turbo](https://huggingface.co/baidu/ERNIE-Image-Turbo) · ComfyUI [Comfy-Org/ERNIE-Image](https://huggingface.co/Comfy-Org/ERNIE-Image) (one repo holds both variants)
- Text encoder: `ministral-3-3b.safetensors` (7.19 GB) → `models/text_encoders/`, CLIPLoader type `flux2`
- Prompt Enhancer (optional, 3B, Ministral-3-3B fine-tune): `ernie-image-prompt-enhancer.safetensors` (6.41 GB) → `models/text_encoders/`
- VAE: `flux2-vae.safetensors` (320.6 MB) → `models/vae/`

## Recommended Defaults (Turbo)

```text
model:            ernie-image-turbo.safetensors
steps:            8
cfg:              1.0  (true CFG off; distilled, KSampler cfg must stay 1.0)
sampler:          euler
scheduler:        simple
shift:            template default, no ModelSampling node [?]
resolution:       1024x1024 or one of the 7 official buckets
negative prompt:  none (ConditioningZeroOut; ignored at cfg 1)
latent node:      EmptyFlux2LatentImage
prompt enhancer:  off for literal text, on for short/vague prompts
```

## Recommended Defaults (Base)

```text
model:            ernie-image.safetensors
steps:            50  (20 is visibly undercooked)
cfg:              4.0  (true CFG, set on KSampler; useful range 3-5)
sampler:          euler
scheduler:        simple  (sgm_uniform also fine)
shift:            template default, no ModelSampling node [?]
resolution:       1024x1024 or one of the 7 official buckets
negative prompt:  empty, or short quality terms ("blurry, low resolution")
latent node:      EmptyFlux2LatentImage
prompt enhancer:  same rule as Turbo
```

## Recommended Defaults (Base + Distill LoRA)

```text
model:            ernie-image.safetensors
lora:             community ERNIE distill/turbo LoRA, strength 0.8-1.0 [?]
steps:            8
cfg:              1.0
sampler:          euler
scheduler:        simple
negative prompt:  none
```

Community reports favor this over the official Turbo for cleaner color; keep strength at 1.0 when the image contains text.

## Variants

| Variant             | What it is          | License    | Size       | Pick when          |
|---------------------|---------------------|------------|------------|--------------------|
| ERNIE-Image         | SFT base            | Apache-2.0 | ~15 GB [?] | quality, negatives |
| ERNIE-Image-Turbo   | DMD + RL distilled  | Apache-2.0 | 14.96 GB   | speed, iteration   |
| Unsloth GGUF        | community quant     | Apache-2.0 | varies     | low VRAM / RAM     |
| Ernie-Image-Flex-V1 | community fine-tune | Apache-2.0 | ~15 GB [?] | cleaner Turbo look |

- Turbo is distilled with DMD (distribution matching) plus RL for aesthetics: fixed few-step schedule, CFG baked out, negatives have no effect.
- Both variants are 8B single-stream DiT; LoRAs trained on base load on Turbo and vice versa.
- Commercial use is allowed (Apache-2.0 for weights and code).
- `baidu/ERNIE-Image-Aes` in the same collection is an 8B aesthetics scorer (VLM), not a generator.
- GGUF repos: [unsloth/ERNIE-Image-GGUF](https://huggingface.co/unsloth/ERNIE-Image-GGUF), [unsloth/ERNIE-Image-Turbo-GGUF](https://huggingface.co/unsloth/ERNIE-Image-Turbo-GGUF) (need ComfyUI-GGUF).
- Flex-V1 ([wikeeyang/Ernie-Image-Flex-V1](https://huggingface.co/wikeeyang/Ernie-Image-Flex-V1)) is a base fine-tune run at cfg 1.0, 16-25 steps, or 8 steps with a Turbo LoRA.
- RTX 3090 + 32 GB RAM: bf16 DiT + text encoder + PE is ~29 GB of weights and will swap system RAM. Use an fp8 or Q8 GGUF DiT, and either skip the PE or unload it after use.

## Resolution

- Native training resolution: ~1 MP (1024² class).
- Official buckets (identical for base and Turbo):

| Ratio | Pixels    |
|-------|-----------|
| 1:1   | 1024x1024 |
| 2:3   | 848x1264  |
| 3:2   | 1264x848  |
| 9:16  | 768x1376  |
| 16:9  | 1376x768  |
| 3:4   | 896x1200  |
| 4:3   | 1200x896  |

- Required multiple: 16 [?] (FLUX.2 VAE 8x downscale plus 2x2 patching); all official buckets satisfy it.
- Practical range: ~0.6-1.3 MP [?]. The longest official edge is 1376 px; nothing official covers larger sizes.
- Off-spec large sizes risk duplicated subjects and broken layouts; text layouts and multi-panel grids are the first to fall apart. Stay on a bucket and upscale afterwards.
- The PE receives the target width/height and writes composition for that aspect ratio, so set the size before enhancing.

## Parameters

| Setting   | Base          | Turbo         | Base + Distill LoRA |
|-----------|---------------|---------------|---------------------|
| steps     | 50            | 8             | 8                   |
| CFG       | 4.0 (true)    | 1.0           | 1.0                 |
| sampler   | euler         | euler         | euler               |
| scheduler | simple        | simple        | simple              |
| shift     | default [?]   | default [?]   | default [?]         |
| negative  | works         | ignored       | ignored             |

- Turbo with cfg > 1: oversaturated, burned output and doubled step time; there is no benefit.
- Base with cfg 1: prompt is barely followed and the image goes flat.
- Base under ~30 steps: soft, under-resolved detail and garbled small text.
- Wrong latent: use `EmptyFlux2LatentImage` (128-channel FLUX.2 latent layout [?]); an SD/Flux.1 latent node can produce noise or errors on older ComfyUI builds.
- Some community workflows use `res_multistep` for Turbo; euler/simple is the official template pairing.

## Prompting

- Natural language, long and descriptive. Chinese and English are first-class; Japanese works but prompt adherence drops. Booru tags are not the training format.
- Structure that works: medium/style → main subject and action → setting → layout (positions, panels, grid) → exact text in quotes with font/color/placement → lighting and palette.
- Put every string to render in quotes ('...' or "..."); name position ("top center title", "bottom-right caption").
- Text rendering is the headline strength: dense paragraphs, posters, infographics, UI mockups, bilingual EN/ZH. Long CJK strings in grids still get occasional character swaps.
- Prompt Enhancer: rewrites the prompt into a long structured description (template max_length 1536-2048, temperature 0.6, top_p 0.8). It helps short prompts and reasoning-heavy scenes but can rewrite your literal text and lower attribute binding; turn it off for exact copy and already-detailed prompts. A larger external LLM can replace it.
- Token budget: no hard limit documented for the Ministral encoder [?]; official example prompts run to several hundred words without truncation issues.
- `(word:1.2)` weighting: not meaningful with an LLM encoder [?]; restate emphasis in words instead.
- Negative prompts: active only on base (true CFG). Short quality terms are enough; long SD-style lists add nothing.
- No trigger or quality tokens are required. "8K, masterpiece" style padding is tolerated but unnecessary.

Example 1 (poster with text):

```text
A vertical travel poster in flat mid-century illustration style. At the top center, a bold cream serif title reads "LAKE BAIKAL", with a smaller line below it reading "Winter Expedition 2026". The middle shows a lone red ice-fishing tent on clear turquoise ice with cracks glowing blue, snowy mountains on the horizon under a pale pink sky. At the bottom, a dark blue banner contains white sans-serif text "Feb 10 - Mar 5 · Irkutsk". Limited palette of turquoise, cream, red and navy, clean shapes, subtle paper grain.
```

Example 2 (photograph):

```text
A candid street photograph at dusk in a narrow old-town lane after rain. An elderly man in a grey wool coat sits on a wooden stool outside a small repair shop, fixing a bicycle wheel. Above the door hangs a hand-painted yellow sign with red characters "修车" and the English word "REPAIR" underneath. Wet cobblestones reflect warm tungsten light from the shop window, cool blue ambient light in the background, shallow depth of field, 35mm lens, natural skin texture, fine film grain.
```

## Generation Modes

| Mode               | Support                      |
|--------------------|------------------------------|
| txt2img            | native                       |
| img2img            | community workflow (generic) |
| inpaint            | community workflow (generic) |
| outpaint           | community workflow (generic) |
| instruct-edit      | not supported                |
| reference/identity | LoRA only                    |

- img2img: VAEEncode with the FLUX.2 VAE into a normal KSampler; denoise 0.4-0.7 for restyle, 0.2-0.35 for cleanup [?]. Turbo's 8-step schedule leaves few effective steps at low denoise; raise steps to 12-16 with Turbo when denoise is below 0.5 [?].
- Inpaint: no dedicated inpaint checkpoint or adapter; use SetLatentNoiseMask or InpaintModelConditioning with denoise ~0.6-0.9 [?] and composite back.
- Forge Neo supports `ernie-image` and `ernie-image-turbo` for txt2img; img2img/inpaint go through its generic tabs.
- LoRA training: ai-toolkit (ostris) and DiffSynth-Studio support ERNIE-Image; a 10-image face LoRA works on both variants.

## Quirks and Failure Modes

- Turbo look: oily/glossy skin, heavy noise and a yellowish cast are commonly reported; base, base + Distill LoRA, or Flex-V1 are the usual fixes.
- Turbo seed diversity is low: different seeds give near-identical compositions (e.g. "Japanese woman" → kimono every time). Vary the prompt or use base.
- Japanese text: occasional wrong or substituted words in dense sticker/grid layouts; Chinese and English are more reliable.
- Adding a character LoRA, or a Distill LoRA below 1.0, degrades text rendering.
- PE silently changes your prompt; if output ignores a detail you wrote, check whether the PE dropped it.
- PE off scores higher on GenEval attribute binding; PE on scores higher on reasoning and long text.
- Base at 20 steps (some generic workflows) looks broken; it needs ~50.
- "CLIP loader error": ComfyUI older than v0.19.1, or CLIPLoader type not set to `flux2`; restart after updating.
- Wrong VAE: a FLUX.1 / SD3 16-channel VAE gives a tensor-shape error or garbage; only the FLUX.2 VAE fits.
- Missing download: `ministral-3-3b.safetensors` is required even with the PE disabled; the PE file is optional.
- 24 GB VRAM is the official floor for bf16; on a 3090, OOM or heavy slowdown usually comes from the PE and DiT loaded together, not the DiT alone.
- No ControlNet, edit model or regional-prompting support exists from Baidu; third-party "ERNIE ControlNet" guides mostly point at models built for other architectures.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*