"""
Image Bench for Krita: exchanges images with SD WebUI or ComfyUI with the Image Bench extension
(see editor-extensions/PROTOCOL.md)
"""
from krita import DockWidgetFactory, DockWidgetFactoryBase, Krita

from .docker import ImageBenchDocker
from .extension import ImageBenchExtension

_app = Krita.instance()
_app.addExtension(ImageBenchExtension(_app))
_app.addDockWidgetFactory(DockWidgetFactory("imageBenchDocker", DockWidgetFactoryBase.DockRight, ImageBenchDocker))
