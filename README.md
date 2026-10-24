# Image Bench for SD WebUI

Image Bench automates the repetitive micro-tasks of working with SD WebUI.
Basically, it is an image generation UI that works on top of SD WebUI by driving it.
It is built so that you never have to touch the file manager or image browser during
the whole process. Generated images are captured from WebUI, and you save
the best ones into trays that allow you to perform common operations on them.
For example, to upscale an image, you just click one button, without needing
to manually extract image generation parameters, such as the generation seed.
You can also send images to and from graphics editor with a single click,
skipping copy-and-paste operations entirely. See more at the [extension site](https://gchristensen.github.io/image-bench).

The full manual is built in: **Library › Manual** in the Image Bench window.

Note: This add-on is not designed to make SD WebUI less complicated.
It automates repetitive tasks, not the creative process.

## Prompting skill

Image Bench also has a Claude skill, [diffusion-prompting](https://github.com/GChristensen/image-bench/tree/master/skills/diffusion-prompting).
It writes, fixes and converts prompts and suggests sampler settings for the models described in the Library tab
(SDXL, FLUX, Qwen-Image, Z-Image, WAN 2.2 and others), using the same model docs as its references.
Download [diffusion-prompting.zip](https://github.com/GChristensen/image-bench/releases/download/skills/diffusion-prompting.zip) and upload it to claude.ai (Settings › Capabilities › Skills)
or unpack it into `~/.claude/skills/`.

## Installation

From the WebUI page:

1. Open **Extensions › Install from URL**.
2. Enter `https://github.com/GChristensen/sd-webui-image-bench` as the URL and press **Install**.
3. Restart WebUI.

Or clone it by hand into WebUI's `extensions` folder:

```bash
cd <webui>/extensions
git clone https://github.com/GChristensen/sd-webui-image-bench
```

Then restart WebUI. Updates come from **Extensions › Installed › Check for updates**, or `git pull` in the
extension folder. They keep your settings (`config.json`) and the trays and presets in `store/`, which are not
part of the repository.

Optional extensions: [sd-webui-openpose-editor](https://github.com/fabiencomte/sd-webui-openpose-editor) for editing poses from the ControlNet tab.

## Opening Image Bench

Image Bench could run in a standalone mode which loads ComfyUI in background, or be
launched from ComfyUI and work along it.

- `http://<webui address>/image-bench/app` opens it without a WebUI tab: the window loads WebUI itself in a tab
  of its own.
- The **🔬 Image Bench** button in the WebUI toolbar could open it as a new tab or a popup window depending on settings.
  By default, it offers to use the url above.

# Development repository link

This is not a development repository! The full source code is here: https://github.com/GChristensen/image-bench