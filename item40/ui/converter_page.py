from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..converters import GROUP_TITLES, convert_worker, inspect_worker
from ..i18n import tr
from ..tasks import TaskController
from .widgets import button, heading, label


class ConverterPage(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.entries = {}
        self.current = None
        self.work = None
        self.mode = None
        self.loading = False
        self.controller = TaskController(self)
        self.controller.event.connect(self.on_event)
        self.controller.finished.connect(self.on_finished)
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(heading(tr('Конвертеры'), tr('Добавьте файлы и выберите доступный выходной формат.')))
        controls = QHBoxLayout()
        self.add_button = button(tr('Добавить файлы…'), "file", callback=self.browse)
        self.remove_button = button(tr('Убрать'), callback=self.remove_selected)
        self.catalog_button = button(tr('Поддерживаемые форматы'), callback=self.show_catalog)
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        controls.addWidget(self.catalog_button)
        controls.addStretch()
        layout.addLayout(controls)
        splitter = QSplitter()
        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr('Файл'), tr('Формат'), tr('Состояние')])
        self.list.setRootIsDecorated(False)
        self.list.setColumnWidth(0, 225)
        self.list.setColumnWidth(1, 70)
        self.list.currentItemChanged.connect(self.select_entry)
        splitter.addWidget(self.list)
        options = QWidget()
        form_layout = QVBoxLayout(options)
        form_layout.setContentsMargins(10, 0, 0, 0)
        self.source_type = label("", "muted")
        form_layout.addWidget(self.source_type)
        self.search = QLineEdit(placeholderText=tr('Найти формат…'))
        self.search.textChanged.connect(self.filter_formats)
        form_layout.addWidget(self.search)
        self.target = QComboBox()
        self.target.setMinimumContentsLength(14)
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.currentIndexChanged.connect(self.target_changed)
        form_layout.addWidget(self.target)
        self.advanced = QCheckBox(tr('Расширенные настройки'))
        form_layout.addWidget(self.advanced)
        self.extra = QWidget()
        form = QFormLayout(self.extra)
        self.video_codec = QComboBox()
        self.audio_codec = QComboBox()
        self.quality = QSpinBox(minimum=1, maximum=100, value=90)
        self.bitrate = QSpinBox(minimum=0, maximum=1536, value=0, specialValueText=tr('Автоматически'), suffix=" kbps")
        self.width = QSpinBox(minimum=0, maximum=16384, value=0, specialValueText=tr('Исходный размер'), suffix=" px")
        self.fps = QSpinBox(minimum=0, maximum=240, value=0, specialValueText=tr('Автоматически'))
        self.frame = QSpinBox(minimum=0, maximum=100000, value=0)
        self.background = QLineEdit("white")
        self.ocr = QCheckBox(tr('Распознавать страницы без текста'))
        self.ocr.setChecked(True)
        self.ocr_language = QComboBox()
        for name, code in ((tr('Русский + English'), "rus+eng"), (tr('Русский'), "rus"), ("English", "eng")):
            self.ocr_language.addItem(name, code)
        for title, control in ((tr('Кодек видео'), self.video_codec), (tr('Кодек аудио'), self.audio_codec),
                               (tr('Качество изображения'), self.quality), (tr('Битрейт аудио'), self.bitrate),
                               (tr('Ширина'), self.width), (tr('Кадров в секунду'), self.fps), (tr('Номер кадра'), self.frame),
                               (tr('Фон без прозрачности'), self.background), ("OCR", self.ocr),
                               (tr('Язык OCR'), self.ocr_language)):
            form.addRow(title, control)
        form_layout.addWidget(self.extra)
        self.extra.hide()
        self.advanced.toggled.connect(self.extra.setVisible)
        self.apply_button = button(tr('Применить к совместимым файлам'), callback=self.apply_to_all)
        form_layout.addWidget(self.apply_button)
        form_layout.addStretch()
        splitter.addWidget(options)
        splitter.setSizes([490, 460])
        layout.addWidget(splitter, 1)
        row = QHBoxLayout()
        directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        self.directory = QLineEdit(context.store.setting("converter_output_dir", str(Path(directory) / "item-40")), readOnly=True)
        row.addWidget(self.directory, 1)
        self.folder_button = button(tr('Выбрать папку…'), "folder", callback=self.choose_folder)
        self.open_button = button(tr('Открыть папку'), "folder", callback=self.open_folder)
        row.addWidget(self.folder_button)
        row.addWidget(self.open_button)
        layout.addLayout(row)
        actions = QHBoxLayout()
        self.run_button = button(tr('Конвертировать'), "play", True, self.start)
        self.retry_button = button(tr('Повторить неудачные'), "refresh", callback=self.retry)
        self.cancel_button = button(tr('Отменить'), "stop", callback=self.controller.cancel)
        actions.addWidget(self.run_button)
        actions.addWidget(self.retry_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = label("", "muted", True)
        layout.addWidget(self.status)
        self.progress = QProgressBar(textVisible=False)
        layout.addWidget(self.progress)
        self.options_panel = options
        self.busy(False)

    def browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, tr('Выберите файлы для конвертации'))
        self.add_files(files)

    def add_files(self, files):
        if self.controller.process is not None:
            return
        added = []
        for filename in files:
            path = str(Path(filename).resolve())
            if not Path(path).is_file() or path in self.entries:
                continue
            item = QTreeWidgetItem([Path(path).name, "", tr('Подготовка…')])
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            item.setToolTip(0, path)
            self.list.addTopLevelItem(item)
            self.entries[path] = {"item": item, "targets": [], "target": None, "options": {}, "state": "queued"}
            added.append(path)
        if added:
            self.mode = "inspect"
            self.busy(True)
            self.controller.start(inspect_worker, str(self.context.root), added)

    def select_entry(self, current, previous=None):
        self.store_options()
        self.current = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        self.loading = True
        self.search.clear()
        self.filter_formats()
        entry = self.entries.get(self.current)
        if entry:
            self.source_type.setText(GROUP_TITLES.get(entry.get("group"), ""))
            options = entry["options"]
            for key, control, default in (("quality", self.quality, 90), ("bitrate", self.bitrate, 0),
                                          ("width", self.width, 0), ("fps", self.fps, 0), ("frame", self.frame, 0)):
                control.setValue(options.get(key, default))
            self.background.setText(options.get("background", "white"))
            self.ocr.setChecked(options.get("ocr", True))
            self.ocr_language.setCurrentIndex(max(0, self.ocr_language.findData(options.get("ocr_language", "rus+eng"))))
        self.loading = False

    def filter_formats(self):
        entry = self.entries.get(self.current)
        self.target.blockSignals(True)
        self.target.clear()
        if entry:
            for target in entry["targets"]:
                if self.search.text().casefold() in target.title.casefold():
                    self.target.addItem(target.title, target)
            index = next((i for i in range(self.target.count()) if self.target.itemData(i) == entry["target"]), 0)
            self.target.setCurrentIndex(index)
        self.target.blockSignals(False)
        self.target_changed()

    def target_changed(self):
        entry = self.entries.get(self.current)
        target = self.target.currentData()
        if not entry or not target:
            return
        entry["target"] = target
        entry["item"].setText(1, target.extension.upper())
        for combo, choices, chosen in ((self.video_codec, target.video_choices, target.video),
                                       (self.audio_codec, target.audio_choices, target.audio)):
            combo.clear()
            for codec in choices or ((chosen,) if chosen else ()):
                combo.addItem(codec, codec)
            saved = entry["options"].get("video_codec" if combo is self.video_codec else "audio_codec")
            index = combo.findData(saved or chosen)
            combo.setCurrentIndex(max(0, index))

    def store_options(self):
        if self.loading or self.current not in self.entries:
            return
        self.entries[self.current]["options"] = {
            "quality": self.quality.value(), "bitrate": self.bitrate.value(), "width": self.width.value(),
            "fps": self.fps.value(), "frame": self.frame.value(), "background": self.background.text(),
            "ocr": self.ocr.isChecked(), "ocr_language": self.ocr_language.currentData(),
            "video_codec": self.video_codec.currentData() or "", "audio_codec": self.audio_codec.currentData() or "",
        }

    def apply_to_all(self):
        self.store_options()
        chosen = self.entries.get(self.current)
        if not chosen or not chosen["target"]:
            return
        for entry in self.entries.values():
            target = next((target for target in entry["targets"] if target.id == chosen["target"].id), None)
            if target:
                entry.update(target=target, options=dict(chosen["options"]))
                entry["item"].setText(1, target.extension.upper())

    def remove_selected(self):
        if self.controller.process is None and self.current:
            entry = self.entries.pop(self.current)
            self.current = None
            self.list.takeTopLevelItem(self.list.indexOfTopLevelItem(entry["item"]))

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr('Папка результатов'), self.directory.text())
        if folder:
            self.directory.setText(folder)
            self.context.store.set_setting("converter_output_dir", folder)

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.directory.text()))

    def show_catalog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('Поддерживаемые форматы'))
        dialog.resize(650, 500)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(readOnly=True)
        lines = []
        for path, entry in self.entries.items():
            lines.append(Path(path).name)
            lines.extend(f"  {target.title} (.{target.extension})" for target in entry["targets"])
        text.setPlainText("\n".join(lines) or tr('Добавьте файл, чтобы загрузить список совместимых форматов.'))
        layout.addWidget(text)
        dialog.exec()

    def retry(self):
        for entry in self.entries.values():
            if entry["state"] in {"failed", "cancelled"}:
                entry["state"] = "queued"
        missing = [path for path, entry in self.entries.items() if not entry["targets"]]
        if missing:
            self.mode = "inspect"
            self.busy(True)
            self.controller.start(inspect_worker, str(self.context.root), missing)
        else:
            self.start()

    def start(self):
        self.store_options()
        requests = [(path, entry["target"], entry["options"]) for path, entry in self.entries.items()
                    if entry["target"] and entry["state"] != "completed"]
        if not requests or self.controller.process is not None:
            return
        try:
            folder = Path(self.directory.text()).resolve()
            folder.mkdir(parents=True, exist_ok=True)
            self.work = Path(tempfile.mkdtemp(prefix=".item40-convert-", dir=folder))
        except OSError:
            self.status.setText(tr('Не удалось подготовить папку результатов.'))
            return
        self.mode = "convert"
        self.busy(True)
        self.controller.start(convert_worker, str(self.context.root), requests, str(self.work), str(folder))

    def on_event(self, kind, values):
        if kind == "progress":
            self.status.setText(values["stage"])
            fraction = values["progress"]
            self.progress.setRange(0, 0 if fraction is None else 1000)
            if fraction is not None:
                self.progress.setValue(round(fraction * 1000))
            return
        entry = self.entries.get(values.get("path"))
        if not entry:
            return
        item = entry["item"]
        if kind == "inspected":
            targets = values["targets"]
            if not targets:
                item.setText(2, tr('Нет доступных преобразований'))
                entry["state"] = "failed"
                return
            preferred = next((target for target in targets if target.id == "image:png"), targets[0])
            entry.update(targets=targets, target=preferred, group=values["group"], state="queued")
            item.setText(1, preferred.extension.upper())
            item.setText(2, tr('В очереди'))
        elif kind == "started":
            entry["state"] = "running"
            item.setText(2, tr('Обработка…'))
        elif kind == "saved":
            entry.update(state="completed", result=values["result"])
            item.setText(2, tr('Готово'))
            item.setToolTip(2, str(values["result"]))
        elif kind == "file_failed":
            entry["state"] = "failed"
            item.setText(2, tr('Ошибка'))
            item.setToolTip(2, values["error"])
            self.status.setText(values["error"])

    def on_finished(self, kind, values):
        for entry in self.entries.values():
            if entry["state"] == "running":
                entry["state"] = "cancelled" if kind == "cancelled" else "failed"
                entry["item"].setText(2, tr('Отменено') if kind == "cancelled" else tr('Ошибка'))
        self.cleanup()
        self.busy(False)
        if kind == "failed":
            self.status.setText(values.get("error", tr('Ошибка обработки.')))
        elif kind == "cancelled":
            self.status.setText(tr('Отменено'))
        elif self.mode == "convert":
            done = sum(entry["state"] == "completed" for entry in self.entries.values())
            failed = sum(entry["state"] == "failed" for entry in self.entries.values())
            self.status.setText(tr('Готово {0} · Ошибки {1}', done, failed))
        else:
            self.select_entry(self.list.currentItem())
            if self.list.currentItem() is None and self.list.topLevelItemCount():
                self.list.setCurrentItem(self.list.topLevelItem(0))

    def busy(self, busy):
        for control in (self.add_button, self.remove_button, self.folder_button, self.run_button,
                        self.retry_button, self.options_panel, self.list):
            control.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)

    def cleanup(self):
        if self.work:
            shutil.rmtree(self.work, ignore_errors=True)
            self.work = None

    def shutdown(self):
        self.controller.shutdown()
        self.cleanup()

    def dragEnterEvent(self, event):
        if self.controller.process is None and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()
