from __future__ import annotations

import multiprocessing as mp
import queue
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..youtube import AUDIO_FORMATS, VIDEO_FORMATS, Format, Selection, save_download, video_url, worker
from .widgets import button, heading, label, panel


class YouTubePage(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.mp = mp.get_context("spawn")
        self.process = None
        self.events = None
        self.cancel_event = None
        self.cancel_time = None
        self.work_dir = None
        self.video = None
        self.muxers = []
        self.result = None
        self.dead_since = None
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self.poll)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(heading(tr('Скачать с YouTube'), tr('Видео или аудио по ссылке на ролик.')))

        frame, link_panel = panel()
        self.link = QLineEdit(placeholderText="https://www.youtube.com/watch?v=…")
        self.link.setAccessibleName(tr('Ссылка на ролик YouTube'))
        self.link.returnPressed.connect(self.lookup)
        self.link.textChanged.connect(self.reset_link)
        self.lookup_button = button(tr('Загрузить форматы'), "search", callback=self.lookup)
        row = QHBoxLayout()
        row.addWidget(self.link, 1)
        row.addWidget(self.lookup_button)
        link_panel.addLayout(row)
        link_panel.addWidget(label(tr('При первом использовании приложение скачает компоненты (около 166 МБ).'),
                                   "muted", True))
        layout.addWidget(frame)

        self.options, format_panel = panel()
        self.title = label("", "sectionTitle", True)
        format_panel.addWidget(self.title)
        self.advanced = QCheckBox(tr('Расширенный режим'))
        format_panel.addWidget(self.advanced)
        self.form = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem(tr('Видео'), "video")
        self.kind.addItem(tr('Только аудио'), "audio")
        self.advanced_kind = QComboBox()
        self.advanced_kind.addItem(tr('Исходный поток YouTube'), "stream")
        self.advanced_kind.addItem(tr('Конвертация FFmpeg'), "convert")
        self.format = QComboBox()
        self.stream = QComboBox()
        self.muxer = QComboBox()
        for combo in (self.format, self.stream, self.muxer):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.video_codec = QComboBox()
        self.audio_codec = QComboBox()
        self.quality = QComboBox()
        for title, widget in ((tr('Тип файла'), self.kind), (tr('Режим'), self.advanced_kind), (tr('Формат'), self.format),
                              (tr('Поток'), self.stream), (tr('Контейнер'), self.muxer), (tr('Кодек видео'), self.video_codec),
                              (tr('Кодек аудио'), self.audio_codec), (tr('Разрешение'), self.quality)):
            widget.setAccessibleName(title)
            self.form.addRow(title, widget)

        downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        directory = context.store.setting("youtube_download_dir", downloads or str(Path.home() / "Downloads"))
        folder_row = QHBoxLayout()
        self.directory = QLineEdit(directory, readOnly=True)
        self.directory.setAccessibleName(tr('Папка для скачивания'))
        folder_row.addWidget(self.directory, 1)
        folder_row.addWidget(button(tr('Выбрать…'), "folder", callback=self.choose_folder))
        self.form.addRow(tr('Папка'), folder_row)
        format_panel.addLayout(self.form)
        self.download_button = button(tr('Скачать'), "save", True, self.start_download)
        format_panel.addWidget(self.download_button)
        layout.addWidget(self.options)
        self.options.hide()

        self.status = label("", "muted", True)
        layout.addWidget(self.status)
        self.progress = QProgressBar(textVisible=False)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.result_controls = QWidget()
        actions = QHBoxLayout(self.result_controls)
        actions.setContentsMargins(0, 0, 0, 0)
        self.open_folder_button = button(tr('Открыть папку'), "folder", callback=self.open_folder)
        self.transcribe_button = button(tr('Добавить в расшифровку'), "audio", callback=self.transcribe)
        actions.addWidget(self.open_folder_button)
        actions.addWidget(self.transcribe_button)
        actions.addStretch()
        self.result_controls.hide()
        layout.addWidget(self.result_controls)
        self.cancel_button = button(tr('Отменить'), "stop", callback=self.cancel)
        self.cancel_button.hide()
        layout.addWidget(self.cancel_button)
        layout.addStretch()

        self.advanced.toggled.connect(self.update_options)
        self.kind.currentIndexChanged.connect(self.set_presets)
        self.advanced_kind.currentIndexChanged.connect(self.update_options)
        self.muxer.currentIndexChanged.connect(self.set_codecs)
        self.video_codec.currentIndexChanged.connect(self.update_options)
        self.audio_codec.currentIndexChanged.connect(self.update_options)
        self.reset_link()

    def reset_link(self):
        self.video = None
        self.options.hide()
        self.result = None
        self.result_controls.hide()
        self.lookup_button.setEnabled(bool(self.link.text().strip()))
        self.status.clear()

    def lookup(self):
        if self.process is not None:
            return
        self.reset_link()
        try:
            self.url = video_url(self.link.text())
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.start_task()

    def load_formats(self, video, muxers):
        self.video = video
        self.title.setText(video.title)
        self.kind.model().item(0).setEnabled(any(s.video for s in video.streams))
        self.kind.model().item(1).setEnabled(video.has_audio)
        self.kind.setCurrentIndex(0 if any(s.video for s in video.streams) else 1)
        self.quality.clear()
        self.quality.addItem(tr('Лучшее доступное'), None)
        for height in video.resolutions:
            self.quality.addItem(f"{height}p", height)
        self.stream.clear()
        for stream in video.streams:
            parts = [stream.extension.upper()]
            if stream.video:
                parts.extend((f"{stream.width}×{stream.height}" if stream.width and stream.height else tr('Видео'),
                              stream.video))
                if stream.fps:
                    parts.append(tr('{0:g} кадр/с', stream.fps))
            if stream.audio:
                parts.append(stream.audio)
            if stream.bitrate:
                parts.append(tr('{0:.0f} кбит/с', stream.bitrate))
            if stream.language:
                parts.append(stream.language)
            parts.append(f"#{stream.id}")
            self.stream.addItem(" · ".join(parts), stream)
        self.muxer.clear()
        for muxer in muxers:
            if (muxer.video and any(s.video for s in video.streams)) or (muxer.audio and video.has_audio):
                self.muxer.addItem(f"{muxer.name} · {muxer.title} (.{muxer.extension})", muxer)
        self.muxer.setCurrentIndex(max(0, self.muxer.findText("mp4 ·", Qt.MatchFlag.MatchStartsWith)))
        self.set_codecs()
        self.set_presets()
        self.options.show()

    def set_presets(self):
        self.format.clear()
        presets = AUDIO_FORMATS if self.kind.currentData() == "audio" else VIDEO_FORMATS
        for name, preset in presets.items():
            self.format.addItem(name, preset)
        self.update_options()

    def set_codecs(self):
        muxer = self.muxer.currentData()
        if muxer is None or self.video is None:
            return
        for combo, choices, available in (
            (self.video_codec, muxer.video, any(s.video for s in self.video.streams)),
            (self.audio_codec, muxer.audio, self.video.has_audio),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr('Исключить дорожку'), "")
            if available:
                for codec in choices:
                    combo.addItem(codec, codec)
            combo.setCurrentIndex(min(1, combo.count() - 1))
            combo.blockSignals(False)
        self.update_options()

    def update_options(self):
        advanced = self.advanced.isChecked()
        convert = advanced and self.advanced_kind.currentData() == "convert"
        for widget, visible in (
            (self.kind, not advanced), (self.advanced_kind, advanced), (self.format, not advanced),
            (self.stream, advanced and not convert), (self.muxer, convert),
            (self.video_codec, convert), (self.audio_codec, convert),
            (self.quality, bool(self.video_codec.currentData()) if convert
             else not advanced and self.kind.currentData() == "video"),
        ):
            self.form.setRowVisible(widget, visible)
        self.download_button.setEnabled(self.video is not None and self.selection() is not None)

    def selection(self):
        height = self.quality.currentData()
        if not self.advanced.isChecked():
            output = self.format.currentData()
            if output and self.video and not self.video.has_audio:
                output = replace(output, audio="")
            return Selection(format=output, height=height) if output and (output.video or output.audio) else None
        if self.advanced_kind.currentData() == "stream":
            stream = self.stream.currentData()
            return Selection(stream=stream) if stream else None
        muxer, video, audio = self.muxer.currentData(), self.video_codec.currentData(), self.audio_codec.currentData()
        if muxer and (video or audio):
            extension = muxer.extension if video else {"ipod": "m4a", "matroska": "mka", "asf": "wma"}.get(
                muxer.name, muxer.extension)
            return Selection(format=Format(muxer.name, extension, video, audio), height=height)
        return None

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, tr('Куда сохранить файл'), self.directory.text())
        if path:
            self.directory.setText(path)
            self.context.store.set_setting("youtube_download_dir", path)

    def start_download(self):
        if self.process is not None or self.video is None or (selection := self.selection()) is None:
            return
        try:
            destination = Path(self.directory.text()).resolve()
            destination.mkdir(parents=True, exist_ok=True)
            self.work_dir = Path(tempfile.mkdtemp(prefix=".item40-youtube-", dir=destination))
        except OSError as error:
            self.status.setText(tr('Не удалось подготовить папку для сохранения. {0}', error))
            return
        self.start_task((self.video, selection, self.work_dir))

    def start_task(self, request=None):
        self.result_controls.hide()
        self.result = None
        self.status.setText(tr('Подготовка…'))
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self.link.setEnabled(False)
        self.lookup_button.setEnabled(False)
        self.options.setEnabled(False)
        self.events = self.mp.Queue()
        self.cancel_event = self.mp.Event()
        self.process = self.mp.Process(target=worker, args=(self.context.root, self.url, self.events,
                                                           self.cancel_event, request), daemon=True)
        try:
            self.process.start()
        except (OSError, RuntimeError) as error:
            self.finish("failed", error=tr('Не удалось запустить загрузку. {0}', error))
            return
        self.timer.start()

    def cancel(self):
        if self.process and self.cancel_time is None:
            self.cancel_event.set()
            self.cancel_time = time.monotonic()
            self.status.setText(tr('Отмена…'))
            self.cancel_button.setEnabled(False)

    def poll(self):
        for _ in range(100):
            try:
                kind, values = self.events.get_nowait()
            except queue.Empty:
                break
            if kind != "progress":
                self.finish("cancelled" if self.cancel_time is not None else kind, **values)
                return
            if self.cancel_time is None:
                fraction = values["progress"]
                self.status.setText(values["stage"])
                self.progress.setRange(0, 0 if fraction is None else 1000)
                if fraction is not None:
                    self.progress.setValue(round(fraction * 1000))
        now = time.monotonic()
        if self.cancel_time is not None and now - self.cancel_time > 1.5:
            self.finish("cancelled")
        elif not self.process.is_alive():
            if self.dead_since is None:
                self.dead_since = now
            elif now - self.dead_since > 0.5:
                self.finish("cancelled" if self.cancel_time is not None else "failed",
                            error=tr('Процесс загрузки завершился неожиданно. Повторите попытку.'))

    def finish(self, kind, **values):
        self.stop_process()
        self.status.setToolTip(values.get("detail", ""))
        if kind == "downloaded":
            try:
                self.result = save_download(values["source"], self.video.title)
            except OSError as error:
                self.status.setText(tr('Не удалось сохранить файл. {0}', error))
            else:
                self.status.setText(tr('Сохранено · {0}', self.result.name))
                if not values["readable_audio"] and self.selection_has_audio():
                    self.status.setText(self.status.text() + tr(' · Для расшифровки выберите WAV или MP3.'))
                self.transcribe_button.setVisible(values["readable_audio"])
                self.result_controls.show()
                if not self.isVisible():
                    self.context.show_notice(self.status.text())
        elif kind == "inspected":
            self.load_formats(values["video"], values["muxers"])
            self.status.clear()
        elif kind == "cancelled":
            self.status.setText(tr('Отменено'))
        else:
            self.status.setText(values["error"])
        self.cleanup()
        self.link.setEnabled(True)
        self.lookup_button.setEnabled(True)
        self.options.setEnabled(True)
        self.progress.hide()
        self.cancel_button.hide()

    def selection_has_audio(self):
        selection = self.selection()
        return selection and bool(selection.stream.audio if selection.stream else selection.format.audio)

    def open_folder(self):
        if self.result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.parent)))

    def transcribe(self):
        if self.result and self.result.is_file():
            self.context.open_tool("audio.transcribe")
            self.context.tool_views["audio.transcribe"].add_files([str(self.result)])
        else:
            self.status.setText(tr('Файл перемещён или удалён.'))

    def stop_process(self):
        self.timer.stop()
        if self.process is not None:
            if self.process.pid is not None:
                self.process.join(timeout=0.15)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=1)
            self.process.close()
            self.events.close()
            self.events.cancel_join_thread()
        self.process = self.events = self.cancel_event = self.cancel_time = self.dead_since = None

    def cleanup(self):
        if self.work_dir is not None:
            # The task directory was created for this operation only.
            shutil.rmtree(self.work_dir, ignore_errors=True)
            self.work_dir = None

    def shutdown(self):
        self.cancel()
        self.stop_process()
        self.cleanup()
