import os
from typing import Any, Dict

from . import persist


def read_user_metadata(lora_path: str) -> Dict[str, Any]:
    """Preferred weight and activation text of a LoRA from its Forge / A1111 user metadata (sidecar .json)"""
    metadata_path = os.path.splitext(lora_path)[0] + ".json"
    user_metadata = (persist.read_json_file(metadata_path) if os.path.isfile(metadata_path) else None) or {}

    return {
        "preferredWeight": user_metadata.get("preferred weight") or 1,
        "activationText": user_metadata.get("activation text") or ""
    }
