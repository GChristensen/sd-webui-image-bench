# WAN 2.2 Reference

## Encoder/VAE

- Repos: HF [Wan-AI/Wan2.2-T2V-A14B](https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B), [Wan-AI/Wan2.2-I2V-A14B](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B), [Wan-AI/Wan2.2-TI2V-5B](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B) · ComfyUI [Comfy-Org/Wan_2.2_ComfyUI_Repackaged](https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged)
- Video VAE — two different VAEs in this family, easy to mix up:
  - T2V-A14B / I2V-A14B use the **Wan2.1** VAE, `wan_2.1_vae.safetensors`. Causal, temporal compression 4x, spatial 8x8, 16 latent channels.
  - TI2V-5B uses the new **Wan2.2-VAE**, `wan2.2_vae.safetensors`. Causal, temporal compression 4x, spatial 16x16 (double the 2.1 VAE), 16 latent channels. Combined with the DiT's 2x2 patchify, total effective compression reaches 4x32x32 = 4096x — this is what lets the 5B dense model handle 720p without an oversized latent grid, at the cost of coarser per-token spatial detail.
  - A causal VAE compresses in blocks of 4 frames anchored on frame 0, so valid pixel-space frame counts satisfy 4n+1 (see Resolution).
  - Tiled decode: ComfyUI exposes a "Tiled VAE Decode" node for Wan, commonly needed at 720p/81-frame length to avoid OOM.
- Text encoder: umT5-XXL (encoder-only). Token limit not confirmed by any source [?]; community pipelines commonly cap around 512 tokens. Trained on ~100 languages, but Wan's own training data skews English/Chinese — expect stronger adherence in those two.
- Audio encoder: Wav2Vec, used only by S2V-14B to read driving audio (speech rhythm/tone/phonemes) — this is audio-conditioned video, not audio output.

## Recommended Defaults (TI2V-5B)

``` text
Resolution: 1280x704
Frames:     121  (4n+1, ~5s @ 24fps)
Sampler:    unipc
Steps:      40
CFG:        4.5
Shift:      3   (raise toward 5 for more motion)
Negative:   <default negative prompt, see Prompting>
```

This is a synthesized starting point, not an official recommended-defaults block — confirm shift/CFG against `generate.py`'s actual TI2V-5B defaults before treating it as tuned. 

## Variants

| Variant | Type | Size | License | Pick it when… |
|----|----|----|----|----|
| T2V-A14B | T2V, MoE (high/low-noise experts) | 27B total/14B active | Apache 2.0 | best quality T2V |
| I2V-A14B | I2V, MoE | 27B total/14B active | Apache 2.0 | best quality I2V |
| TI2V-5B | T2V+I2V, dense, unified single checkpoint | 5B | Apache 2.0 | fits on 8-16GB, faster |
| S2V-14B | audio-to-video | 14B | Apache 2.0 | talking-head/digital human |
| Animate-14B | character animate/faceswap | 14B | Apache 2.0 | motion transfer |
| Lightning LoRAs | 4-step distill (lightx2v, mirrored by Kijai) | small | varies | speed over quality |
| GGUF (any 14B) | quantized (QuantStack, city96) | 5-16GB | Apache 2.0 | VRAM-constrained 14B runs |

## Duration, Frame Count, Resolution, FPS

| Variant | Native fps | Max native length |
|----|----|----|
| T2V-A14B | 16 fps | ~5s (81 frames) |
| I2V-A14B | 16 fps | ~5s (81 frames) |
| TI2V-5B | 24 fps | ~5s (121 frames) |
| S2V-14B | n/a | matches input audio |

Frame-count rule: 4n+1 (17, 21, 25 … 81 for the A14B models). Violating it typically gets silently rounded to the nearest valid count rather than hard-failing, but behavior differs between the official script and ComfyUI nodes — test on your setup.

Resolutions: T2V-A14B/I2V-A14B use 480p and 720p, standard 16:9/9:16 buckets (e.g. 832x480, 480x832, 1280x720, 720x1280). TI2V-5B: 1280x704 or 704x1280 only. Buckets are native pairs (WxH and HxW both trained), not a landscape crop.

Going 480p→720p roughly doubles latent token count; going 81→121 frames adds proportionally more. On a 24GB card, 720p + full 81 frames is where you start needing fp8/GGUF + block swap rather than fp16. For TI2V-5B, 24fps is the trained rate, not just export metadata — requesting a different output fps is a post-process re-time, not a native conditioning knob. Beyond native length, expect quality collapse (drift, freezing, slow-motion artifacts) rather than a hard failure — see Length Extension for chaining as the practical fix.

## Parameters

| Variant | Steps | CFG/guide | Sampler | Shift | Neg prompt useful? |
|----|----|----|----|----|----|
| T2V-A14B | 40-50 | 4.5-5 | unipc | 3-5 | yes |
| I2V-A14B | 40-50 | 4.5-5 | unipc | 3-5 | yes |
| TI2V-5B | 40-50 | 4.5-5 | unipc | 3-5 | yes |
| S2V-14B | 40 | 4.5 | unipc | 3 | yes |

Only S2V-14B's defaults come from an official source; T2V/I2V/TI2V rows are community consensus extrapolated from the same family [?] — treat the exact CFG/shift numbers as a starting point, not gospel. Shift is reported to need scaling up for higher resolution/more motion (community range 3.0-5.0, higher = more motion).

| Variant | Steps | CFG | Sampler | Shift |
|----|----|----|----|----|
| *-Lightning LoRA | 4+4 | 1.0 | euler/euler_a | ~5 |

"4+4" means 4 steps on the high-noise expert (composition) then 4 on low-noise (detail), each with its matching Lightning LoRA applied. CFG must drop to 1.0 with these LoRAs (they distill guidance in) — leaving CFG at 4-5 with a distilled LoRA is the single most common cause of a slideshow/static-frame failure. The second most common cause is a shift value left at defaults tuned for the full model. 4-step output is visibly less dynamic/more static than the 40-50 step full run — fine for previews, not final hero shots. Wan 2.1 LoRAs are broadly compatible with the Wan2.2 **low-noise** expert only; do not apply 2.1-era LoRAs to the high-noise expert — reported to break composition.

## Prompting

Structure that works: subject → action → camera → lighting/scene, roughly in that order; community guides converge on ~80-120 words as the sweet spot before the model stops meaningfully using additional detail. Motion vocabulary commonly reported to work: pan, zoom, orbit, dolly, whip-pan, slow-motion, time-lapse.

The official pipeline supports an optional prompt-expansion step via a Qwen model/API, meant to enrich short prompts before they hit the video model — raw short prompts without it are reported noticeably less detailed/dynamic.

Default negative prompt (same list used since Wan2.1, English translation — check `generate.py`'s literal default if exact wording matters):
"bright colors, overexposed, static, blurred details, subtitles, style, artwork, painting, picture, still, overall gray, worst quality, low quality, JPEG compression residue, ugly, incomplete, extra fingers, poorly drawn hands, poorly drawn faces, deformed, disfigured, malformed limbs, fused fingers, still picture, cluttered background, three legs, many people in the background, walking backwards"

Temporal ("then") sequencing: no dedicated mechanism confirmed; prompts describing "first X, then Y" reportedly work loosely for simple two-beat actions within one clip, reliability drops fast beyond two beats.

Two example prompts at the length the model actually wants:

> A woman in a red raincoat walks briskly down a rain-slicked city street at night, neon signs reflecting in puddles around her. The camera tracks alongside her in a smooth dolly shot at eye level, slightly low angle. Rain falls steadily, illuminated by streetlights; her breath fogs faintly in the cold air. Soft cinematic lighting, shallow depth of field, muted blue-and-red color palette, photorealistic detail.

> A close-up of a barista's hands pouring steamed milk into a cup of espresso, creating a rosetta latte-art pattern. Camera slowly pushes in on the cup. Warm morning light from a side window, shallow depth of field blurring the background cafe. Steam rises gently, motion is slow and deliberate, shot on 50mm lens, soft bokeh, warm color grade.

## Generation Modes

| Mode | Support |
|----|----|
| Text-to-video | native (T2V-A14B, TI2V-5B) |
| Image-to-video (start frame) | native (I2V-A14B, TI2V-5B) |
| First-and-last-frame | community workaround — no dedicated Wan2.2 checkpoint (unlike Wan2.1's FLF2V-14B); ComfyUI reuses I2V-A14B files with start+end frame nodes bolted on. Treat quality as best-effort, not native |
| Video-to-video (restyle) | Fun Control / VACE-Fun (extra weights, see Structural Control) |
| Video extension/continuation | community chaining |
| Inpainting/outpainting | VACE-Fun (extra weights) |
| Instruction-based editing | not supported |
| Reference-driven | native (Animate-14B) — one reference character image plus one driving video; no multi-reference support found |
| Multi-shot in one call | not supported |

V2V denoise range and I2V conditioning-strength values are not documented for this model [?] — no separate "strength" slider confirmed beyond standard latent-concat conditioning.

## Edit Modes

- Checkpoint: the separate Wan2.2-Animate-14B (`Wan2_2-Animate-14B` fp8 in ComfyUI), with an
  optional relight LoRA and the Lightning LoRA.
- Mechanism: the latent of a reference character image plus pose (skeleton) and face-crop
  videos extracted from a driving video; replacement adds the background video and a mask.

| Edit type                      | Support  | Refs            |
|--------------------------------|----------|-----------------|
| Animate a character (Move)     | native   | 1 image + video |
| Replace a character (Mix)      | native   | 1 image + video |
| Restyle / control video (VACE) | VACE-Fun | 1 video         |

- References: one character image and one driving video.
- Prompt: a short description of the character and scene; motion and expressions come from the
  driving video.
- Output size: width and height multiples of 16; the length follows the driving video,
  generated in chunks that continue from the previous motion.
- Settings: as Wan 14B (Lightning LoRA: 4 steps, CFG 1.0); the schedule is set through
  ModelSamplingSD3.
- ComfyUI: WanAnimateToVideo with pose and face preprocessing; Mix also needs the character
  mask. Forge Neo: not supported (Wan 14B T2V/I2V only).
- Typical failures: lighting mismatch in Mix (use the relight LoRA), halos at the mask edge,
  face drift on fast motion or profiles, broken hands in quick gestures.

Example prompts:

- "A woman in a red dress dancing in a sunlit studio"
- "A cartoon fox character performing the same moves, plain background"
- "The man walking down the street, natural evening light"

## Structural and Reference Control

Mature: Alibaba PAI's official Fun checkpoints cover control video, VACE and camera paths, and
ComfyUI runs the 14B Fun Control natively.

- Mechanisms, not interchangeable: Fun Control (control-video channels in a full
  checkpoint pair), VACE (control blocks plus reference images), Fun Camera (camera trajectory
  conditioning).
- Fun Control 14B: [alibaba-pai/Wan2.2-Fun-A14B-Control](https://huggingface.co/alibaba-pai/Wan2.2-Fun-A14B-Control)
  (canny, depth, pose, MLSD, trajectory; Apache-2.0). Comfy-Org repack
  `wan2.2_fun_control_high_noise_14B_fp8_scaled` / `_low_noise_` in
  Comfy-Org/Wan_2.2_ComfyUI_Repackaged, node Wan22FunControlToVideo (template "Wan 2.2 14B Fun
  Control"); the I2V Lightning LoRA pair cuts it to 4 steps at some loss of motion. GGUF:
  [QuantStack/Wan2.2-Fun-A14B-Control-GGUF](https://huggingface.co/QuantStack/Wan2.2-Fun-A14B-Control-GGUF).
- Fun Control 5B: [alibaba-pai/Wan2.2-Fun-5B-Control](https://huggingface.co/alibaba-pai/Wan2.2-Fun-5B-Control)
  (same signals, 121 frames at 24 fps).
- VACE: [alibaba-pai/Wan2.2-VACE-Fun-A14B](https://huggingface.co/alibaba-pai/Wan2.2-VACE-Fun-A14B)
  (built on T2V-A14B, high/low-noise pair, ~64 GB; canny, depth, pose, MLSD, trajectory,
  subject reference images, masked inpaint and outpaint; 512-1024, 81 frames at 16 fps). In
  ComfyUI through Kijai's VACE module files (`Kijai/WanVideo_comfy`, matched high/low pairs)
  with WanVideoWrapper or WanVaceToVideo; GGUF
  [QuantStack/Wan2.2-VACE-Fun-A14B-GGUF](https://huggingface.co/QuantStack/Wan2.2-VACE-Fun-A14B-GGUF).
- Camera: [alibaba-pai/Wan2.2-Fun-A14B-Control-Camera](https://huggingface.co/alibaba-pai/Wan2.2-Fun-A14B-Control-Camera)
  and [alibaba-pai/Wan2.2-Fun-5B-Control-Camera](https://huggingface.co/alibaba-pai/Wan2.2-Fun-5B-Control-Camera):
  pan, tilt, zoom and orbit presets from an image; ComfyUI template "Wan2.2 Fun Camera Control".
- Preprocessors: canny is built into ComfyUI; pose and depth need comfyui_controlnet_aux or
  ComfyUI-DepthAnythingV2. A pre-rendered control video goes in directly.
- On a 3090: fp8 or GGUF pairs; the official workflow defaults to 640×640 to stay in VRAM.
- Identity across a driving video: Animate-14B (see Edit Modes) holds a character better than
  VACE reference images.

## Length Extension and Continuity

Last-frame-as-next-start-frame chaining through the I2V pipeline is the community-standard method to exceed native length; no autoregressive or sliding-window-context mode is documented officially. Color drift and saturation/contrast creep are the most commonly reported degradation across chained segments; motion decay and identity drift also reported over 3+ chained segments. Color-matching each new segment against the previous segment's last frame before feeding it back in helps, as does some frame overlap between segments rather than a hard cut. Community reports diminishing returns past roughly 2-3 chained segments (~15-25s) before drift becomes visually distracting (anecdotal, not benchmarked).

## Upscaling, Interpolation and Post

Two-stage low-res-then-refine (generate at 480p, upscale separately) is a common community workflow rather than an official documented pipeline. SeedVR2 is the commonly-referenced temporal-consistency-preserving upscaler in current Wan workflows; per-frame image upscalers (4x-UltraSharp etc.) are used too but need care to avoid flicker since they have no temporal awareness. RIFE (commonly RIFE49 in ComfyUI) is the standard frame-interpolation choice — if combining with an upscaler like SeedVR2, bypass any interpolation node inside the base Wan workflow first to avoid interpolating twice. Since no Wan2.2 variant offers a genuinely higher native fps, interpolation is the only way to reach higher output fps at all, not a quality tradeoff.

One reported end-to-end pipeline (community, treat as a starting point not a standard): VAEDecode → light unsharp mask → image upscaler (e.g. 4x-UltraSharp) scaled back down ~0.5x for a net ~2x result → RIFE x2 → encode H264 CRF17.

## Quirks and Failure Modes

| Failure | Usual cause | Fix |
|----|----|----|
| Slideshow/static output | CFG left >1 with distilled LoRA | set CFG to 1.0 |
| Slideshow/static output | too few steps for full model | 40-50 steps, no distill |
| Flicker between frames | mismatched shift for resolution | raise shift, use unipc |
| Color/saturation drift | chained segments, no correction | color-match segment joins |
| Background instability | long clips near frame-count max | shorten, chain instead |
| Freeze-then-static tail | exceeding native frame count | stay within 4n+1, ≤81/121 |

Other classic video-diffusion failures (limb/object permanence loss, face degradation over time, unintended slow-motion, physics errors) are reported anecdotally for Wan2.2 but with no systematic single fix — expect them occasionally rather than expecting a reliable single knob to fix them.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
