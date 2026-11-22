from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from ..i18n import tr
from .theme import icon


def label(text, style=None, wrap=False):
    widget = QLabel(text)
    if style:
        widget.setObjectName(style)
    widget.setWordWrap(wrap)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def button(text, glyph=None, primary=False, callback=None):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        widget.setObjectName("primary")
    if glyph:
        widget.setIcon(icon(glyph, "#151515" if primary else "#aaaaaa"))
    if callback:
        widget.clicked.connect(callback)
    return widget


def panel():
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)
    return frame, layout


class DropZone(QFrame):
    files_dropped = Signal(list)
    browse_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(72)
        self.setMaximumHeight(88)
        self.setObjectName("inset")
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)
        title = label(tr('Добавить аудиофайлы'))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        formats = label(tr('M4A, MP3, WAV, FLAC и другие'), "muted", True)
        formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(formats)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.browse_requested.emit()

    def dragEnterEvent(self, event):
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        paths = [path for path in paths if Path(path).is_file()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


def heading(title, subtitle=None, eyebrow=None):
    frame = QFrame()
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 8)
    layout.setSpacing(8)
    layout.addWidget(label(title, "title"))
    if subtitle:
        layout.addWidget(label(subtitle, "subtitle", True))
    return frame
