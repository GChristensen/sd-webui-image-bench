import os
import json
from typing import Dict, Any, Optional, Tuple


def read_json_file(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Read and parse a JSON file.

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON data or None if error
    """
    try:
        with open(file_path, 'r', encoding="utf-8") as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        print(f"Error: The file at {file_path} was not found.")
        return None
    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON from the file at {file_path}.")
        return None


async def read_request_body(request) -> bytes:
    """
    Read request body from either FastAPI or aiohttp request.

    Args:
        request: FastAPI Request or aiohttp Request object

    Returns:
        Request body as bytes

    Raises:
        ValueError: If request type is not supported
    """
    # FastAPI Request has 'body' method
    if hasattr(request, 'body') and callable(request.body):
        return await request.body()
    # aiohttp Request has 'read' method
    elif hasattr(request, 'read') and callable(request.read):
        return await request.read()
    else:
        raise ValueError(f"Unsupported request type: {type(request)}")


def read_file_content(file_path: str, default: str = "") -> str:
    """
    Read text file content.

    Args:
        file_path: Path to file
        default: Default value if file doesn't exist

    Returns:
        File content as string, or default if file not found
    """
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    return default


def write_file_content(file_path: str, content: str):
    """
    Write text content to file.

    Args:
        file_path: Path to write to
        content: String content to write
    """
    # store/ is not shipped: a new install creates it with the first write
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)


def write_file_bytes(file_path: str, content: bytes):
    """
    Write bytes to file.

    Args:
        file_path: Path to write to
        content: Bytes to write
    """
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    with open(file_path, 'wb') as f:
        f.write(content)


async def write_file_from_request(file_path: str, request, as_text: bool = False):
    """
    Write file from request body (works with both FastAPI and aiohttp).

    Args:
        file_path: Path to write to
        request: FastAPI or aiohttp Request object
        as_text: If True, decode as UTF-8 text; otherwise write raw bytes
    """
    content = await read_request_body(request)
    if as_text:
        write_file_content(file_path, content.decode('utf-8'))
    else:
        write_file_bytes(file_path, content)


# Store-specific convenience functions

def get_store_file_path(base_dir: str, filename: str) -> str:
    """
    Get full path for a file in the store subdirectory.

    Args:
        base_dir: Base directory containing 'store' folder
        filename: Name of file in store folder

    Returns:
        Full path to store file
    """
    return os.path.join(base_dir, "store", filename)


# The last prompts generated from the Generate tab, saved with the projects
PROMPT_HISTORY_FILE = "prompt_history.json"
# Values of the generation dialogs and toolbars (variation strength, sweep values, config presets), global
GENERATION_SETTINGS_FILE = "generation_settings.json"

# The snippets of a new install, styles of comfyui-styles-all and Fooocus (see THIRD_PARTY_LICENSES)
DEFAULT_SNIPPETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "default_snippets.json")


def serve_store_file_content(base_dir: str, filename: str, default_file: str = "") -> str:
    """
    Read store file content.

    Args:
        base_dir: Base directory containing 'store' folder
        filename: Name of file in store folder
        default_file: Path of a file served while the store file doesn't exist

    Returns:
        File content as string, or empty string if neither file exists
    """
    file_path = get_store_file_path(base_dir, filename)

    if default_file and not os.path.exists(file_path):
        file_path = default_file

    return read_file_content(file_path, "")


async def write_store_file_content(base_dir: str, filename: str, content: str):
    """
    Write content to store file.

    Args:
        base_dir: Base directory containing 'store' folder
        filename: Name of file in store folder
        content: String content to write
    """
    file_path = get_store_file_path(base_dir, filename)
    write_file_content(file_path, content)


async def write_store_file_from_request(base_dir: str, filename: str, request):
    """
    Write store file from request body (works with both FastAPI and aiohttp).

    Args:
        base_dir: Base directory containing 'store' folder
        filename: Name of file in store folder
        request: FastAPI or aiohttp Request object
    """
    content = await read_request_body(request)
    file_path = get_store_file_path(base_dir, filename)
    write_file_content(file_path, content.decode('utf-8'))


def clear_directory(directory_path: str):
    """
    Clear all files and directories within the specified directory.

    Args:
        directory_path: Path to directory to clear

    Note:
        Does not delete the directory itself, only its contents.
        Handles exceptions gracefully and continues on error.
    """
    import shutil

    if not os.path.exists(directory_path):
        print(f"Directory does not exist: {directory_path}")
        return

    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f'Failed to delete {file_path}. Reason: {e}')
