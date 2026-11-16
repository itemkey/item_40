from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class TranscriptEditor(QPlainTextEdit):
    """Stream text without moving a reader who has scrolled away from the end."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._document_key = object()
        self._following_tail = True
        self._updating = False
        self._scroll_generation = 0
        self._pending_restore = None
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore_position)
        self.verticalScrollBar().valueChanged.connect(self._scroll_changed)
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)

    def _scroll_changed(self, value):
        if self._updating:
            return
        self._following_tail = value == self.verticalScrollBar().maximum()
        self._scroll_generation += 1
        self._pending_restore = None
        self._restore_timer.stop()

    def _range_changed(self, *_):
        if not self._updating and self._following_tail:
            self._queue_restore(None, self.horizontalScrollBar().value())

    def _queue_restore(self, position, horizontal):
        self._pending_restore = (self._scroll_generation, position, horizontal)
        self._restore_timer.start(0)

    def _restore_position(self):
        pending = self._pending_restore
        self._pending_restore = None
        if pending is None or pending[0] != self._scroll_generation:
            return
        _, position, horizontal = pending
        self._updating = True
        try:
            scroll = self.verticalScrollBar()
            scroll.setValue(scroll.maximum() if position is None else position)
            self.horizontalScrollBar().setValue(horizontal)
        finally:
            self._updating = False

    def set_snapshot(self, text, document_key):
        previous_text = self.toPlainText()
        same_document = document_key == self._document_key
        if same_document and text == previous_text:
            return
        scroll = self.verticalScrollBar()
        follow = not same_document or scroll.maximum() == 0 or self._following_tail
        position = scroll.value()
        horizontal = self.horizontalScrollBar().value()
        current = self.textCursor()
        cursor_position, anchor = (current.position(), current.anchor()) if same_document else (0, 0)
        signals_blocked = self.blockSignals(True)
        undo_enabled = self.isUndoRedoEnabled()
        self._updating = True
        try:
            self.setUndoRedoEnabled(False)
            if same_document and text.startswith(previous_text):
                cursor = QTextCursor(self.document())
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(text[len(previous_text):])
            else:
                self.setPlainText(text)
            limit = max(0, self.document().characterCount() - 1)
            cursor = QTextCursor(self.document())
            cursor.setPosition(min(anchor, limit))
            cursor.setPosition(min(cursor_position, limit), QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
            scroll.setValue(scroll.maximum() if follow else position)
            self.horizontalScrollBar().setValue(horizontal)
        finally:
            self.setUndoRedoEnabled(undo_enabled)
            self.blockSignals(signals_blocked)
            self._updating = False
        self._document_key = document_key
        self._following_tail = follow
        # Qt can finish wrapping/layout after the document update. A user scroll
        # cancels this deferred restoration instead of getting overridden by it.
        self._queue_restore(None if follow else position, horizontal)
