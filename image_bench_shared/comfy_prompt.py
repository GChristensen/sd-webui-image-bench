"""
Generation parameters of an image saved by ComfyUI, which keeps the executed prompt (API format: {node id:
{class_type, inputs}}, links as [node id, output slot]) in the "prompt" PNG text instead of an infotext.

The prompt is turned into an infotext as WebUI writes it ("prompt\nNegative prompt: ...\nSteps: ..., Model: ..."),
so that it is parsed and mapped like any other: the first-pass sampler gives seed, steps, CFG, sampler and scheduler,
its conditioning the prompts (followed back through ControlNet and guidance nodes to the text), its model path the
checkpoint, LoRAs and shift, its latent the size; a sampler working on the output of another one is the Hires. fix
pass (steps and denoising strength). An encoded latent gives the denoising strength of the first pass, an Inpaint Crop
on its path the inpaint options (mask blur, mask mode, inpaint area, padding).

The graph is walked by input names, without node definitions, so that it works on either host and with node types
it does not know.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

SAMPLER_TYPES = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"}

# Inputs holding the text of a prompt, by preference
TEXT_INPUTS = ("text", "prompt", "text_g", "t5xxl", "clip_l", "value", "string")
# Inputs a conditioning is passed on through (ControlNet apply nodes have positive/negative: chosen by the slot)
CONDITIONING_INPUTS = ("conditioning", "conditioning_to", "conditioning_1", "cond")
# Inputs of the model and latent paths
MODEL_INPUTS = ("model", "unet")
LATENT_INPUTS = ("latent_image", "latent", "samples")
# Loaders of the checkpoint (or diffusion model), by the input of the file name
MODEL_NAME_INPUTS = ("ckpt_name", "unet_name", "model_name", "model_path")

# The crop node of ComfyUI-Inpaint-CropAndStitch
INPAINT_CROP_TYPE = "InpaintCropImproved"

MODEL_EXTENSIONS = re.compile(r"\.(safetensors|sft|gguf|ckpt|pt|pth|bin)$", re.IGNORECASE)
MAX_DEPTH = 64


def is_link(prompt: Dict[str, Any], value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)
            and str(value[0]) in prompt)


class PromptGraph:
    def __init__(self, prompt: Dict[str, Any]):
        self.prompt = prompt

    def node(self, node_id) -> Dict[str, Any]:
        return self.prompt.get(str(node_id)) or {}

    def inputs(self, node_id) -> Dict[str, Any]:
        return self.node(node_id).get("inputs") or {}

    def type(self, node_id) -> str:
        return self.node(node_id).get("class_type") or ""

    def source(self, value) -> Optional[Tuple[str, int]]:
        """(node id, slot) of a link"""
        return (str(value[0]), value[1]) if is_link(self.prompt, value) else None

    def value(self, value, depth: int = 0):
        """A plain input value; a link is followed to the value of a primitive node (or a node passing one on)"""
        link = self.source(value)

        if not link:
            return value

        if depth > MAX_DEPTH:
            return None

        inputs = self.inputs(link[0])

        for name in ("value", "seed", "noise_seed", "int", "float", "number", "string", "text", "boolean"):
            if name in inputs:
                return self.value(inputs[name], depth + 1)

        # A node with a single input passes it on (Reroute, converters)
        if len(inputs) == 1:
            return self.value(next(iter(inputs.values())), depth + 1)

        return None

    def text(self, value, depth: int = 0) -> Optional[str]:
        """Text of a string input or of the node a string link comes from"""
        link = self.source(value)

        if not link:
            return value if isinstance(value, str) else None

        if depth > MAX_DEPTH:
            return None

        inputs = self.inputs(link[0])

        for name in TEXT_INPUTS:
            if name in inputs:
                text = self.text(inputs[name], depth + 1)

                if text is not None:
                    return text

        return None

    def conditioning_text(self, value, negative: bool, depth: int = 0) -> Optional[str]:
        """
        Prompt of a conditioning: the text of the encoder it comes from, followed back through the nodes that
        change a conditioning (ControlNet, guidance, concat, ...)
        """
        link = self.source(value)

        if not link or depth > MAX_DEPTH:
            return None

        node_id, slot = link
        inputs = self.inputs(node_id)

        # An encoder of both prompts (TextEncodeQwenImage21): the negative one on the second output
        if "negative_prompt" in inputs and (negative or slot == 1):
            return self.text(inputs["negative_prompt"])

        for name in TEXT_INPUTS[:5]:
            if name in inputs:
                text = self.text(inputs[name])

                if text is not None:
                    return text

        # ControlNet apply nodes: positive on the first output, negative on the second
        if "positive" in inputs and "negative" in inputs:
            return self.conditioning_text(inputs["negative" if slot == 1 else "positive"], negative, depth + 1)

        for name in CONDITIONING_INPUTS:
            if name in inputs:
                return self.conditioning_text(inputs[name], negative, depth + 1)

        return None

    def upstream(self, value, names, depth: int = 0):
        """Node ids along a path of inputs (model, latent), from the nearest one"""
        result = []

        while depth <= MAX_DEPTH:
            link = self.source(value)

            if not link:
                break

            result.append(link[0])
            inputs = self.inputs(link[0])
            value = next((inputs[name] for name in names if self.source(inputs.get(name))), None)
            depth += 1

        return result


def find_samplers(graph: PromptGraph) -> List[str]:
    return sorted((node_id for node_id in graph.prompt if graph.type(node_id) in SAMPLER_TYPES),
                  key=lambda node_id: (len(node_id), node_id))


def sampler_parts(graph: PromptGraph, sampler_id: str) -> Dict[str, Any]:
    """
    Inputs of a sampler, wherever they are: {seed, steps, cfg, sampler, scheduler, denoise, model, positive,
    negative, latent} (model, positive, negative, latent are links)
    """
    inputs = graph.inputs(sampler_id)
    parts = {
        "seed": inputs.get("seed", inputs.get("noise_seed")),
        "steps": inputs.get("steps"),
        "cfg": inputs.get("cfg"),
        "sampler": inputs.get("sampler_name"),
        "scheduler": inputs.get("scheduler"),
        "denoise": inputs.get("denoise"),
        "model": inputs.get("model"),
        "positive": inputs.get("positive"),
        "negative": inputs.get("negative"),
        "latent": inputs.get("latent_image")
    }

    # SamplerCustom(Advanced): noise, guider, sampler and sigmas nodes
    noise = graph.source(inputs.get("noise"))

    if noise:
        parts["seed"] = graph.inputs(noise[0]).get("noise_seed", parts["seed"])

    guider = graph.source(inputs.get("guider"))

    if guider:
        guider_inputs = graph.inputs(guider[0])
        parts["cfg"] = guider_inputs.get("cfg", parts["cfg"])
        parts["model"] = guider_inputs.get("model", parts["model"])
        parts["positive"] = guider_inputs.get("positive", guider_inputs.get("conditioning", parts["positive"]))
        parts["negative"] = guider_inputs.get("negative", parts["negative"])

    sampler = graph.source(inputs.get("sampler"))

    if sampler:
        parts["sampler"] = graph.inputs(sampler[0]).get("sampler_name", parts["sampler"])

    sigmas = graph.source(inputs.get("sigmas"))

    if sigmas:
        sigma_inputs = graph.inputs(sigmas[0])
        parts["steps"] = sigma_inputs.get("steps", parts["steps"])
        parts["scheduler"] = sigma_inputs.get("scheduler", parts["scheduler"])
        parts["denoise"] = sigma_inputs.get("denoise", parts["denoise"])
        parts["model"] = parts["model"] or sigma_inputs.get("model")

    for name in ("seed", "steps", "cfg", "sampler", "scheduler", "denoise"):
        parts[name] = graph.value(parts[name])

    return parts


def is_after_sampler(graph: PromptGraph, sampler_id: str, samplers: List[str]) -> bool:
    """Whether a sampler works on the output of another one (a Hires. fix pass), through decode/encode nodes"""
    parts = sampler_parts(graph, sampler_id)
    seen = set()
    pending = [parts["latent"]]

    while pending:
        link = graph.source(pending.pop())

        if not link or link[0] in seen or len(seen) > 200:
            continue

        seen.add(link[0])

        if link[0] in samplers:
            return True

        pending.extend(value for value in graph.inputs(link[0]).values() if graph.source(value))

    return False


def model_info(graph: PromptGraph, model_link) -> Dict[str, Any]:
    """Checkpoint, LoRAs and shift along the model path of a sampler"""
    info = {"model": None, "loras": [], "shift": None}

    for node_id in graph.upstream(model_link, MODEL_INPUTS):
        inputs = graph.inputs(node_id)
        name = next((graph.value(inputs[key]) for key in MODEL_NAME_INPUTS if key in inputs), None)

        if isinstance(name, str) and info["model"] is None:
            info["model"] = name
        elif "lora_name" in inputs:
            lora = graph.value(inputs["lora_name"])
            weight = graph.value(inputs.get("strength_model", 1))

            if isinstance(lora, str) and weight not in (0, 0.0):
                info["loras"].append((lora, weight))
        elif "shift" in inputs and info["shift"] is None:
            info["shift"] = graph.value(inputs["shift"])

    return info


def latent_size(graph: PromptGraph, latent_link) -> Optional[Tuple[int, int]]:
    for node_id in graph.upstream(latent_link, LATENT_INPUTS + ("pixels", "image")):
        inputs = graph.inputs(node_id)

        # Inpaint Crop scales the crop to its target size (WebUI's "Resize to" of inpaint)
        if graph.type(node_id) == INPAINT_CROP_TYPE:
            if not graph.value(inputs.get("output_resize_to_target_size")):
                return None

            inputs = {"width": inputs.get("output_target_width"), "height": inputs.get("output_target_height")}

        if "width" in inputs and "height" in inputs:
            width, height = graph.value(inputs["width"]), graph.value(inputs["height"])

            if isinstance(width, (int, float)) and isinstance(height, (int, float)):
                return int(width), int(height)

    return None


def is_img2img(graph: PromptGraph, latent_link) -> bool:
    """Whether the latent of a sampler is an encoded image"""
    return any("pixels" in graph.inputs(node_id) for node_id in graph.upstream(latent_link, LATENT_INPUTS))


def inpaint_options(graph: PromptGraph, latent_link) -> List[Tuple[str, Any]]:
    """
    Infotext entries of the Inpaint Crop node (ComfyUI-Inpaint-CropAndStitch) the latent of a sampler comes from, as
    WebUI writes its inpaint options: the mask blur, the mask mode and the area only if they are not the defaults.
    The bundled inpaint workflows feed its context mask from a GrowMask (padding) and a SolidMask (1: whole picture)
    """
    crop = next((node_id for node_id in graph.upstream(latent_link, LATENT_INPUTS + ("pixels", "image"))
                 if graph.type(node_id) == INPAINT_CROP_TYPE), None)

    if crop is None:
        return []

    inputs = graph.inputs(crop)
    entries = [("Mask blur", graph.value(inputs.get("mask_blend_pixels")))]

    if graph.value(inputs.get("mask_invert")):
        entries.append(("Mask mode", "Inpaint not masked"))

    # The nodes of the context mask
    context = {}
    pending = [inputs.get("optional_context_mask")]

    while pending and len(context) < 50:
        link = graph.source(pending.pop())

        if link and link[0] not in context:
            context[link[0]] = graph.type(link[0])
            pending.extend(value for value in graph.inputs(link[0]).values() if graph.source(value))

    whole = any(node_type == "SolidMask" and (graph.value(graph.inputs(node_id).get("value")) or 0) >= 0.5
                for node_id, node_type in context.items())

    if not whole:
        entries.append(("Inpaint area", "Only masked"))
        padding = next((graph.value(graph.inputs(node_id).get("expand")) for node_id, node_type in context.items()
                        if node_type == "GrowMask"), None)
        entries.append(("Masked area padding", padding))

    return entries


def guidance(graph: PromptGraph, positive_link) -> Optional[float]:
    """Guidance of a FluxGuidance node on the positive conditioning"""
    for node_id in graph.upstream(positive_link, CONDITIONING_INPUTS + ("positive",)):
        inputs = graph.inputs(node_id)

        if "guidance" in inputs:
            return graph.value(inputs["guidance"])

    return None


def format_number(value) -> str:
    return f"{value:g}" if isinstance(value, float) else str(value)


def quote(value: str) -> str:
    return f'"{value}"' if any(char in value for char in ',:"') else value


def model_title(name: str) -> str:
    """File name of a model without its folder and extension, as WebUI writes it"""
    return MODEL_EXTENSIONS.sub("", os.path.basename(name.replace("\\", "/")))


def prompt_to_infotext(prompt: Dict[str, Any]) -> Optional[str]:
    """Infotext of a ComfyUI prompt, None if it has no sampler"""
    graph = PromptGraph(prompt)
    samplers = find_samplers(graph)

    if not samplers:
        return None

    first = next((node_id for node_id in samplers if not is_after_sampler(graph, node_id, samplers)), samplers[0])
    hires = next((node_id for node_id in samplers if node_id != first and is_after_sampler(graph, node_id, samplers)),
                 None)
    parts = sampler_parts(graph, first)

    positive = graph.conditioning_text(parts["positive"], False) or ""
    negative = graph.conditioning_text(parts["negative"], True) if parts["negative"] else None
    model = model_info(graph, parts["model"])

    # LoRAs of loader nodes, as WebUI keeps them in the prompt
    for lora, weight in model["loras"]:
        name = model_title(lora)

        if f"<lora:{name}:" not in positive:
            positive = f"{positive}, <lora:{name}:{format_number(weight)}>" if positive else f"<lora:{name}:{format_number(weight)}>"

    params = []

    def add(key, value):
        if value is not None and value != "":
            params.append(f"{key}: {quote(format_number(value)) if not isinstance(value, str) else quote(value)}")

    add("Steps", parts["steps"])
    add("Sampler", parts["sampler"])
    add("Schedule type", parts["scheduler"])
    add("CFG scale", parts["cfg"])
    add("Distilled CFG Scale", guidance(graph, parts["positive"]))
    add("Seed", parts["seed"])

    size = latent_size(graph, parts["latent"])

    if size:
        add("Size", f"{size[0]}x{size[1]}")

    if model["model"]:
        add("Model", model_title(model["model"]))

    add("Shift", model["shift"])

    if hires:
        hires_parts = sampler_parts(graph, hires)
        add("Denoising strength", hires_parts["denoise"])
        add("Hires steps", hires_parts["steps"])
    elif is_img2img(graph, parts["latent"]):
        add("Denoising strength", parts["denoise"])

    for key, value in inpaint_options(graph, parts["latent"]):
        add(key, value)

    lines = [positive]

    if negative:
        lines.append(f"Negative prompt: {negative}")

    lines.append(", ".join(params))
    return "\n".join(lines)


def read_comfy_infotext(info: Dict[str, Any]) -> Optional[str]:
    """Infotext of the "prompt" text of a ComfyUI image (PNG text or WebP/JPEG EXIF as ComfyUI writes it)"""
    text = info.get("prompt")

    if isinstance(text, bytes):
        text = text.decode("utf8", errors="ignore")

    if not isinstance(text, str) or not text.strip().startswith("{"):
        return None

    try:
        prompt = json.loads(text)
    except ValueError:
        return None

    try:
        return prompt_to_infotext(prompt) if isinstance(prompt, dict) else None
    except Exception as e:
        print(f"[Image Bench] Unable to read the ComfyUI prompt of an image: {e}")
        return None
