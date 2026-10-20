"""
The /image-bench/app entry point of both hosts: Image Bench in the embedded mode, which loads the host UI in its own
iframe tab, so that the host page never has to be opened by hand. The launcher page activates an open app, or loads
it in its own tab (as a popup window with the openInWindow setting)
"""

import os

# Opens the app as a popup window (a page cannot open one without a redirect)
LAUNCHER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "launcher.html")
