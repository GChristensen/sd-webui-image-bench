# Image Bench for SD WebUI

Image Bench is a generation workspace for SD WebUI, laid out so that the frequent steps
of image generation take as few actions as possible. It runs in its own window and drives
SD WebUI, which does the generation. Every image WebUI generates arrives in Image Bench
with its parameters, and you keep the best ones in trays, where the common follow-up
tasks are automated. For example, upscaling an image takes just one button click, 
with no need to look up its seed
or other parameters, and an image goes to a graphics editor and back in one click,
without copying and pasting. You do not need the file manager or an image browser
at any point. See more at the [extension site](https://gchristensen.github.io/image-bench).

The full manual is built in: **Library › Manual** in the Image Bench window. If you are new to Image Bench, start
with the [tutorial](https://gchristensen.github.io/image-bench/tutorial/), which walks through the common workflows
with screenshots.

Note: This add-on is not designed to make SD WebUI less complicated.
It automates repetitive tasks, not the creative process.

## Prompting skill

Image Bench also has a Claude skill, [diffusion-prompting](https://github.com/GChristensen/image-bench/tree/master/skills/diffusion-prompting).
It writes, fixes and converts prompts and suggests sampler settings for the models described in the Library tab
(SDXL, FLUX, Qwen-Image, Z-Image, WAN 2.2 and others), using the Image Bench model docs as its references.
Download [diffusion-prompting.zip](https://github.com/GChristensen/image-bench/releases/download/skills/diffusion-prompting.zip) and upload it to claude.ai (Settings › Capabilities › Skills)
or unpack it into `~/.claude/skills/`. It may work with other agents that support skills.

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