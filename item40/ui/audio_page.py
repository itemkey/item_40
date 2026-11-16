from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QLocale, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLayout,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..domain import AUDIO_FILTER, MODEL_LABELS, STATUS_LABELS, job_files, result_stem, source_label
from ..exports import output_directory, save_result, write_text_atomic
from .file_order import FileOrderDialog
from .theme import icon
from .transcript_editor import TranscriptEditor
from .widgets import DropZone, button, heading, label, panel


class AudioPage(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.store = context.store
        self.manager = context.manager
        self.selected_id = None
        self.items = {}
        self.dirty = False
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.flush_edit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        layout.addWidget(heading("Аудио → текст"))
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(18)
        layout.addWidget(splitter, 1)

        left, left_layout = panel()
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(8)
        left.setMinimumWidth(330)
        left.setMaximumWidth(480)
        input_body = QWidget()
        input_layout = QVBoxLayout(input_body)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(8)
        input_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        left_scroll = QScrollArea()
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(input_body)
        left_layout.addWidget(left_scroll, 1)
        title_row = QHBoxLayout()
        title_row.addWidget(label("Файлы", "sectionTitle"))
        title_row.addStretch()
        title_row.addWidget(button("Добавить", callback=self.browse))
        self.remove_button = button("Убрать", callback=self.remove_selected)
        self.remove_button.setToolTip("Убрать выбранные записи из списка. Файлы на диске не удаляются.")
        title_row.addWidget(self.remove_button)
        input_layout.addLayout(title_row)
        self.queue_count = label("0 файлов", "muted")
        self.drop = DropZone()
        self.drop.browse_requested.connect(self.browse)
        self.drop.files_dropped.connect(self.add_files)
        input_layout.addWidget(self.drop)

        options = QHBoxLayout()
        quality_column = QVBoxLayout()
        quality_column.addWidget(label("Качество", "muted"))
        self.quality = QComboBox()
        for key, text in MODEL_LABELS.items():
            self.quality.addItem(text, key)
        self.quality.setCurrentIndex(max(0, self.quality.findData(self.store.setting("model", "small"))))
        self.quality.setToolTip("small: загрузка около 0,5 ГБ. large-v3: около 3,1 ГБ. Модель скачивается один раз.")
        self.quality.currentIndexChanged.connect(lambda: self.store.set_setting("model", self.quality.currentData()))
        quality_column.addWidget(self.quality)
        options.addLayout(quality_column, 1)
        language_column = QVBoxLayout()
        language_column.addWidget(label("Язык записи", "muted"))
        self.language = QComboBox()
        self.language.addItem("Определить", None)
        self.language.addItem("Русский", "ru")
        self.language.addItem("English", "en")
        # All multilingual Whisper languages are available without a separate service.
        from faster_whisper.tokenizer import _LANGUAGE_CODES
        for code in _LANGUAGE_CODES:
            if code not in {"ru", "en"}:
                locale = QLocale(code)
                name = locale.nativeLanguageName() if locale.language() != QLocale.Language.C else code
                self.language.addItem(f"{name.capitalize()} ({code})", code)
        self.language.setCurrentIndex(max(0, self.language.findData(self.store.setting("language"))))
        self.language.currentIndexChanged.connect(lambda: self.store.set_setting("language", self.language.currentData()))
        language_column.addWidget(self.language)
        options.addLayout(language_column, 1)
        input_layout.addLayout(options)
        group_controls = QHBoxLayout()
        self.combine_button = button("Объединить…", callback=self.combine_selected)
        self.combine_button.setToolTip("Одна расшифровка для выбранных файлов. Ctrl+A — выбрать все.")
        group_controls.addWidget(self.combine_button)
        group_controls.addStretch()
        input_layout.addLayout(group_controls)
        self.list = QListWidget()
        self.list.setMinimumHeight(60)
        self.list.setSpacing(1)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.currentItemChanged.connect(self.selection_changed)
        self.list.itemSelectionChanged.connect(self.update_remove_button)
        self.list.itemDoubleClicked.connect(lambda item: self.edit_order(item.data(Qt.ItemDataRole.UserRole)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.source_menu)
        remove_action = QAction(self.list)
        remove_action.setShortcut("Delete")
        remove_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        remove_action.triggered.connect(self.remove_selected)
        self.list.addAction(remove_action)
        input_layout.addWidget(self.list, 1)
        self.empty_queue = label("Список пуст", "muted")
        input_layout.addWidget(self.empty_queue, 1)
        input_layout.addWidget(self.queue_count)
        self.queue_progress = QProgressBar()
        self.queue_progress.setRange(0, 1000)
        self.queue_progress.setTextVisible(False)
        left_layout.addWidget(self.queue_progress)
        self.stage = label("Готово к работе", "muted", True)
        self.stage.setMinimumHeight(24)
        left_layout.addWidget(self.stage)
        actions = QHBoxLayout()
        self.run_button = button("Расшифровать", "play", True, self.start)
        self.run_button.setMinimumHeight(42)
        actions.addWidget(self.run_button, 1)
        self.cancel_button = button("", "stop", callback=self.cancel_selected)
        self.cancel_button.setToolTip("Отменить выбранную задачу")
        self.cancel_button.setMinimumHeight(42)
        actions.addWidget(self.cancel_button)
        self.retry_button = button("", "refresh", callback=self.retry_selected)
        self.retry_button.setToolTip("Повторить выбранную задачу")
        self.retry_button.setMinimumHeight(42)
        actions.addWidget(self.retry_button)
        left_layout.addLayout(actions)
        splitter.addWidget(left)

        right, right_layout = panel()
        right.setMinimumWidth(390)
        editor_header = QHBoxLayout()
        editor_title = QVBoxLayout()
        editor_title.addWidget(label("Текст расшифровки", "sectionTitle"))
        self.filename = label("", "muted")
        self.filename.setMaximumWidth(440)
        editor_title.addWidget(self.filename)
        editor_header.addLayout(editor_title, 1)
        self.copy_button = button("", "copy", callback=self.copy)
        self.copy_button.setToolTip("Копировать текст")
        self.export_button = button("Сохранить как…", callback=self.export)
        editor_header.addWidget(self.copy_button)
        editor_header.addWidget(self.export_button)
        right_layout.addLayout(editor_header)
        self.result_stack = QStackedWidget()
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.addStretch()
        self.empty_hint = label("Выберите файл", "muted")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_layout.addWidget(self.empty_hint)
        placeholder_layout.addStretch()
        self.result_stack.addWidget(placeholder)
        self.editor = TranscriptEditor()
        self.editor.setTabChangesFocus(True)
        self.editor.textChanged.connect(self.on_edit)
        self.result_stack.addWidget(self.editor)
        right_layout.addWidget(self.result_stack, 1)
        self.error = label("", "accent", True)
        self.error.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error.hide()
        right_layout.addWidget(self.error)
        footer = QHBoxLayout()
        self.char_count = label("0 символов", "muted")
        self.saved_hint = label("", "muted")
        footer.addWidget(self.char_count)
        footer.addStretch()
        footer.addWidget(self.saved_hint)
        right_layout.addLayout(footer)
        splitter.addWidget(right)
        splitter.setSizes([370, 680])
        splitter.setStretchFactor(1, 1)

        self.manager.changed.connect(self.refresh)
        self.refresh()

    def browse(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите записи", "", AUDIO_FILTER)
        self.add_files(paths)

    def add_files(self, paths):
        paths = [str(Path(path).resolve()) for path in paths if Path(path).is_file()]
        if not paths:
            return
        ids = self.manager.enqueue(paths, self.quality.currentData(), self.language.currentData(),
                                   self.store.setting("device", "auto"))
        self.refresh()
        self.list.clearSelection()
        self.list.setCurrentItem(self.items[ids[0]], QItemSelectionModel.SelectionFlag.NoUpdate)
        for job_id in ids:
            self.items[job_id].setSelected(True)
        self.selected_id = ids[0]
        self.update_result()
        self.update_remove_button()

    def start(self):
        if not self.store.pending():
            self.browse()
        if self.store.pending():
            self.store.configure_pending(self.quality.currentData(), self.language.currentData(),
                                         self.store.setting("device", "auto"))
            self.manager.start()
        self.refresh()

    def cancel_selected(self):
        if self.selected_id:
            self.manager.cancel(self.selected_id)

    def update_remove_button(self):
        items = self.list.selectedItems()
        self.remove_button.setEnabled(bool(items))
        jobs = [self.store.get(item.data(Qt.ItemDataRole.UserRole)) for item in items]
        self.combine_button.setEnabled(bool(jobs) and all(job and job["status"] != "running" for job in jobs)
                                       and sum(len(job_files(job)) for job in jobs if job) >= 2)

    def combine_selected(self):
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
        jobs = [self.store.get(job_id) for job_id in ids]
        if not jobs or any(not job or job["status"] == "running" for job in jobs):
            return
        paths = [path for job in jobs for path in job_files(job)]
        if len(paths) < 2:
            return
        dialog = FileOrderDialog(paths, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.flush_edit()
            try:
                job_id = self.manager.combine_sources(ids, dialog.paths(), self.quality.currentData(),
                    self.language.currentData(), self.store.setting("device", "auto"))
            except ValueError as error:
                self.context.show_error("Не удалось объединить", str(error))
                return
            self.refresh()
            self.select(job_id)

    def edit_order(self, job_id):
        job = self.store.get(job_id)
        if not job or len(job_files(job)) < 2:
            return
        editable = job["status"] == "queued"
        dialog = FileOrderDialog(job_files(job), self, editable=editable, accept_text="Сохранить")
        if dialog.exec() == QDialog.DialogCode.Accepted and editable:
            try:
                self.store.reorder_sources(job_id, dialog.paths())
            except ValueError as error:
                self.context.show_error("Порядок файлов", str(error))
                return
            self.refresh(job_id)

    def source_menu(self, position):
        if not self.list.selectedItems():
            return
        menu = QMenu(self)
        current = self.list.currentItem()
        if current:
            job_id = current.data(Qt.ItemDataRole.UserRole)
            job = self.store.get(job_id)
            if job and len(job_files(job)) > 1:
                menu.addAction("Порядок файлов…", lambda: self.edit_order(job_id))
        menu.addAction("Убрать из списка", self.remove_selected)
        menu.exec(self.list.viewport().mapToGlobal(position))

    def remove_selected(self):
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
        if not ids:
            return
        self.flush_edit()
        if self.selected_id in ids:
            self.selected_id = None
        self.manager.remove_sources(ids)
        self.refresh()

    def open_result(self, job_id):
        self.flush_edit()
        if job_id in self.items:
            self.select(job_id)
        else:
            self.list.clearSelection()
            self.selected_id = job_id
            self.update_result()

    def retry_selected(self):
        if self.selected_id:
            self.flush_edit()
            self.manager.retry(self.selected_id)
            self.manager.start()

    def select(self, job_id):
        if job_id in self.items:
            self.list.setCurrentItem(self.items[job_id])

    def selection_changed(self, current, previous):
        self.flush_edit()
        self.selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.update_result()

    def refresh(self, job_id=""):
        jobs = self.store.source_jobs()
        visible_ids = {job["id"] for job in jobs}
        self.list.blockSignals(True)
        for removed in set(self.items) - visible_ids:
            item = self.items.pop(removed)
            self.list.takeItem(self.list.row(item))
            if removed == self.selected_id:
                self.selected_id = None
        for job in jobs:
            item = self.items.get(job["id"])
            if item is None:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, job["id"])
                self.items[job["id"]] = item
                self.list.addItem(item)
            percent = f" · {job['progress']:.0%}" if job["status"] == "running" else ""
            item.setText(f"{source_label(job)}\n{STATUS_LABELS[job['status']]}{percent}")
            item.setIcon(icon("check" if job["status"] == "completed" else "audio",
                              "#aaaaaa"))
            item.setToolTip("\n".join(job_files(job)) + "\n" + job["stage"])
        self.list.blockSignals(False)
        pending = len(self.store.pending())
        active = self.store.get(self.manager.active) if self.manager.active and not self.manager.download_only else None
        self.queue_count.setText(f"Файлов: {sum(len(job_files(job)) for job in jobs)}")
        self.empty_queue.setVisible(not jobs)
        self.list.setVisible(bool(jobs))
        self.update_remove_button()
        self.run_button.setEnabled(not self.manager.download_only)
        self.run_button.setText("Очередь запущена" if self.manager.enabled and active else "Расшифровать")
        if active:
            self.queue_progress.setValue(int(active["progress"] * 1000))
            self.stage.setText(active["stage"])
        else:
            self.queue_progress.setValue(0)
            self.stage.setText(f"Ожидают запуска: {pending}" if pending else "Готово к работе")
        if not self.selected_id and self.list.count():
            self.list.setCurrentRow(0)
            if not self.selected_id:
                self.selected_id = self.list.item(0).data(Qt.ItemDataRole.UserRole)
        if not job_id or job_id == self.selected_id:
            self.update_result()

    def update_result(self):
        job = self.store.get(self.selected_id) if self.selected_id else None
        text = job["transcript"] if job else ""
        self.filename.setText(source_label(job) if job else "")
        self.filename.setToolTip("\n".join(job_files(job)) if job else "")
        if not self.dirty:
            self.editor.set_snapshot(text, self.selected_id)
        running = bool(job and job["status"] in {"queued", "running"})
        self.editor.setReadOnly(not job or running)
        self.result_stack.setCurrentIndex(1 if text or (job and not running) else 0)
        self.empty_hint.setText("Распознавание…"
                               if job and job["status"] == "running" else
                               "Ожидает запуска" if job else "Выберите файл")
        self.char_count.setText(f"{len(self.editor.toPlainText()):,} символов".replace(",", " "))
        self.saved_hint.setText("TXT сохранён" if job and job["output_path"] and not job["output_error"] else "")
        self.saved_hint.setToolTip(job["output_path"] if job else "")
        self.copy_button.setEnabled(bool(text))
        self.export_button.setEnabled(bool(text))
        self.cancel_button.setEnabled(bool(job and job["status"] in {"queued", "running"}))
        self.retry_button.setEnabled(bool(job and job["status"] in {"failed", "cancelled", "interrupted"}))
        errors = "\n".join(filter(None, (job["error"], job["output_error"]))) if job else ""
        self.error.setText(errors)
        self.error.setVisible(bool(errors))
        if job and job["status"] == "completed" and not text:
            self.editor.setPlaceholderText("В этой записи речь не обнаружена.")
        else:
            self.editor.setPlaceholderText("Введите или исправьте текст…")

    def on_edit(self):
        if self.selected_id and not self.editor.isReadOnly():
            self.dirty = True
            self.save_timer.start()
            text = self.editor.toPlainText()
            self.char_count.setText(f"{len(text)} символов")
            self.copy_button.setEnabled(bool(text))
            self.export_button.setEnabled(bool(text))

    def flush_edit(self):
        self.save_timer.stop()
        if self.dirty and self.selected_id:
            self.store.update(self.selected_id, transcript=self.editor.toPlainText(), edited=1)
            save_result(self.store, self.selected_id)
        self.dirty = False
        if self.selected_id:
            self.update_result()

    def copy(self):
        QApplication.clipboard().setText(self.editor.toPlainText())
        self.context.show_notice("Текст скопирован")

    def export(self):
        if not self.selected_id:
            return
        job = self.store.get(self.selected_id)
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить текст",
                                             str(output_directory(self.store) / (result_stem(job) + ".txt")),
                                             "Текст UTF-8 (*.txt)")
        if path:
            try:
                write_text_atomic(Path(path), self.editor.toPlainText())
                self.context.show_notice("Текст сохранён: " + path)
            except OSError as error:
                self.context.show_error("Не удалось сохранить текст", str(error))
