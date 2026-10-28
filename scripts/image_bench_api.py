import asyncio
import json
import os
import re
import sys
import time
import zipfile

from fastapi import Depends, FastAPI, Body, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, StreamingResponse

import gradio as gr
import modules.images as webui_images
import modules.script_callbacks as script_callbacks
import modules.sd_models as sd_models
import modules.shared as shared
import requests

import websockets
from starlette.responses import JSONResponse
from starlette.status import HTTP_204_NO_CONTENT

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from image_bench_shared import persist
from image_bench_shared import civitai
from image_bench_shared import console
from image_bench_shared import controlnet_inputs
from image_bench_shared import explore_export
from image_bench_shared import launcher
from image_bench_shared import loras
from image_bench_shared import media
from image_bench_shared import editor
from image_bench_shared import pnginfo
from image_bench_shared import projects
from image_bench_shared import tray

DEFAULT_CONFIG = """{
  "repositionConfigPresetsDropdown": false,
  "automaticallyClearGeneratedImages": true,
  "exploreLoraFreeImages": true
}
"""

EXTENSION_CONFIG_FILE = "config.json"
IMAGE_TRAY_FILE = tray.TRAY_FILES["image_tray"]
CONCEPT_TRAY_FILE = tray.TRAY_FILES["concept_tray"]
UPSCALED_FILE = tray.TRAY_FILES["upscaled"]
SNIPPETS_FILE = "snippets.json"

TERMINATE_WEBSOCKET = object()


class ImageBenchApi():

    BASE_PATH = "/image-bench"

    def __init__(self):
        webui_config = self.get_webui_config()

        self.websocket_queue = asyncio.Queue()
        # Loop of the websocket, which owns the queue (asyncio queues are not thread-safe)
        self.websocket_loop = None
        # Set to end the handler of a connection when a new one replaces it
        self.websocket_retire_events = set()
        # WebUI pages listening for images sent from the editor
        self.editor_host_websockets = set()
        # The editor plugin receiving images sent from the Image Bench window
        self.editor = editor.EditorConnection()
        # Last image of each kind as (content, media type)
        self.editor_images = {}
        self.config_presets_dropdown = None
        self.outputs_dir = webui_config.get("outdir_samples") or os.path.join(self.get_webui_root_dir(), "outputs")
        self.image_bench_dir = os.path.join(self.outputs_dir, "image-bench")

        config_path = self.get_file_path("../config.json")
        if not os.path.exists(config_path):
            with open(config_path, 'w') as f:
                f.write(DEFAULT_CONFIG)

    def start(self, _: gr.Blocks, app: FastAPI):
        self.app = app
        self.add_api_route("/window", self.get_window, methods=["GET"])
        self.add_api_route("/app", self.get_app, methods=["GET"])
        self.add_api_route("/js/{path:path}", self.get_extension_js, methods=["GET"])
        self.add_api_route("/config.json", self.get_config, methods=["GET"])
        self.add_api_route("/config.json", self.write_config, methods=["POST"])
        self.add_api_route("/explore_presets", self.get_explore_presets, methods=["GET"])
        self.add_api_route("/explore_presets", self.write_explore_presets, methods=["POST"])
        self.add_api_route("/image_tray", self.get_image_tray, methods=["GET"])
        self.add_api_route("/image_tray", self.write_image_tray, methods=["POST"])
        self.add_api_route("/concept_tray", self.get_concept_tray, methods=["GET"])
        self.add_api_route("/concept_tray", self.write_concept_tray, methods=["POST"])
        self.add_api_route("/upscaled", self.get_upscaled, methods=["GET"])
        self.add_api_route("/upscaled", self.write_upscaled, methods=["POST"])
        self.add_api_route("/compare", self.get_compare, methods=["GET"])
        self.add_api_route("/compare", self.write_compare, methods=["POST"])
        self.add_api_route("/compare_upload", self.compare_upload, methods=["POST"])
        self.add_api_route("/png_info", self.png_info, methods=["POST"])
        self.add_api_route("/infotext", self.write_infotext, methods=["POST"])
        self.add_api_route("/media/thumb", self.get_media_thumb, methods=["GET"])
        self.add_api_route("/media/info", self.get_media_info, methods=["GET"])
        self.add_api_route("/config_presets", self.get_presets, methods=["GET"])
        self.add_api_route("/clear_outputs_dir", self.clear_outputs_dir, methods=["POST"])
        self.add_api_route("/download_image_tray", self.download_image_tray, methods=["GET"])
        self.add_api_route("/explore_export", self.explore_export, methods=["POST"])
        self.add_api_route("/image_tray_upload", self.image_tray_upload, methods=["POST"])
        self.add_api_route("/concept_tray_upload", self.image_tray_upload, methods=["POST"])
        self.add_api_route("/models", self.get_models, methods=["GET"])
        self.add_api_route("/samplers", self.get_samplers, methods=["GET"])
        self.add_api_route("/loras", self.get_loras, methods=["GET"])
        self.add_api_route("/modules", self.get_modules, methods=["GET"])
        self.add_api_route("/refresh_models", self.refresh_models, methods=["POST"])
        self.add_api_route("/webui_options", self.get_webui_options, methods=["GET"])
        self.add_api_route("/webui_options", self.write_webui_options, methods=["POST"])
        self.add_api_route("/controlnet/choices", self.get_controlnet_choices, methods=["GET"])
        self.add_api_route("/controlnet/input", self.save_controlnet_input, methods=["POST"])
        self.add_api_route("/controlnet/input", self.get_controlnet_input, methods=["GET"])
        self.add_api_route("/civitai/model_info", self.get_civitai_model_info, methods=["GET"])
        self.add_api_route("/snippets", self.get_snippets, methods=["GET"])
        self.add_api_route("/snippets", self.write_snippets, methods=["POST"])
        self.add_api_route("/snippets/webui_styles", self.get_webui_styles, methods=["GET"])
        self.add_api_route("/prompt_history", self.get_prompt_history, methods=["GET"])
        self.add_api_route("/prompt_history", self.write_prompt_history, methods=["POST"])
        self.add_api_route("/generation_settings", self.get_generation_settings, methods=["GET"])
        self.add_api_route("/generation_settings", self.write_generation_settings, methods=["POST"])
        self.add_api_route("/projects/{action}", self.projects_action, methods=["GET", "POST"])
        self.app.add_websocket_route(self.BASE_PATH + "/websocket", self.handle_websocket)
        self.add_api_route("/close_websocket", self.close_websocket, methods=["POST"])
        self.app.add_websocket_route(self.BASE_PATH + "/heartbeat", self.handle_heartbeat)
        self.app.add_websocket_route(self.BASE_PATH + "/console", self.handle_console)
        self.add_api_route("/editor/upload", self.editor_upload, methods=["POST"], guarded=False)
        self.add_api_route("/editor/project", self.editor_project, methods=["POST"], guarded=False)
        self.add_api_route("/editor/send", self.editor_send, methods=["POST"])
        self.add_api_route("/editor/image", self.get_editor_image, methods=["GET"])
        self.add_api_route("/editor/status", self.get_editor_status, methods=["GET"])
        self.add_api_route("/generation_status", self.get_generation_status, methods=["GET"])
        self.add_api_route("/interrupt", self.interrupt, methods=["POST"])
        self.add_api_route("/skip", self.skip, methods=["POST"])
        self.app.add_websocket_route(self.BASE_PATH + "/editor/host-websocket", self.handle_editor_host_websocket)
        self.app.add_websocket_route(self.BASE_PATH + "/editor/websocket", self.handle_editor_websocket)
        # The routes of the Photoshop plugins installed before the editor bridge
        self.add_api_route("/photoshop/upload", self.editor_upload, methods=["POST"], guarded=False)
        self.app.add_websocket_route(self.BASE_PATH + "/photoshop/plugin-websocket", self.handle_editor_websocket)

    def get_path(self, path):
        return f"{self.BASE_PATH}{path}"

    def get_webui_root_dir(self):
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    def add_api_route(self, path: str, endpoint, guarded: bool = True, **kwargs):
        """
        A route of the extension; guarded routes refuse the requests that change something from other sites.
        The routes of the editor plugins are not guarded, since their requests may carry any headers
        """
        if guarded:
            kwargs["dependencies"] = [*kwargs.get("dependencies", []), Depends(self.reject_cross_site)]

        return self.app.add_api_route(self.get_path(path), endpoint, **kwargs)

    @staticmethod
    def reject_cross_site(request: Request):
        """
        Refuse a request that may change something sent by a page of another site (as ComfyUI does). The browser sets
        Sec-Fetch-Site itself, so proxies do not change it; GET is never refused, since Firefox marks bookmarks of an
        https host reached by HTTPS-First as cross-site, and no GET route changes anything
        """
        if request.method not in ("GET", "HEAD") and request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise HTTPException(status_code=403, detail="Cross-site request")

    def get_config(self):
        config_path = self.get_file_path(EXTENSION_CONFIG_FILE, upper=True)
        return FileResponse(config_path, media_type="application/json")

    def get_webui_config(self):
        config_path = os.path.join(self.get_webui_root_dir(), "config.json")
        return persist.read_json_file(config_path) or {}

    async def write_config(self, request: Request):
        config_path = self.get_file_path("../config.json")
        await persist.write_file_from_request(config_path, request, as_text=False)
        return Response("", media_type="application/json")

    def get_window(self):
        index_html_path = self.get_file_path("index.html")
        return FileResponse(index_html_path, headers={"Cache-Control": "no-cache"})

    def get_app(self):
        return FileResponse(launcher.LAUNCHER_PATH, headers={"Cache-Control": "no-cache"})

    def get_extension_js(self, path: str):
        # Serves the extension's ES module graph with revalidation, since Gradio's file= route
        # lets browsers cache modules imported without the mtime query
        base_dir = os.path.normpath(self.get_file_path("../javascript"))
        file_path = os.path.normpath(os.path.join(base_dir, path))

        # Check the unresolved path: javascript/shared is a symlink outside of base_dir
        if (not path.endswith(".js") or ".." in path.replace("\\", "/").split("/")
                or os.path.commonpath([base_dir, file_path]) != base_dir
                or not os.path.isfile(file_path)):
            raise HTTPException(status_code=404)

        return FileResponse(file_path, media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    def on_image_saved(self, image_data):
        filename = image_data.filename
        # print("\n", image_data.filename, "\n")
        # print("\n", image_data.pnginfo, "\n")
        # print("\n", image_data.p.__dict__, "\n")

        if not (filename.startswith("/") or ":" in filename):
            filename = self.get_webui_root_dir() + "/" + filename

        if not self.is_grid(filename):
            filename = filename.replace("\\", "/")

            msg = {
                "type": "SAVED_IMAGE",
                "imageUrl": f"/file={filename}",
                "imagePath": filename,
                # job_timestamp is shared by all images of a single generation (batch)
                "batchId": getattr(shared.state, "job_timestamp", None),
                "parameters": self.pnginfo_to_dict(image_data.p.prompt, image_data.p.negative_prompt,
                                                   image_data.pnginfo)
            }

            self.post_websocket_message(msg)

    def is_grid(self, path):
        """
        Whether a saved image is a grid: WebUI names grids grid-NNNN and saves them to the grid directories
        (a path merely containing "grid", e.g. from the prompt, is an image)
        """
        if os.path.basename(path).lower().startswith("grid-"):
            return True

        root_dir = self.get_webui_root_dir()

        def option_dirs(names):
            values = (getattr(shared.opts, name, None) for name in names)
            return [os.path.normcase(os.path.abspath(v if os.path.isabs(v) else os.path.join(root_dir, v)))
                    for v in values if v]

        def is_inside(directory, parent):
            return directory == parent or directory.startswith(parent.rstrip(os.sep) + os.sep)

        directory = os.path.normcase(os.path.abspath(os.path.dirname(path)))
        sample_dirs = option_dirs(("outdir_samples", "outdir_txt2img_samples", "outdir_img2img_samples"))

        # A grid directory holding the images too (configured so) tells nothing
        return any(is_inside(directory, grid_dir)
                   for grid_dir in option_dirs(("outdir_grids", "outdir_txt2img_grids", "outdir_img2img_grids"))
                   if not any(is_inside(sample_dir, grid_dir) for sample_dir in sample_dirs))

    def on_video_saved(self, p, path, info):
        """A video saved by Forge Neo (modules.images.save_video, which has no callback), sent like an image"""
        if not path or not os.path.isfile(path):
            return

        path = os.path.abspath(path).replace("\\", "/")
        prompt = getattr(p, "prompt", "") if not isinstance(p, str) else ""
        negative_prompt = getattr(p, "negative_prompt", "") if not isinstance(p, str) else ""

        self.post_websocket_message({
            "type": "SAVED_IMAGE",
            "mediaType": "video",
            "imageUrl": f"/file={path}",
            "imagePath": path,
            "batchId": getattr(shared.state, "job_timestamp", None),
            "parameters": self.pnginfo_to_dict(prompt, negative_prompt, {"parameters": info}) if info else {}
        })

    def media_file_path(self, url):
        """File path of a /file= URL of a generated file, None outside of the output directories"""
        if not (url or "").startswith("/file="):
            return None

        path = os.path.abspath(url[len("/file="):])
        roots = {self.outputs_dir, self.image_bench_dir, shared.opts.data.get("outdir_videos") or ""}

        for root in filter(None, roots):
            root = os.path.abspath(root)

            try:
                if os.path.commonpath([root, path]) == root:
                    return path
            except ValueError:
                continue

        return None

    async def get_media_thumb(self, url: str):
        """Thumbnail of a generated video by its /file= URL; 404 without PyAV or ffmpeg (the popup shows the video)"""
        path = self.media_file_path(url)

        if not path or media.media_kind(path) != "video":
            raise HTTPException(status_code=400, detail="Not a video")

        try:
            thumb_path = await asyncio.to_thread(media.video_thumbnail, self.image_bench_dir, path)
        except (media.MediaError, OSError) as e:
            raise HTTPException(status_code=404, detail=str(e))

        return FileResponse(thumb_path, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

    async def get_media_info(self, url: str):
        """Duration, frame rate, frame count and soundtrack of a video or audio file by its /file= URL"""
        path = self.media_file_path(url)

        if not path or media.media_kind(path) == "image" or not os.path.isfile(path):
            raise HTTPException(status_code=400, detail="Not a video or audio file")

        try:
            return await asyncio.to_thread(media.probe, path)
        except media.MediaError as e:
            raise HTTPException(status_code=404, detail=str(e))

    def pnginfo_to_dict(self, prompt, negative_prompt, pnginfo):
        return tray.pnginfo_to_dict(prompt, negative_prompt, pnginfo)

    def prompts_from_pnginfo(self, pnginfo):
        return tray.prompts_from_pnginfo(pnginfo)

    def get_file_path(self, file_name, upper=False):
        current_dir = os.path.dirname(os.path.abspath(__file__))

        if upper:
            current_dir = os.path.dirname(current_dir)

        file_path = os.path.join(current_dir, file_name)
        return file_path

    def post_websocket_message(self, msg):
        """
        Queue a message for the websocket from any thread: images are saved on the generation thread, where a put
        into the queue would not wake the loop waiting for it, so that the image would arrive late or never
        """
        loop = self.websocket_loop

        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self.websocket_queue.put_nowait, msg)
        else:
            self.websocket_queue.put_nowait(msg)

    async def handle_websocket(self, websocket, *args):
        self.websocket_loop = asyncio.get_running_loop()
        await websocket.accept()

        while not self.websocket_queue.empty():
            self.websocket_queue.get_nowait()

        # The handlers of earlier connections end: one of a connection lost without close_websocket would wait for
        # the next image and lose it
        for event in self.websocket_retire_events:
            event.set()

        retired = asyncio.Event()
        self.websocket_retire_events.add(retired)

        try:
            while True:
                getter = asyncio.ensure_future(self.websocket_queue.get())
                retire_wait = asyncio.ensure_future(retired.wait())
                await asyncio.wait({getter, retire_wait}, return_when=asyncio.FIRST_COMPLETED)
                retire_wait.cancel()

                if retired.is_set():
                    # A message taken at the same moment goes to the new connection
                    if getter.done() and not getter.cancelled():
                        if getter.result() is not TERMINATE_WEBSOCKET:
                            self.websocket_queue.put_nowait(getter.result())
                    else:
                        getter.cancel()
                    break

                msg = getter.result()

                if msg is TERMINATE_WEBSOCKET:
                    break

                try:
                    await websocket.send_text(json.dumps(msg))
                except Exception as e:
                    print(e)
                    # Kept for the next connection
                    self.websocket_queue.put_nowait(msg)
                    break
        finally:
            self.websocket_retire_events.discard(retired)

    def close_websocket(self):
        self.post_websocket_message(TERMINATE_WEBSOCKET)
        return Response("")

    @staticmethod
    async def handle_heartbeat(websocket, *args):
        """Kept open by the Image Bench window to tell that the backend is running; answers its pings"""
        await websocket.accept()

        try:
            while True:
                if await websocket.receive_text() == "ping":
                    await websocket.send_text("pong")
        except Exception:
            pass

    @staticmethod
    async def handle_console(websocket, *args):
        """The terminal output for the console drawer of the Image Bench window, while it is open"""
        await websocket.accept()
        await console.serve(websocket.send_text, websocket.receive_text)

    async def handle_editor_host_websocket(self, websocket, *args):
        """Keep a WebUI page connected to receive images sent from the editor plugin"""
        await self.keep_websocket(websocket, self.editor_host_websockets)

    async def handle_editor_websocket(self, websocket, *args):
        """
        Keep the editor plugin connected to receive images sent from the Image Bench window,
        and to report when they are in the editor; a new plugin connection replaces this one
        """
        await websocket.accept()
        token = await self.editor.attach(websocket.send_text, lambda code: websocket.close(code=code))

        try:
            while True:
                self.editor.handle_message(token, await websocket.receive_text())
        except Exception:
            pass
        finally:
            self.editor.detach(token)

    @staticmethod
    async def keep_websocket(websocket, clients):
        await websocket.accept()
        clients.add(websocket)

        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass
        finally:
            clients.discard(websocket)

    @staticmethod
    async def broadcast(clients, msg):
        """Send a message to the connected websockets, returning the number of the receivers"""
        text = json.dumps(msg)
        receivers = 0

        for websocket in list(clients):
            try:
                await websocket.send_text(text)
                receivers += 1
            except Exception:
                clients.discard(websocket)

        return receivers

    def get_editor_image_url(self, kind):
        return f"{self.BASE_PATH}/editor/image?kind={kind}&t={time.time_ns()}"

    async def editor_upload(self, request: Request, kind: str, width: int, height: int, components: int,
                            target: str = "input"):
        """
        Receive raw pixels of the document (kind=image) or its selection (kind=mask) from the editor plugin
        and notify the connected WebUI pages to insert it into the target (see editor.EDITOR_TARGET_KINDS)
        """
        if kind not in editor.EDITOR_IMAGE_KINDS:
            raise HTTPException(status_code=400, detail=f"Unknown image kind: {kind}")

        if kind not in editor.EDITOR_TARGET_KINDS.get(target, ()):
            raise HTTPException(status_code=400, detail=f"Unknown target of the {kind}: {target}")

        try:
            png = editor.raw_pixels_to_png(await request.body(), width, height, components)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Saved and added to the Compare tab here, so that it arrives even if the popup is closed
        if target == editor.COMPARE_TARGET:
            image = tray.save_compare_file(f"editor_{time.strftime('%Y%m%d-%H%M%S')}.png", png,
                                           self.image_bench_dir, "webui")
            tray.append_tray_image(self.get_file_path("store", upper=True), tray.COMPARE_KIND, image)
            clients = await self.broadcast(self.editor_host_websockets, {
                "type": "EDITOR_IMAGE",
                "kind": kind,
                "target": target,
                "image": image
            })
            return JSONResponse({"clients": clients, "saved": True})

        self.editor_images[kind] = (png, "image/png")

        clients = await self.broadcast(self.editor_host_websockets, {
            "type": "EDITOR_IMAGE",
            "kind": kind,
            "target": target,
            "imageUrl": self.get_editor_image_url(kind)
        })

        return JSONResponse({"clients": clients})

    async def editor_send(self, request: Request, name: str = "image.png", new_document: bool = False):
        """
        Receive an image file from the Image Bench window and notify the editor plugin to open it,
        answering when the plugin reports the image is in the editor
        """
        media_type = request.headers.get("content-type", "").split(";")[0].strip()

        if media_type not in editor.SENDABLE_MEDIA_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported image type: {media_type}")

        kind = editor.OUTGOING_IMAGE_KIND
        self.editor_images[kind] = (await request.body(), media_type)

        return JSONResponse(await self.editor.send_open_image(editor.get_image_file_name(name, media_type),
                                                              self.get_editor_image_url(kind), new_document))

    def get_editor_status(self):
        """The name of the connected editor, or null"""
        return JSONResponse(self.editor.status())

    def get_generation_status(self):
        """Whether the server runs or queues a generation. The page may still show one that has ended here,
        when Gradio lost its result (an interrupt just as the job ended); the popup then offers to reload it.
        Also the sampling step of the image being generated and the image of the job (batch count): the page shows
        only the whole job's progress, in whole percents"""
        from modules import call_queue, progress

        # FIFOLock of Forge wraps a threading.Lock, older versions use one directly
        lock = getattr(call_queue.queue_lock, "_lock", call_queue.queue_lock)
        locked = lock.locked() if hasattr(lock, "locked") else False
        busy = locked or progress.current_task is not None or bool(progress.pending_tasks) or bool(shared.state.job)

        state = shared.state
        return JSONResponse({"busy": busy, "step": state.sampling_step, "steps": state.sampling_steps,
                             "job": state.job_no, "jobs": state.job_count}, headers={"Cache-Control": "no-store"})

    async def interrupt(self, request: Request):
        """
        Stop the generation of the page's tasks ({tasks: [ids]}, the ids of Forge's submit()) without its Interrupt
        button, whose "Interrupting..." placeholder stays for good if a click comes after the job has ended.
        A running task is interrupted as the button does; one not begun yet is interrupted as it begins, since
        begin() clears an earlier interrupt (install_interrupt_hook()); a finished one is left alone, so that a late
        Stop does not end the next generation. Without ids, the running job is interrupted
        """
        from modules import progress

        body = await persist.read_request_body(request)
        tasks = [task for task in (json.loads(body or b"{}").get("tasks") or []) if isinstance(task, str)]
        interrupted = pending = False

        if runs_task(tasks):
            interrupt_like_button()
            interrupted = True
        else:
            stops = getattr(shared.state.begin, "_image_bench_stops", None)

            for task in tasks:
                if stops is not None and task not in progress.finished_tasks:
                    stops[task] = time.time()
                    pending = True

            prune_pending_stops(stops)

        return JSONResponse({"interrupted": interrupted, "pending": pending}, headers={"Cache-Control": "no-store"})

    async def skip(self, request: Request):
        """
        Skip the image being generated of the page's tasks ({tasks: [ids]}) without the Skip button, as its click
        does (shared.state.skip); WebUI continues with the next image of the batch. Only a running task is skipped:
        begin() clears the flag, and a late skip must not cut the next generation. Without ids, the running job
        """
        body = await persist.read_request_body(request)
        tasks = [task for task in (json.loads(body or b"{}").get("tasks") or []) if isinstance(task, str)]
        skipped = runs_task(tasks)

        if skipped:
            shared.state.skip()

        return JSONResponse({"skipped": skipped}, headers={"Cache-Control": "no-store"})

    def get_editor_image(self, kind: str):
        image = self.editor_images.get(kind)

        if image is None:
            raise HTTPException(status_code=404, detail="Not found")

        content, media_type = image
        return Response(content, media_type=media_type, headers={"Cache-Control": "no-store"})

    @staticmethod
    def get_controlnet_choices(type: str = "All", all_models: bool = False):
        """
        Preprocessors and models of a control type, as Forge ControlNet Integrated offers them after choosing the type
        (models whose file names match it), or all models, as it offers them after refreshing them until the type
        is changed; empty lists without it. Its module is already loaded by its script
        """
        global_state = sys.modules.get("lib_controlnet.global_state")

        if global_state is None:
            return JSONResponse({"preprocessors": [], "models": []})

        return JSONResponse({
            "preprocessors": global_state.get_filtered_preprocessor_names(type),
            "models": global_state.get_all_controlnet_names() if all_models
                      else global_state.get_filtered_controlnet_names(type)
        })

    def get_explore_presets(self):
        return self.serve_store_file("explore_presets.json")

    async def write_explore_presets(self, request: Request):
        base_dir = self.get_file_path("", upper=True)
        await persist.write_store_file_from_request(base_dir, "explore_presets.json", request)
        return Response("", media_type="application/json")

    def get_snippets(self):
        return self.serve_store_file(SNIPPETS_FILE, persist.DEFAULT_SNIPPETS_FILE)

    async def write_snippets(self, request: Request):
        base_dir = self.get_file_path("", upper=True)
        await persist.write_store_file_from_request(base_dir, SNIPPETS_FILE, request)
        return Response("", media_type="application/json")

    def get_prompt_history(self):
        return self.serve_store_file(persist.PROMPT_HISTORY_FILE)

    async def write_prompt_history(self, request: Request):
        base_dir = self.get_file_path("", upper=True)
        await persist.write_store_file_from_request(base_dir, persist.PROMPT_HISTORY_FILE, request)
        return Response("", media_type="application/json")

    def get_generation_settings(self):
        return self.serve_store_file(persist.GENERATION_SETTINGS_FILE)

    async def write_generation_settings(self, request: Request):
        base_dir = self.get_file_path("", upper=True)
        await persist.write_store_file_from_request(base_dir, persist.GENERATION_SETTINGS_FILE, request)
        return Response("", media_type="application/json")

    @staticmethod
    def get_webui_styles():
        """The styles of WebUI (styles.csv), imported as snippets"""
        styles = getattr(getattr(shared, "prompt_styles", None), "styles", None) or {}

        return JSONResponse([{"name": style.name, "prompt": style.prompt or "",
                              "negative_prompt": style.negative_prompt or ""}
                             for name, style in styles.items() if name and name != "None"])

    async def editor_project(self, request: Request, save: str, psd: int, width: int = 0, height: int = 0,
                             components: int = 0):
        """
        Save the editor's document into the folder of the current project (Keep › File / Final of the plugins,
        see projects.save_editor_document): the body is the PSD file, then the raw pixels of the merged document
        """
        store_dir = self.get_file_path("store", upper=True)
        config = persist.read_json_file(self.get_file_path(EXTENSION_CONFIG_FILE, upper=True)) or {}

        try:
            document, image = editor.split_project_upload(await request.body(), psd, width, height, components)
            result = await asyncio.to_thread(projects.save_editor_document, projects.get_root(config), store_dir,
                                             save, document, image)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except projects.ProjectError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status)
        except OSError as e:
            return JSONResponse({"error": str(e)}, status_code=500)

        return JSONResponse(result)

    async def projects_action(self, action: str, request: Request):
        """Projects of the Library tab (see projects.dispatch)"""
        files = {}
        form = None
        body = None

        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            form = {}

            for key, value in (await request.form()).multi_items():
                if hasattr(value, "read"):
                    files[key] = (value.filename, await value.read())
                else:
                    form[key] = value
        elif request.method == "POST":
            body = await request.body()

        store_dir = self.get_file_path("store", upper=True)
        config = persist.read_json_file(self.get_file_path(EXTENSION_CONFIG_FILE, upper=True)) or {}

        try:
            args = projects.parse_args(dict(request.query_params), form, body, files)
            result = await asyncio.to_thread(projects.dispatch, action, args, files, config, store_dir,
                                             self.image_bench_dir, "webui", request.method)
        except projects.ProjectError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status)
        except OSError as e:
            return JSONResponse({"error": str(e)}, status_code=500)

        if isinstance(result, projects.FileResult):
            if result.path:
                return FileResponse(result.path, media_type=result.media_type, headers={"Cache-Control": "no-cache"})

            return Response(result.content, media_type=result.media_type, headers={"Cache-Control": "no-cache"})

        return JSONResponse(result)

    def get_image_tray(self):
        return self.serve_store_file(IMAGE_TRAY_FILE)

    async def write_image_tray(self, request: Request):
        return await self.write_tray(request, "image_tray")

    def get_concept_tray(self):
        return self.serve_store_file(CONCEPT_TRAY_FILE)

    async def write_concept_tray(self, request: Request):
        return await self.write_tray(request, "concept_tray")

    def get_upscaled(self):
        return self.serve_store_file(UPSCALED_FILE)

    async def write_upscaled(self, request: Request):
        return await self.write_tray(request, "upscaled")

    def get_compare(self):
        return self.serve_store_file(tray.TRAY_FILES["compare"])

    async def write_compare(self, request: Request):
        return await self.write_tray(request, "compare")

    async def compare_upload(self, file: UploadFile):
        try:
            image = tray.save_compare_file(file.filename, await file.read(), self.image_bench_dir, "webui")
        except ValueError as e:
            return JSONResponse(content={"error": str(e)})

        return JSONResponse(content=image)

    async def png_info(self, file: UploadFile):
        """Infotext and parameters of an uploaded image, read as WebUI reads them (PNG text, EXIF, NovelAI)"""
        def read_infotext(image):
            try:
                return webui_images.read_info_from_image(image)[0]
            except Exception:
                return pnginfo.read_infotext(image)

        return JSONResponse(content=pnginfo.image_info(await file.read(), read_infotext))

    async def write_infotext(self, request: Request):
        """Write an infotext into a PNG image of the output directories (Paste infotext of the image context menu)"""
        data = json.loads(await request.body())
        path = data.get("imagePath")

        if not explore_export.is_allowed_image(path, self.get_image_output_dirs()):
            return JSONResponse(content={"error": "The image is not a file of the output directories."}, status_code=400)

        try:
            return JSONResponse(content=await asyncio.to_thread(pnginfo.write_infotext, path, data.get("infotext") or ""))
        except (ValueError, OSError) as e:
            return JSONResponse(content={"error": str(e)}, status_code=400)

    async def write_tray(self, request: Request, kind):
        tray_data = json.loads(await request.body())

        # Copy the new images to the tray directory and update their paths
        await tray.save_tray_images(tray_data, kind, self.image_bench_dir, "webui")

        base_dir = self.get_file_path("", upper=True)
        await persist.write_store_file_content(base_dir, tray.TRAY_FILES[kind], json.dumps(tray_data))

        # Return updated tray data so frontend can update its store with new paths
        return Response(json.dumps(tray_data), media_type="application/json")

    def serve_store_file(self, filename, default_file=""):
        base_dir = self.get_file_path("", upper=True)
        result = persist.serve_store_file_content(base_dir, filename, default_file)
        return Response(result, media_type="application/json")

    async def write_store_file(self, filename, content):
        base_dir = self.get_file_path("", upper=True)
        await persist.write_store_file_content(base_dir, filename, content)
        return Response("", media_type="application/json")

    def get_presets(self):
        if self.config_presets_dropdown:
            response = jsonable_encoder(self.config_presets_dropdown.choices)
        else:
            response = jsonable_encoder([])

        return JSONResponse(response)

    def get_models(self):
        """Get list of available SD models/checkpoints"""
        models_list = []
        for model in sd_models.checkpoints_list.values():
            models_list.append({
                "title": model.title,
                "model_name": model.title, #model.model_name
                "hash": model.shorthash,
                "sha256": model.sha256,
                "filename": model.filename
            })
        return JSONResponse(jsonable_encoder(models_list))

    def refresh_models(self):
        """Rescan the checkpoints and LoRAs (as /sdapi/v1/refresh-checkpoints and refresh-loras, which need --api)"""
        sd_models.list_models()

        networks = sys.modules.get("networks")  # Module of the built-in sd_forge_lora extension
        if networks is not None:
            networks.list_available_networks()

        main_entry = self.get_forge_main_entry()
        if main_entry is not None:
            main_entry.refresh_models()

        return JSONResponse({})

    @staticmethod
    def get_forge_main_entry():
        """modules_forge.main_entry of Forge, which lists the VAE / Text Encoder modules; None in other WebUIs"""
        try:
            from modules_forge import main_entry
        except ImportError:
            return None

        return main_entry if hasattr(main_entry, "module_list") else None

    def get_modules(self):
        """VAE / Text Encoder modules of Forge as [{name, kind}], kind "vae" or "te" by the folder of the file"""
        main_entry = self.get_forge_main_entry()

        if main_entry is None:
            return JSONResponse([])

        if not main_entry.module_list:
            main_entry.refresh_models()

        from modules import paths

        te_dirs = [os.path.join(paths.models_path, "text_encoder"), *(getattr(shared.cmd_opts, "text_encoder_dirs", None) or [])]
        te_roots = [os.path.normcase(os.path.abspath(d)) + os.sep for d in te_dirs if d]

        def get_kind(path):
            path = os.path.normcase(os.path.abspath(path))
            return "te" if any(path.startswith(root) for root in te_roots) else "vae"

        modules_list = [{"name": name, "kind": get_kind(path)} for name, path in main_entry.module_list.items()]
        modules_list.sort(key=lambda m: m["name"].lower())
        return JSONResponse(modules_list)

    def get_samplers(self):
        """Get lists of available samplers and schedulers"""
        import modules.sd_samplers as sd_samplers
        import modules.sd_schedulers as sd_schedulers

        return JSONResponse({
            "samplers": sd_samplers.visible_sampler_names(),
            "schedulers": [s.label for s in sd_schedulers.schedulers]
        })

    @staticmethod
    def is_reference_option(name):
        """Only the boolean settings that switch the references of the edit models may be read and changed"""
        return name.endswith("_reference") and isinstance(shared.opts.data.get(name), bool)

    def get_webui_options(self, names: str):
        """Values of the edit reference settings (e.g. klein_no_reference), by comma-separated names"""
        return JSONResponse({name: shared.opts.data[name] for name in names.split(",") if self.is_reference_option(name)})

    async def write_webui_options(self, request: Request):
        """Change edit reference settings given as a JSON object and save the WebUI settings"""
        values = json.loads(await persist.read_request_body(request))

        if not isinstance(values, dict) or not all(self.is_reference_option(name) and isinstance(value, bool)
                                                   for name, value in values.items()):
            raise HTTPException(status_code=400, detail="Only edit reference settings may be changed")

        for name, value in values.items():
            shared.opts.set(name, value)

        shared.opts.save(shared.config_filename)
        return JSONResponse(values)

    def get_loras(self):
        """Get list of available LoRAs with their Forge user metadata (sidecar .json)"""
        networks = sys.modules.get("networks")  # Module of the built-in sd_forge_lora extension

        if networks is None:
            return JSONResponse([])

        # LoRA root folders, as scanned by sd_forge_lora (networks.process_network_files)
        lora_dirs = [getattr(shared.cmd_opts, "lora_dir", None), *(getattr(shared.cmd_opts, "lora_dirs", None) or [])]
        lora_roots = [os.path.abspath(d) for d in lora_dirs if d]

        def get_lora_folder(filename):
            """Folder of the LoRA relative to the deepest root containing it, "" if placed in the root itself"""
            lora_dir = os.path.dirname(os.path.abspath(filename))
            roots = [r for r in lora_roots
                     if os.path.normcase(lora_dir) == os.path.normcase(r)
                     or os.path.normcase(lora_dir).startswith(os.path.normcase(r) + os.sep)]

            if not roots:
                return os.path.basename(lora_dir)

            folder = os.path.relpath(lora_dir, max(roots, key=len))
            return "" if folder == "." else folder.replace(os.sep, "/")

        loras_list = []
        for lora in networks.available_networks.values():
            loras_list.append({
                "name": lora.name,
                "alias": lora.get_alias(),
                "filename": lora.filename,
                "folder": get_lora_folder(lora.filename),
                **loras.read_user_metadata(lora.filename)
            })
        return JSONResponse(jsonable_encoder(loras_list))

    def get_civitai_model_info(self, kind: str = "checkpoint", name: str = "", hash: str = ""):
        """Civitai page and metadata of a checkpoint or LoRA, by name and/or hash
        (no name and hash: the selected checkpoint)"""
        import modules.hashes as hashes

        file_hash = None

        if kind == "lora":
            networks = sys.modules.get("networks")
            available = networks.available_networks if networks else {}
            lora = available.get(name) or next((n for key, n in available.items() if key.lower() == name.lower()), None)

            if lora:
                file_hash = lambda: hashes.sha256(lora.filename, f"lora/{lora.name}")
        else:
            info = sd_models.get_closet_checkpoint_match(name or shared.opts.sd_model_checkpoint)

            if info:
                name = name or info.name

                def file_hash():
                    info.calculate_shorthash()
                    return info.sha256

        store_dir = persist.get_store_file_path(self.get_file_path("", upper=True), "")
        config = persist.read_json_file(self.get_file_path(EXTENSION_CONFIG_FILE, upper=True)) or {}
        domain = config.get("civitaiDomain", "com")
        return JSONResponse(civitai.model_info(name, hash, file_hash, store_dir, domain))

    def on_before_config_presets(self, component, *args, **kwargs):
        if kwargs.get("elem_id") == "config_preset_txt2img_dropdown":
            self.config_presets_dropdown = component

    def clear_outputs_dir(self):
        persist.clear_directory(self.outputs_dir)

    # ControlNet inputs of the generated images, stored by hash (see shared_backend/controlnet_inputs.py)
    async def save_controlnet_input(self, request: Request):
        try:
            return JSONResponse({"hash": controlnet_inputs.save_input(self.image_bench_dir, await request.body())})
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    async def get_controlnet_input(self, hash: str):
        try:
            path = controlnet_inputs.input_path(self.image_bench_dir, hash)
        except FileNotFoundError:
            raise HTTPException(status_code=404)

        return FileResponse(path, headers={"Cache-Control": "max-age=31536000, immutable"})

    async def image_tray_upload(self, file: UploadFile):
        file_data = await file.read()
        result = await tray.image_tray_upload(file.filename, file_data, self.image_bench_dir, IMAGE_TRAY_FILE)
        return JSONResponse(content=result)

    def download_image_tray(self, kind: str):
        store_dir = self.get_file_path("store", upper=True)
        file_path, status_code = tray.download_image_tray(
            kind,
            self.image_bench_dir,
            store_dir,
            IMAGE_TRAY_FILE
        )

        if status_code == 200 and file_path:
            return FileResponse(file_path, media_type="application/zip")
        elif status_code == 204:
            return Response(status_code=HTTP_204_NO_CONTENT)
        else:  # 404
            raise HTTPException(status_code=404, detail="Not found")

    async def explore_export(self, request: Request):
        form = await request.form()
        data = json.loads(form.get("data") or "{}")
        roots = self.get_image_output_dirs()

        def resolve_path(image):
            path = image.get("imagePath")
            return path if explore_export.is_allowed_image(path, roots) else None

        content = explore_export.generate_explore_html(data.get("groups") or [], resolve_path,
                                                       data.get("title") or "Image Bench exploration",
                                                       data.get("matrix"))
        return StreamingResponse(content, media_type="text/html; charset=utf-8",
                                 headers={"Content-Disposition": explore_export.content_disposition()})

    def get_image_output_dirs(self):
        """Directories that generated images may be read from"""
        root_dir = self.get_webui_root_dir()
        option_names = ["outdir_samples", "outdir_txt2img_samples", "outdir_img2img_samples",
                        "outdir_extras_samples", "outdir_grids", "outdir_txt2img_grids",
                        "outdir_img2img_grids", "outdir_save"]
        dirs = [self.outputs_dir, os.path.join(root_dir, "outputs")]

        for name in option_names:
            value = getattr(shared.opts, name, None)
            if value:
                dirs.append(value if os.path.isabs(value) else os.path.join(root_dir, value))

        return dirs

    def import_image_tray(self, archive_path):
        result = tray.import_image_tray(archive_path, self.image_bench_dir, IMAGE_TRAY_FILE)
        return JSONResponse(content=result)


def install_video_hook(api):
    """
    Wrap modules.images.save_video (Forge Neo) once, so that its videos reach the popup; a reload of the scripts only
    points the wrapper to the new api. The generation never fails because of it
    """
    save_video = getattr(webui_images, "save_video", None)

    if save_video is None:
        return

    if not getattr(save_video, "_image_bench", False):
        original = save_video

        def save_video(p, frames, *args, **kwargs):
            path = original(p, frames, *args, **kwargs)

            try:
                save_video._image_bench_api.on_video_saved(p, path, kwargs.get("info"))
            except Exception as e:
                print(f"[Image Bench] Unable to send a saved video: {e}")

            return path

        save_video._image_bench = True
        webui_images.save_video = save_video

    save_video._image_bench_api = api


PENDING_STOP_AGE = 120
PENDING_STOP_LIMIT = 16


def runs_task(tasks):
    """Whether one of the tasks (ids of Forge's submit()) is running; without ids, whether any job is"""
    from modules import progress

    # state.job is set by begin(), current_task just after it
    return progress.current_task in tasks or shared.state.job in tasks or not tasks and bool(shared.state.job)


def interrupt_like_button():
    """The interrupt_function of the Interrupt button (modules/ui_toprow.py): with "Don't Interrupt in the middle",
    the first stop of a batch ends it after the current image"""
    state = shared.state

    if not state.stopping_generation and state.job_count > 1 and getattr(shared.opts, "interrupt_after_current", False):
        state.stop_generating()
    else:
        state.interrupt()


def prune_pending_stops(stops):
    """Drop the stops of tasks that never began: too old, or beyond the limit (the oldest first)"""
    if stops is None:
        return

    now = time.time()

    for task, added in list(stops.items()):
        if now - added > PENDING_STOP_AGE:
            del stops[task]

    while len(stops) > PENDING_STOP_LIMIT:
        del stops[next(iter(stops))]


def install_interrupt_hook():
    """
    Wrap shared.state.begin once, so that a stop of a task that had not begun yet (/image-bench/interrupt) is applied
    as it begins: begin() clears the interrupt flag. The pending stops live on the wrapper, so a reload of the scripts
    keeps them
    """
    state = shared.state
    begin = getattr(state, "begin", None)

    if begin is None or getattr(begin, "_image_bench", False):
        return

    original = begin

    def begin(*args, **kwargs):
        original(*args, **kwargs)

        try:
            job = kwargs.get("job", args[0] if args else None)

            if job is not None and begin._image_bench_stops.pop(job, None) is not None:
                state.interrupt()
        except Exception as e:
            print(f"[Image Bench] Unable to apply a pending stop: {e}")

    begin._image_bench = True
    begin._image_bench_stops = {}
    state.begin = begin


try:
    # As early as possible: the console drawer shows the output from here on
    console.install_stream_tee()

    # The Total progress bar writes to the stdout of the import of shared, and tqdm measures the terminal only for
    # the current sys.stdout / sys.stderr: without this it keeps its narrow default width
    if getattr(shared, "progress_print_out", None) is getattr(sys.stdout, "original", None):
        shared.progress_print_out = sys.stdout
except Exception as e:
    print(f"[Image Bench] Unable to capture the console output: {e}")

try:
    api = ImageBenchApi()
    script_callbacks.on_app_started(api.start)
    script_callbacks.on_image_saved(api.on_image_saved)
    install_video_hook(api)
    install_interrupt_hook()
    script_callbacks.on_before_component(api.on_before_config_presets)
except Exception as e:
    print(e)
