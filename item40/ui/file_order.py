from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from .widgets import button, label


class FileOrderDialog(QDialog):
    def __init__(self, paths, parent=None, *, editable=True, accept_text="Объединить"):
        super().__init__(parent)
        self.setWindowTitle("Порядок файлов")
        self.resize(580, 420)
        layout = QVBoxLayout(self)
        if editable:
            layout.addWidget(label("Порядок: сверху вниз. Строки можно перетаскивать.", "muted"))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        if editable:
            self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        for path in paths:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.list.addItem(item)
        layout.addWidget(self.list, 1)
        if editable:
            controls = QHBoxLayout()
            self.up = button("Вверх", callback=lambda: self.move(-1))
            self.down = button("Вниз", callback=lambda: self.move(1))
            controls.addWidget(self.up)
            controls.addWidget(self.down)
            controls.addStretch()
            layout.addLayout(controls)
            self.list.currentRowChanged.connect(self.update_controls)
        buttons = QDialogButtonBox()
        if editable:
            confirm = buttons.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole)
            confirm.clicked.connect(self.accept)
            buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        else:
            buttons.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole).clicked.connect(self.reject)
        layout.addWidget(buttons)
        self.list.setCurrentRow(0)
        if editable:
            self.update_controls()

    def paths(self):
        return [self.list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.list.count())]

    def move(self, direction):
        current = self.list.currentRow()
        target = current + direction
        if current >= 0 and 0 <= target < self.list.count():
            item = self.list.takeItem(current)
            self.list.insertItem(target, item)
            self.list.setCurrentRow(target)
        self.update_controls()

    def update_controls(self, *_):
        row = self.list.currentRow()
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < self.list.count() - 1)
