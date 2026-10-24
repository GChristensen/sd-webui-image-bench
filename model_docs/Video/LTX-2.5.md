# LTX 2.5 Reference

## Overview

- **Model:** Lightricks, 2026-08; successor of LTX-2 (2026-01) and LTX-2.3, whose LoRAs and IC-LoRAs mostly load
- **Backbone:** asymmetric dual-stream DiT (video and audio streams with cross-attention) [?], 22B; rectified flow; dev and distilled checkpoints
- **Text:** Gemma 4 12B with projection layers [?]
- **Video:** 24 fps, 8n+1 frames, about 10 s per shot, several shots in one generation; images condition any frame index with a strength
- **Audio:** joint generation in the same pass, own audio VAE and vocoder, 24 kHz stereo
- **Strengths:** synchronized audio, native multishot with consistent characters, two-stage 2x latent upscaling

## Encoder/VAE

- Repos: HF [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) · ComfyUI: same repo (ships `comfy-int8` files), no Comfy-Org repack
- Video VAE: causal (inherited from the LTX-Video lineage). Two selectable decoders — a diffusion decoder ("DiffVAE", higher quality/slower) and a lightweight convolutional decoder (faster). Files: `ltx-2.5-video-vae-bf16.safetensors` / `ltx-2.5-video-vae-conv-bf16.safetensors` (fast decoder). Whether LTX-2.5 reuses LTX-Video-13B's exact 32x spatial / 8x temporal / 128-channel compression ratios is unconfirmed [?].
- Audio VAE: `ltx-2.5-audio-vae-bf16.safetensors` — stereo audio at 16kHz as mel-spectrograms, decoded to 24kHz stereo via a modified HiFi-GAN vocoder.
- Text encoder: `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors` (per official filenames). This may be a real "Gemma 4" release, an internal codename, or a documentation error — verify on the HF model card before citing it [?]. LTX-2 base itself used Gemma3-12B with a learned projection + bidirectional "text connector" and learnable "thinking tokens." Token limit/language coverage not stated anywhere found [?].
- Latent upscalers: separate 2x spatial (`ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors`) and 2x temporal (`ltx-2.5-latent-temporal-upscaler-x2-bf16-1.0.safetensors`) checkpoints for the two-stage pipeline.

## Recommended Defaults (distilled)

``` text
Resolution:      544 x 960          (official Stage-1 example)
Frame count:     121                (satisfies 8n+1 rule: 15*8+1)
FPS:             24
Steps:           8 (stage 1) + 4 (stage 2), predefined sigmas
CFG:             1.0
Flow shift:      UNKNOWN — not published, do not guess; sweep 1.0 / 3.0 / 5.0 yourself
Negative prompt: "blurry, low quality, static, no movement"
```
Recommending the distilled checkpoint to start — it's the only variant with a fully specified step/CFG recipe and is far more forgiving of VRAM than the dev/full model at 40 steps.

## Variants

| Variant | What it is | License note |
|----|----|----|
| dev (full, bf16) | full-precision base checkpoint | LTX-2.x Community |
| distilled (bf16) | step-reduced distilled checkpoint | LTX-2.x Community |
| distilled, Comfy int8 | quantized for ComfyUI | LTX-2.x Community |
| distilled, NVFP4 | 4-bit, Blackwell-targeted | LTX-2.x Community |
| distilled LoRA (450 st) | LoRA instead of a full checkpoint | LTX-2.x Community |
| LTX-2.5 Pro (API only) | hosted, not downloadable, faster/higher-fidelity than local checkpoints | Commercial (API ToS) |

## Duration, Frame Count, Resolution, FPS

- Frame-count rule: `num_frames % 8 == 1` (8n+1: 1, 9, 17, …, 121, …). Spatial dimensions must be divisible by 32. Exact failure behavior on violation (hard error vs. auto-round) not confirmed [?].
- Stage-1 example resolution: 544x960 @ 24fps; Stage 2 runs at 2x Stage-1 resolution.
- LTX-2 base synthesizes up to ~20s of continuous audio+video with coherence degrading past that point. LTX-2.5 marketing emphasizes ~10s single-shot clips plus native multishot for longer sequences rather than pushing single-clip length further.
- Aspect ratio / portrait-native-vs-cropped: not documented [?].
- LTX-2.3 (predecessor) community guidance, for rough orientation only: iterate at 1280x720 keeping sequences under 257 frames, push to 1920x1080 for final quality.

## Parameters

| Pipeline | Steps | Guidance | Notes |
|----|----|----|----|
| Distilled | 8 (stage1) + 4 (stage2) | CFG = 1 | fixed predefined sigmas |
| Dev/full | 20-30 iterating, 40 final | not specified [?] | "gradient estimation" mode |

- CFG=1 for the distilled pipeline is carried over by strong community convention from LTX-2.3, not independently re-stated on the 2.5 card [?].
- Guidance value for the dev/full pipeline is not published; the LTX-2 base paper's modality-aware CFG weights (text=3/cross-modal=3 for video, text=7/cross-modal=3 for audio) are the closest documented numbers, but whether 2.5's dev pipeline exposes the same two-scale control or collapses it to one slider is unconfirmed.
- Flow/timestep shift: no value published for 2.5 in any source — test empirically, don't guess.
- Negative prompt: supported on dev, useful. Community-common terms: "blurry, low quality, static, no movement" plus artifact/lipsync-mismatch terms when using native audio.
- Most likely "slideshow" cause: a frame count violating the 8n+1 rule, or running the dev pipeline's low step count (under ~20) without switching to the distilled sigma schedule — dev is not step-distilled and degrades hard below its intended step range.

## Prompting

- No official prompt-ordering was published for 2.5 specifically; general LTX-family convention (subject → action → camera → lighting/style) is community-carried from earlier releases.
- An official prompt-enhancer/rewriter (built on the same Gemma encoder family) is part of the intended pipeline — expect noticeably weaker adherence from short raw prompts without it.
- Motion vocabulary, official negative-prompt default, and example prompts at official length: not published for 2.5 [?].
- Temporal "then" sequencing within one clip is not documented either way; native multishot (below) is the documented mechanism for connected scenes.

## Generation Modes

| Mode | Support |
|----|----|
| Text-to-video | native |
| Image-to-video (start frame) | native |
| First-and-last-frame | not confirmed for 2.5 specifically [?] |
| Video-to-video | via IC-LoRA pipeline |
| Video extension/continuation | via Retake pipeline (regional regen) |
| Video inpaint/outpaint | ComfyUI templates exist (unclear if 2.5-updated) [?] |
| Instruction-based editing | not documented |
| Reference-driven generation | IC-LoRA conditioning; exact ref-image/clip count caps not published |
| Text-to-audio | native |
| Audio-to-video | native, via `A2VidPipelineTwoStage` |
| Multi-shot in one call | native — headline feature of 2.5 |

Named pipelines on the official card: DistilledPipeline, DFRPipeline, TI2VidTwoStagesPipeline, ICLoraPipeline, DubItPipeline (lip-sync dubbing), A2VidPipelineTwoStage, RetakePipeline (regional regen), plus additional unnamed specialized pipelines. Denoise ranges for v2v and exact i2v conditioning-strength parameters not published.

## Edit Modes

- Checkpoint: the distilled model with IC-LoRAs (in-context LoRAs); most LTX-2.3 IC-LoRAs load on
  2.5 but need testing.
- Mechanism: the frames of the source or guide video enter as in-context tokens next to the
  generated ones; the IC-LoRA defines what is taken from them.

| Edit type                        | Support             | Refs         |
|----------------------------------|---------------------|--------------|
| V2V transform (source as guide)  | IC-LoRA             | 1 video      |
| Depth / canny / pose control     | Union IC-LoRA       | 1 video      |
| Video inpaint                    | In/outpaint IC-LoRA | video + mask |
| Video outpaint                   | In/outpaint IC-LoRA | 1 video      |
| Reference sheet (Ingredients)    | IC-LoRA             | 1 image      |
| Motion tracks                    | IC-LoRA             | 1 image      |
| SDR to HDR                       | HDR IC-LoRA         | 1 video      |
| Instruction edit (Edit Anything) | community IC-LoRA   | 1 video      |

- References: one guide video (or reference sheet) per IC-LoRA; the source audio can be kept
  frozen.
- Prompt: describe the result; Edit Anything v2 takes Replace / Remove / Add / Restyle
  instructions, several in one prompt, without a reference image.
- Output size: follows the source clip; frames 8n+1, sides divisible by 32.
- Settings: distilled, 8 steps, CFG 1.0; inpaint and outpaint run two stages.
- ComfyUI: the 2.5 example workflows of Lightricks/ComfyUI-LTXVideo (`V2V_ICLoRA_Single_Stage`,
  `ICLoRA_Union_Control`, `ICLoRA_Inpaint_Two_Stage`, `ICLoRA_Outpaint_Two_Stage`,
  `ICLoRA_Ingredients`, `ICLoRA_Motion_Track`). Forge Neo: not supported.
- Typical failures: an over-strong guide copies the source too literally, flicker at mask
  edges, identity loss across a long clip.

Example edit prompts:

- "Replace the red car with a blue vintage bicycle"
- "Remove the man in the background"
- "Add falling snow"
- "Restyle the clip as a hand-painted watercolor animation"
- "Replace the jacket with a black leather jacket and add sunglasses"

## Structural and Reference Control

Mature and official: Lightricks ships control as IC-LoRAs on the distilled model; no classic
ControlNet.

- Mechanism: in-context LoRAs (the guide video's tokens sit next to the generated ones); they
  need the distilled checkpoint (ICLoraPipeline) and do not replace one another.
- Union Control (depth, canny, pose in one adapter): reused from 2.3,
  [Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control),
  `ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors`; the guide runs at half the output
  resolution. Strength 1.0; 0.5-0.8 leaves more freedom.
- Preprocessors in the official workflow: Video Depth Anything (VideoDepthAnythingProcess,
  wired by default), CannyEdgePreprocessor (92/200) and DWPreprocessor from
  comfyui_controlnet_aux; guide sides divisible by 64.
- Motion tracks: [Lightricks/LTX-2.3-22b-IC-LoRA-Motion-Track-Control](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Motion-Track-Control)
  (sparse spline trajectories drawn with LTX Draw Tracks / LTX Sparse Track Editor); the
  camera follows the motion of the guide or the tracks, there is no separate camera-control
  adapter for 2.5.
- Layout to render: [Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render)
  turns a playblast or blockout into a finished shot (strength 1.0, with the 2× latent
  upscaler).
- Identity: [Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Ingredients)
  (reference sheet); within one generation, multi-shot holds characters across cuts.
- ComfyUI: LTXICLoRALoaderModelOnly → LTXAddVideoICLoRAGuide → LTXVCropGuides, from
  [Lightricks/ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) plus
  ComfyUI-VideoDepthAnything; stage 1 at 8 steps with the IC-LoRA, stage 2 upscales 2× in 4
  steps; CFG 1.0-1.5. Output size, length and fps follow the guide video.
- Failures: depth on flat scenes, canny on fur, foliage and heavy texture, pose without visible
  full bodies; describing motion in the prompt fights the guide, so describe the look instead.

## Audio

- Native, single-pass: audio is generated in the same diffusion pass as video via the dual-stream architecture, not a bolted-on second stage.
- Channels/sample rate: encoded at 16kHz stereo mel-spectrograms, decoded/output at 24kHz stereo via a modified HiFi-GAN vocoder.
- Content types: dialogue/lip-sync, foley/effects, ambience, music.
- Audio can be described in the same prompt; whether it can be prompted separately from video text is not confirmed [?].
- Lip-sync: handled via the dedicated DubItPipeline; community tips (2.3-era) suggest converting driving audio to stereo with a 0.2-0.5s leading pause to fix sync issues.
- Disabling audio to save VRAM/time: plausible given audio is a separate stream/VAE, but not confirmed as a toggle [?].

## Length Extension and Continuity

RetakePipeline (regional regen) and native multishot are the official tools for going beyond one continuous clip; a documented autoregressive "continue from last frames" chaining mode was not found for 2.5 specifically [?]. Degradation across chained segments and realistic max coherent length via chaining are not published for 2.5 — the base LTX-2 paper's ~20s coherence figure is for a single continuous generation, a different question from chaining separate generations.

## Upscaling, Interpolation and Post

- Two-stage low-res-then-refine is the intended workflow: Stage 1 at base resolution (e.g. 544x960), Stage 2 at 2x via the official spatial+temporal latent upscalers.
- The official 2x latent upscalers operate in latent space specifically to avoid the flicker that per-frame pixel-space upscalers introduce on video.
- Multi-tile inference with overlapping tiles is used for high-res synthesis (per the base-model paper); seam artifacts at tile boundaries not independently benchmarked.
- No official interpolation tool named for 2.5; RIFE is the de facto community standard for this model family (not confirmed official).
- Denoise values for latent vs. pixel refinement passes: not published [?].
- Recommended pipeline: Stage 1 draft at base res → Stage 2 latent upscale (spatial then/or temporal) → optional DFR detailing pass → optional external frame interpolation.

---

*This file was generated automatically. Do not edit it: all edits are lost on update.*
