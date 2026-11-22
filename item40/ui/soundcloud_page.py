from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..soundcloud import track_url, worker
from ..tasks import TaskController
from .widgets import button, heading, label


class SoundCloudPage(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.controller = TaskController(self)
        self.controller.event.connect(self.on_event)
        self.controller.finished.connect(self.on_finished)
        self.tracks = []
        self.items = {}
        self.saved = {}
        self.failed = set()
        self.requested = []
        self.work = None
        self.mode = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(heading(tr('Скачать с SoundCloud'), tr('Сохраните трек или выбранные песни из плейлиста и альбома.')))
        row = QHBoxLayout()
        self.link = QLineEdit(placeholderText="https://soundcloud.com/…")
        self.link.returnPressed.connect(self.lookup)
        self.link.textChanged.connect(self.reset)
        self.lookup_button = button(tr('Загрузить треки'), "search", callback=self.lookup)
        row.addWidget(self.link, 1)
        row.addWidget(self.lookup_button)
        layout.addLayout(row)
        self.title = label("", "sectionTitle", True)
        layout.addWidget(self.title)
        self.list = QTreeWidget()
        self.list.setHeaderLabels([tr('Трек'), tr('Исполнитель'), tr('Длительность'), tr('Состояние')])
        self.list.setColumnWidth(0, 330)
        self.list.setColumnWidth(1, 180)
        self.list.setRootIsDecorated(False)
        self.list.itemChanged.connect(self.selection_changed)
        layout.addWidget(self.list, 1)
        selection = QHBoxLayout()
        self.all_button = button(tr('Выбрать все'), callback=lambda: self.select_all(True))
        self.none_button = button(tr('Снять выделение'), callback=lambda: self.select_all(False))
        selection.addWidget(self.all_button)
        selection.addWidget(self.none_button)
        self.count = label("", "muted")
        selection.addWidget(self.count)
        selection.addStretch()
        layout.addLayout(selection)
        formats = QHBoxLayout()
        self.search = QLineEdit(placeholderText=tr('Найти аудиоформат…'))
        self.search.textChanged.connect(self.filter_formats)
        self.targets = []
        self.format = QComboBox()
        self.format.setMinimumContentsLength(14)
        self.format.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.format.currentIndexChanged.connect(self.update_codecs)
        self.codec = QComboBox()
        self.codec.setToolTip(tr('Кодек аудио'))
        formats.addWidget(self.search)
        formats.addWidget(self.format, 1)
        formats.addWidget(self.codec)
        layout.addLayout(formats)
        self.preview = QCheckBox(tr('Разрешить ознакомительные фрагменты, если полная песня недоступна'))
        layout.addWidget(self.preview)
        folder = QHBoxLayout()
        directory = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        self.directory = QLineEdit(context.store.setting("soundcloud_output_dir", directory), readOnly=True)
        folder.addWidget(self.directory, 1)
        self.folder_button = button(tr('Выбрать папку…'), "folder", callback=self.choose_folder)
        self.open_button = button(tr('Открыть папку'), "folder", callback=self.open_folder)
        folder.addWidget(self.folder_button)
        folder.addWidget(self.open_button)
        layout.addLayout(folder)
        actions = QHBoxLayout()
        self.download_button = button(tr('Скачать выбранные'), "save", True, self.download_selected)
        self.retry_button = button(tr('Повторить неудачные'), "refresh", callback=self.retry)
        self.cancel_button = button(tr('Отменить'), "stop", callback=self.controller.cancel)
        actions.addWidget(self.download_button)
        actions.addWidget(self.retry_button)
        actions.addWidget(self.cancel_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = label("", "muted", True)
        layout.addWidget(self.status)
        self.progress = QProgressBar(textVisible=False)
        layout.addWidget(self.progress)
        self.busy(False)
        self.reset()

    def reset(self):
        if self.controller.process is not None:
            return
        self.list.clear()
        self.title.clear()
        self.tracks, self.targets, self.items, self.saved, self.failed = [], [], {}, {}, set()
        self.format.clear()
        self.status.clear()
        self.selection_changed()

    def lookup(self):
        if self.controller.process is not None:
            return
        self.reset()
        try:
            url = track_url(self.link.text())
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.mode = "inspect"
        self.busy(True)
        self.controller.start(worker, str(self.context.root), "inspect", {"url": url})

    def load_collection(self, values):
        self.title.setText(values["title"])
        self.tracks = values["tracks"]
        self.targets = values["targets"]
        for track in self.tracks:
            duration = f"{int(track.duration) // 60}:{int(track.duration) % 60:02d}" if track.duration else ""
            status = tr('Недоступно') if track.unavailable else tr('Ознакомительный фрагмент') if track.preview else ""
            item = QTreeWidgetItem([track.title, track.artist, duration, status])
            item.setData(0, Qt.ItemDataRole.UserRole, track.id)
            item.setCheckState(0, Qt.CheckState.Unchecked if track.unavailable else Qt.CheckState.Checked)
            if track.unavailable:
                item.setDisabled(True)
            self.list.addTopLevelItem(item)
            self.items[track.id] = item
        self.filter_formats()

    def filter_formats(self):
        self.format.clear()
        self.format.addItem(tr('Исходный поток'), None)
        for target in self.targets:
            if self.search.text().casefold() in target.title.casefold():
                self.format.addItem(target.title, target)
        index = next((i for i in range(self.format.count()) if getattr(self.format.itemData(i), "id", "") == "media:mp3"), 0)
        self.format.setCurrentIndex(index)

    def update_codecs(self):
        self.codec.clear()
        if target := self.format.currentData():
            for codec in target.audio_choices or (target.audio,):
                self.codec.addItem(codec, codec)
            self.codec.setCurrentIndex(max(0, self.codec.findData(target.audio)))

    def selection_changed(self, *args):
        count = sum(not item.isDisabled() and item.checkState(0) == Qt.CheckState.Checked for item in self.items.values())
        self.count.setText(tr('Выбрано {0} из {1}', count, len(self.tracks)))
        self.download_button.setEnabled(count > 0 and self.controller.process is None)

    def select_all(self, selected):
        for item in self.items.values():
            if not item.isDisabled():
                item.setCheckState(0, Qt.CheckState.Checked if selected else Qt.CheckState.Unchecked)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr('Куда сохранить песни'), self.directory.text())
        if folder:
            self.directory.setText(folder)
            self.context.store.set_setting("soundcloud_output_dir", folder)

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.directory.text()))

    def download_selected(self):
        selected = [track for track in self.tracks if not track.unavailable
                    and self.items[track.id].checkState(0) == Qt.CheckState.Checked]
        self.saved, self.failed = {}, set()
        self.start_download(selected)

    def retry(self):
        self.start_download([track for track in self.tracks if track.id in self.failed])

    def start_download(self, tracks):
        if not tracks or self.controller.process is not None:
            return
        try:
            folder = Path(self.directory.text()).resolve()
            folder.mkdir(parents=True, exist_ok=True)
            self.work = Path(tempfile.mkdtemp(prefix=".item40-soundcloud-", dir=folder))
        except OSError:
            self.status.setText(tr('Не удалось подготовить папку для сохранения.'))
            return
        self.requested = tracks
        self.failed.difference_update(track.id for track in tracks)
        self.mode = "download"
        self.busy(True)
        params = {"tracks": tracks, "target": self.format.currentData(), "audio_codec": self.codec.currentData(),
                  "allow_preview": self.preview.isChecked(), "work": str(self.work), "output": str(folder)}
        self.controller.start(worker, str(self.context.root), "download", params)

    def on_event(self, kind, values):
        if kind == "inspected":
            self.load_collection(values)
        elif kind == "progress":
            self.status.setText(values["stage"])
            fraction = values["progress"]
            self.progress.setRange(0, 0 if fraction is None else 1000)
            if fraction is not None:
                self.progress.setValue(round(fraction * 1000))
        elif kind == "started":
            self.items[values["id"]].setText(3, tr('Скачивание…'))
        elif kind == "saved":
            self.saved[values["id"]] = values["result"]
            self.failed.discard(values["id"])
            self.items[values["id"]].setText(3, tr('Готово'))
            self.items[values["id"]].setToolTip(3, str(values["result"]))
        elif kind == "file_failed":
            self.failed.add(values["id"])
            self.items[values["id"]].setText(3, tr('Ошибка'))
            self.items[values["id"]].setToolTip(3, values["error"])

    def on_finished(self, kind, values):
        if self.mode == "download":
            for track in self.requested:
                if track.id not in self.saved:
                    self.failed.add(track.id)
        self.cleanup()
        self.busy(False)
        if kind == "failed":
            self.status.setText(values.get("error", tr('Ошибка загрузки.')))
        elif kind == "cancelled":
            self.status.setText(tr('Отменено'))
        elif self.mode == "download":
            self.status.setText(tr('Сохранено {0} · Осталось {1}', len(self.saved), len(self.failed)))
        else:
            self.status.setText(tr('Выберите песни и формат скачивания.'))
        self.selection_changed()

    def busy(self, busy):
        for control in (self.link, self.lookup_button, self.list, self.all_button, self.none_button, self.format,
                        self.search, self.codec, self.preview, self.folder_button, self.retry_button):
            control.setEnabled(not busy)
        self.download_button.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)
        self.cancel_button.setVisible(busy)

    def cleanup(self):
        if self.work:
            shutil.rmtree(self.work, ignore_errors=True)
            self.work = None

    def shutdown(self):
        self.controller.shutdown()
        self.cleanup()
