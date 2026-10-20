"""
The Image Bench docker: the server URL with the connection state, the send buttons and the status of the last transfer
"""
from krita import DockWidget
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from . import extension

CONNECTION_STATES = {
    "connected": ("Connected", "Connected to the server: click to reconnect", "#3fb950"),
    "connecting": ("Connecting...", "Connecting to the server: click to retry", "#d29922"),
    "disconnected": ("Reconnect", "Not connected to the server: click to reconnect", "#f85149"),
    "replaced": ("Reconnect", "Another editor connected to the server: click to take the connection", "#8b949e"),
}

# Docker groups: (title, ids of extension.SEND_ACTIONS)
GROUPS = [
    ("Input / Inpaint", ("send_image", "send_mask", "send_image_and_mask")),
    ("ControlNet", ("send_cn_preprocess", "send_cn_image", "send_cn_mask")),
    ("Keep", ("send_compare", "save_file", "save_final")),
]


class ImageBenchDocker(DockWidget):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Bench")
        self._extension = extension.instance
        self._buttons = []

        root = QWidget(self)
        layout = QVBoxLayout(root)

        url_row = QHBoxLayout()
        self._url = QComboBox()
        self._url.setEditable(True)
        self._url.setInsertPolicy(QComboBox.NoInsert)
        self._url.setToolTip("SD WebUI or ComfyUI with the Image Bench extension")
        self._url.lineEdit().returnPressed.connect(self._apply_url)
        self._url.activated.connect(lambda _: self._apply_url())
        url_row.addWidget(self._url, 1)

        self._dot = QLabel("●")
        url_row.addWidget(self._dot)
        self._connection = QPushButton()
        self._connection.clicked.connect(self._apply_url)
        url_row.addWidget(self._connection)
        layout.addLayout(url_row)

        actions = {action_id: (text, function) for action_id, _, text, function in extension.SEND_ACTIONS}

        for title, ids in GROUPS:
            group = QGroupBox(title)
            grid = QGridLayout(group)

            for column, action_id in enumerate(ids):
                text, function = actions[action_id]
                button = QPushButton(text)
                button.clicked.connect(lambda checked=False, function=function:
                                       self._extension.run(function, from_docker=True))
                grid.addWidget(button, 0, column)
                self._buttons.append(button)

            layout.addWidget(group)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._status)
        layout.addStretch(1)
        self.setWidget(root)

        self._fill_urls()
        self._extension.client.stateChanged.connect(self._on_state_changed)
        self._extension.statusChanged.connect(self._on_status)
        self._extension.busyChanged.connect(self._on_busy)
        self._on_state_changed(self._extension.client.state)

    def canvasChanged(self, canvas):
        pass

    def _fill_urls(self):
        current = self._extension.url()
        self._url.blockSignals(True)
        self._url.clear()
        self._url.addItems([current] + [url for url in self._extension.recent_urls() if url != current])
        self._url.setCurrentIndex(0)
        self._url.blockSignals(False)

    def _apply_url(self):
        self._extension.set_url(self._url.currentText())

    def _on_state_changed(self, state):
        label, tooltip, color = CONNECTION_STATES[state]
        self._connection.setText(label)
        self._connection.setToolTip(tooltip)
        self._dot.setStyleSheet(f"color: {color}")

        if state == "connected":
            self._fill_urls()

    def _on_status(self, text, is_error):
        self._status.setText(text)
        self._status.setStyleSheet("color: #f85149" if is_error else "")

    def _on_busy(self, busy):
        for button in self._buttons:
            button.setEnabled(not busy)
