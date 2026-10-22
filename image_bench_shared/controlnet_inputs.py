"""
ControlNet inputs of the generated images, stored once by their content: image-bench/controlnet/<sha256>.png

The images carry their units inline: image["controlnet"] = {"units": [{index, params, image, mask, preview}]},
the images as hashes (None where there is none). The WebUI page uploads the unit images when Generate is clicked
(webui-extension/javascript/controlnetRecorder.js); ComfyUI records the files of the input nodes of the ControlNet
units when a prompt is posted (record_comfy_prompt), into the extra_data of the prompt, which /history returns.
"""

import hashlib
import os
import re
from typing import Any, Callable, Dict, Optional, Set

from .comfy_prompt import PromptGraph

DIR = "controlnet"
HASH = re.compile(r"^[0-9a-f]{64}$")
IMAGE_KINDS = ("image", "mask", "preview")
# Key of the record in the extra_data of a ComfyUI prompt
EXTRA_DATA_KEY = "image_bench_controlnet"

# Markers anywhere in a node title, several per title, as js/workflow.js finds them ("ControlNet Canny ib:cn:0")
MARKER = re.compile(r"\bib:([a-z]+)(?::(\d+))?\b", re.IGNORECASE)
MAX_DEPTH = 8

# Hashes of the input files by (path, size, mtime_ns), so that an unchanged file is not read again
_file_hashes: Dict[tuple, str] = {}
MAX_FILE_HASHES = 256


def input_dir(image_bench_dir: str) -> str:
    return os.path.join(image_bench_dir, DIR)


def input_path(image_bench_dir: str, value: str) -> str:
    """Path of a stored input; FileNotFoundError if the hash is invalid or not stored"""
    if not isinstance(value, str) or not HASH.match(value):
        raise FileNotFoundError(value)

    path = os.path.join(input_dir(image_bench_dir), f"{value}.png")

    if not os.path.isfile(path):
        raise FileNotFoundError(value)

    return path


def save_input(image_bench_dir: str, data: bytes) -> str:
    """Store an image unless it is stored already; returns its hash"""
    if not data:
        raise ValueError("Empty image")

    value = hashlib.sha256(data).hexdigest()
    directory = input_dir(image_bench_dir)
    path = os.path.join(directory, f"{value}.png")

    if not os.path.isfile(path):
        os.makedirs(directory, exist_ok=True)
        temp = f"{path}.{os.getpid()}.tmp"

        with open(temp, "wb") as file:
            file.write(data)

        os.replace(temp, path)

    return value


def save_file(image_bench_dir: str, path: Optional[str]) -> Optional[str]:
    """Store an image file; returns its hash, None if the file is missing"""
    if not path or not os.path.isfile(path):
        return None

    stat = os.stat(path)
    key = (os.path.normcase(os.path.abspath(path)), stat.st_size, stat.st_mtime_ns)
    value = _file_hashes.get(key)

    if value and os.path.isfile(os.path.join(input_dir(image_bench_dir), f"{value}.png")):
        return value

    with open(path, "rb") as file:
        value = save_input(image_bench_dir, file.read())

    if len(_file_hashes) >= MAX_FILE_HASHES:
        _file_hashes.pop(next(iter(_file_hashes)))

    _file_hashes[key] = value
    return value


def image_hashes(image: Dict[str, Any]) -> Set[str]:
    """Hashes of the stored inputs an image refers to (for the tray archives)"""
    record = image.get("controlnet")
    units = record.get("units") if isinstance(record, dict) else None
    result = set()

    for unit in units or []:
        for kind in IMAGE_KINDS:
            value = unit.get(kind) if isinstance(unit, dict) else None

            if isinstance(value, str) and HASH.match(value):
                result.add(value)

    return result


# ---------- ComfyUI ----------

def marker_index(title, marker: str) -> Optional[int]:
    """Index of the marker ib:<marker>[:N] in a node title (no index is 0), None if the title lacks it"""
    for match in MARKER.finditer(str(title or "")):
        if match.group(1).lower() == marker:
            return int(match.group(2) or 0)

    return None


def find_upstream(graph: PromptGraph, value, types: Dict[str, str]) -> Optional[str]:
    """The nearest node of one of the types up a link, through any inputs (converters, reroutes)"""
    queue = [(value, 0)]
    seen = set()

    while queue:
        value, depth = queue.pop(0)
        link = graph.source(value)

        if not link or link[0] in seen or depth > MAX_DEPTH:
            continue

        node_id = link[0]
        seen.add(node_id)

        if graph.type(node_id) in types:
            return node_id

        queue.extend((input_value, depth + 1) for input_value in graph.inputs(node_id).values())

    return None


def record_comfy_prompt(json_data: Dict[str, Any], image_bench_dir: str, config: Dict[str, Any],
                        file_path: Callable[[str], Optional[str]]) -> Dict[str, Any]:
    """
    On-prompt handler: record the ControlNet units of a posted prompt, the apply nodes marked ib:cn:N
    (bypassed nodes are not in the prompt), with the files of their image and mask input nodes stored by hash
    @param config: The controlnet section of node_config.json
    @param file_path: Path of an input file named by a LoadImage widget value (folder_paths.get_annotated_filepath)
    """
    prompt = json_data.get("prompt")

    if not isinstance(prompt, dict):
        return json_data

    graph = PromptGraph(prompt)
    node_types = set(config.get("nodeTypes") or [])
    image_types = config.get("imageTypes") or {}
    mask_types = config.get("maskTypes") or {}
    loader_types = config.get("loaderTypes") or {}
    preprocessor_types = {name: "" for name in config.get("preprocessorTypes") or []}
    marker = str(config.get("marker") or "cn").lower()
    units = []

    for node_id, node in prompt.items():
        index = marker_index(((node or {}).get("_meta") or {}).get("title"), marker)

        if index is None or graph.type(node_id) not in node_types:
            continue

        inputs = graph.inputs(node_id)
        params = {"weight": graph.value(inputs.get("strength")),
                  "guidanceStart": graph.value(inputs.get("start_percent")),
                  "guidanceEnd": graph.value(inputs.get("end_percent"))}

        loader = find_upstream(graph, inputs.get("control_net"), loader_types)
        if loader:
            params["model"] = graph.value(graph.inputs(loader).get(loader_types[graph.type(loader)]))

        source = inputs.get("image")
        preprocessor = find_upstream(graph, source, preprocessor_types)
        if preprocessor:
            params["preprocessor"] = graph.value(graph.inputs(preprocessor).get("preprocessor"))
            source = graph.inputs(preprocessor).get("image")

        def stored(node, types):
            name = node and graph.value(graph.inputs(node).get(types[graph.type(node)]))
            return save_file(image_bench_dir, file_path(name)) if isinstance(name, str) and name else None

        image_node = find_upstream(graph, source, image_types)
        mask_node = find_upstream(graph, inputs.get("mask_optional"), mask_types)

        units.append({"index": index,
                      "params": {key: value for key, value in params.items() if value is not None},
                      "image": stored(image_node, image_types),
                      "mask": stored(mask_node, mask_types),
                      "preview": None})

    if units:
        units.sort(key=lambda unit: unit["index"])
        json_data.setdefault("extra_data", {})[EXTRA_DATA_KEY] = {"units": units}

    return json_data
