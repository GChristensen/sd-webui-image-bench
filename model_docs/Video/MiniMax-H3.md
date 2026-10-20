# MiniMax H3 Reference

The full "omni" system has three components, only one of which is open: H3-Context-IR (multimodal input preprocessor, API-only) and H3-Regenerate-2K (in-context upscaling to the marketed "2K" output, API-only) are not released. **H3-Base**, the 33B dense transformer, is what you download and run — locally you are capped at its native 768p output; the "native 2K" marketing claims describe the API pipeline, not the open weights.

## Encoder/VAE
- Repos: HF [MiniMaxAI/MiniMax-H3](https://huggingface.co/MiniMaxAI/MiniMax-H3) · ComfyUI [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3)
- Text encoder: full Qwen3-VL-32B/ Prompt limit: 7,000 characters. Stable support for 11 languages (Arabic, Chinese, English, French, German, Italian, Japanese, Korean, Portuguese, Russian, Spanish).

## Recommended Defaults (FL2VA, base, no Turbo)

``` text
steps         : 50 (or 6-8 with a Turbo LoRA)
cfg           : 1.0 (CFG-distilled, do not raise)
shift (video) : 12.0
shift (audio) : 3.0
resolution    : 768x1344 (native local cap — 2K requires the API's Regenerate-2K stage)
frame_count   : 17n+5, e.g. n=5 -> 90 frames (~3.75s @ 24fps) as a first test
fps           : 24 (fixed)
negative_prompt: unused
```


## Variants

| Variant | What it is | Pick when |
|----|----|----|
| FL2VA | T2V plus first/last-frame I2V, accepts 0-2 input images | text- or frame-driven gen |
| Ref2VA | omni-reference generation from images, video, and/or audio | identity/style consistency |
| Turbo LoRA | community 4-8 step distillation | fast iteration/drafts |

Ref2VA input caps: up to 9 reference images, 3 video clips (2-15s each, ≤15s combined), 3 audio clips, 12 files total combined across types.

## Duration, Frame Count, Resolution, FPS

| Field | Value |
|----|----|
| Native duration | 4-15 seconds |
| FPS | 24, fixed (not a tunable conditioning knob) |
| Frame-count grid | 17n+5 — off-grid requests get snapped, clip may run slightly longer than requested|
| Default resolution | 768 height x 1344 width (short-side 768p), multiple-of-32 |
| Marketed "2K" | only via H3-Regenerate-2K, not open-sourced |
| Aspect ratios | 21:9, 16:9, 4:3, 1:1, 3:4, 9:16 |
| "Extendable to ~30s" | one press writeup, mechanism unspecified [?] |

## Parameters

| Setting | FL2VA / Ref2VA (base) | Turbo LoRA |
|----|----|----|
| Steps | 50 | 4-8 (6-8 recommended) |
| CFG / guidance | 1.0, distilled | 1.0 |
| Flow shift (video) | 12.0 | undocumented [?] |
| Flow shift (audio) | 3.0 | undocumented [?] |

Shift formula (applied independently per stream): `shift*sigma / (1 + (shift-1)*sigma)`. Negative prompt not supported — the model is CFG-distilled. Turbo LoRA at 4 steps removes most motion artifacts on small/static shots but struggles with large fast motion; 6-8 steps closes that gap.


## Prompting

- No negative-prompt field: the model is CFG-distilled, so exclusions are expressed as plain-English positive/constraint sentences instead (e.g. "the subject stays the same size in frame throughout" rather than "no zoom").
- Official prompt formula: reference material notes + core idea + scene-by-scene description. Prompt length cap: 7,000 characters.
- Camera vocabulary reported respected: push, pull, pan, truck, tilt, tracking, arc, static, camera shake, POV, roll — describe range and speed of the move, not just the verb, per MiniMax's own guidance.
- No official prompt-rewriter/extender confirmed as part of the open-weight pipeline (H3-Context-IR, which might do this, is API-only).
- "Then"-style temporal sequencing is supported via the scene-by-scene description structure, consistent with multi-shot support — no data on how many sequential beats it reliably tracks in one clip [?].

Two example prompts at the length the official docs favor:
1. "A weathered fisherman on a wooden dock at golden hour, mending a net with slow deliberate hand movements. Camera: slow push-in, medium speed, staying at eye level. Lighting: warm rim light from low sun, soft haze. Audio: creaking wood, distant gulls, quiet water lapping."
2. "A girl is very happy, she is speaking in English: 'I enjoy working with this framework, it's perfect.'" (official example — shows the dialogue-in-prompt pattern for lip-synced speech)

## Generation Modes

| Mode | Support |
|----|----|
| text-to-video | native (FL2VA) |
| image-to-video (first frame) | native (FL2VA, 1 image) |
| first-and-last-frame | native (FL2VA, 2 images) |
| video-to-video | Fun ControlNet Union (control video), or Ref2VA's reference-video input |
| video extension/continuation | no dedicated node confirmed; Ref2VA's ref-video input may serve this role, unverified [?] |
| video inpaint/outpaint | inpaint through the Fun ControlNet Union mask input |
| instruction-based editing | mentioned in press coverage; unclear whether it needs the API-only H3-Context-IR stage [?] |
| reference-driven generation | native (Ref2VA) — up to 9 images, 3 video clips, 3 audio clips, 12 files max combined |
| multi-shot in one call | native, stated capability; no data on shot-count limits [?] |

No denoise-range or i2v-conditioning-strength numbers found — H3's conditioning appears to go through the omni-context encoder rather than a simple strength scalar.

## Edit Modes

- Checkpoint: the separate H3-Base-Ref2VA (`minimax_h3_ref2va_*`), not the FL2VA model.
- Mechanism: images, videos and audio enter as in-context reference tokens, addressed by tags
  in the prompt; the output is video with audio.

| Edit type                      | Support | Refs    |
|--------------------------------|---------|---------|
| Subject / identity reference   | native  | ≤ 9 img |
| Video edit (re-animate, redub) | native  | ≤ 3 vid |
| Voice timbre reference         | native  | ≤ 3 aud |
| Music reuse                    | native  | ≤ 3 aud |
| Mixed references               | native  | ≤ 12    |

- References: up to 9 images, 3 videos and 3 audio clips (each clip 2-15 s, at most 15 s per
  kind), 12 files in total. The order of the chained reference nodes sets the numbering.
- Prompt: tags `<Subject 1>`, `<Video 1>`, `<Audio 1>`; dialogue as `<d>[English] ...</d>`. The
  official structured prompt comes from H3-Context-IR (API only), so locally write it by hand.
- Output: 4-15 s, 24 fps, short side 768, adaptive aspect ratio, 32 kHz stereo.
- Settings: 20 steps (25 for better motion); turbo LoRA 8 steps. Load both the video and the
  audio VAE, or the output is silent.
- ComfyUI: the official `video_minimax_h3_r2v` template with the MiniMax H3 node.
- Typical failures: reordered references swap roles, many references at once fail without a
  clear cause; start with one character image and one simple action, then add references.

Example prompts:

- "`<Subject 1>` walks along the beach at sunset, the camera tracks beside her"
- "In `<Video 1>`, `<Subject 1>` turns to the camera and says
  `<d>[English] Follow the wind, live free.</d>`, framing and setting unchanged"
- "`<Audio 2>` is the voice timbre reference for `<Subject 1>`'s voice"
- "`<Audio 1>` plays as the background music"


## Structural and Reference Control

New but native: one Fun ControlNet Union from Alibaba PAI, in ComfyUI since 0.35.0.

- Model: [alibaba-pai/MiniMax-H3-Fun-Controlnet-Union](https://huggingface.co/alibaba-pai/MiniMax-H3-Fun-Controlnet-Union)
  (~6.8 GB, control branch only: blocks at 0, 10, 20, 30, 40 of 50); the ComfyUI patch ships in
  [Comfy-Org/MiniMax-H3](https://huggingface.co/Comfy-Org/MiniMax-H3) (`models/model_patches/`).
- Control signals: canny, depth, HED, MLSD and pose control videos, plus masked video inpaint.
  No camera trajectory input; camera moves follow the control video or the prompt.
- ComfyUI: Apply MiniMax H3 Fun ControlNet (MiniMaxH3FunControlNetApply), template "MiniMax H3
  Fun ControlNet Union"; the example extracts the skeleton with SDPose, or a preprocessed
  control video goes straight into `control_video`. It works with the FL2VA and Ref2VA
  transformers. Community extras:
  [wyzborrero/ComfyUI-H3-FunControl](https://github.com/wyzborrero/ComfyUI-H3-FunControl).
- Strength (`control_context_scale`): 1.0 strongest, 0.0 off. Chained controls add up, so treat
  strength as a budget: depth 0.3 + pose 0.7 works, 1.0 + 1.0 washes out and smears the figure,
  above 1.0 degrades.
- End around 0.6 locks motion and layout early and lets the last steps add texture.
- Guidance stays 1.0 (guidance-distilled); the inpaint mask input stays 0 when not inpainting.
- Timing: control video fitted to the 17n+5 frame grid at 24 fps, 5-15 s; a longer control
  video is cut, a shorter one holds its last frame.
- Quirks: apply BlockSparseAttention before the ControlNet node, or the control is erased; a
  small subject in frame limits accuracy; depth alone pulls the figure toward the camera.
- VRAM: the branch adds ~7 GB to a 33B transformer, so offload or quantized files on a 3090.

## Audio

- Generation is native, same pass as video — not a separate stage.
- Channels/sample rate: stereo, 32kHz.
- Content types: speech, effects, ambience confirmed; music not explicitly confirmed [?].
- Prompting: described inline in the same prompt, e.g. dialogue in quotes.
- Lip-sync: supported via the dialogue-in-prompt pattern.
- Audio as driving input: supported, via Ref2VA's up-to-3 audio-clip reference.
- Disabling audio to save VRAM/time: not confirmed either way [?]. The audio VAE is a small separate component (0.56GB fp32) so disabling it should in principle be cheap if the pipeline supports a video-only path, but no official toggle is documented.

## Length Extension and Continuity

No dedicated sliding-window, position-extrapolation, or autoregressive-chaining mechanism documented. "Extendable to ~30s" (one press piece) most likely means first-last-frame chaining of multiple 15s clips, not a native extended-context mode — inference, not a sourced fact [?]. Given Ref2VA's reference-video input, the most plausible continuity method today is: generate segment 1 → feed its final frames back in as Ref2VA reference video for segment 2 → repeat. Unverified as an official recommendation.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
