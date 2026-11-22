from __future__ import annotations

import multiprocessing as mp
import queue
import shutil
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QSize, QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..telegram import pack_name, thumbnail_cache, worker
from ..telegram_credentials import forget_connection, load_connection, save_connection
from .widgets import button, heading, label, panel


class TelegramPage(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.mp = mp.get_context("spawn")
        self.process = None
        self.events = None
        self.cancel_event = None
        self.cancel_time = None
        self.dead_since = None
        self.action = None
        self.work_dir = None
        self.token = ""
        self.pending_token = ""
        self.username = ""
        self.pack = None
        self.items = {}
        self.saved = {}
        self.failed = {}
        self.requested = []
        self.pending_download = None
        self.output_folder = None
        self.timer = QTimer(self, interval=100)
        self.timer.timeout.connect(self.poll)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(heading(tr('Скачать эмодзи'), tr('Выберите эмодзи из пака Telegram и сохраните оригиналы.')))
        self.connection, connection_layout = panel()
        self.connected_row = QWidget()
        connected_layout = QHBoxLayout(self.connected_row)
        connected_layout.setContentsMargins(0, 0, 0, 0)
        self.bot_label = label("", "sectionTitle")
        connected_layout.addWidget(self.bot_label, 1)
        connected_layout.addWidget(button(tr('Сменить бота'), callback=self.change_bot))
        connection_layout.addWidget(self.connected_row)
        self.credentials = QWidget()
        credentials_layout = QVBoxLayout(self.credentials)
        credentials_layout.setContentsMargins(0, 0, 0, 0)
        credentials_layout.addWidget(label(tr('Создайте бота командой /newbot в @BotFather и вставьте его токен.'),
                                           "muted", True))
        row = QHBoxLayout()
        self.token_input = QLineEdit(placeholderText=tr('Токен бота из @BotFather'))
        self.token_input.setAccessibleName(tr('Токен бота Telegram'))
        self.token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_input.returnPressed.connect(self.connect_bot)
        row.addWidget(self.token_input, 1)
        row.addWidget(button(tr('Подключить бота'), callback=self.connect_bot))
        credentials_layout.addLayout(row)
        connection_layout.addWidget(self.credentials)
        layout.addWidget(self.connection)

        self.link_controls = QWidget()
        links = QHBoxLayout(self.link_controls)
        links.setContentsMargins(0, 0, 0, 0)
        self.link = QLineEdit(placeholderText=tr('https://t.me/addemoji/НазваниеПака'))
        self.link.setAccessibleName(tr('Ссылка на эмодзи-пак'))
        self.link.returnPressed.connect(self.lookup)
        self.link.textChanged.connect(self.reset_pack)
        self.lookup_button = button(tr('Загрузить пак'), "search", callback=self.lookup)
        links.addWidget(self.link, 1)
        links.addWidget(self.lookup_button)
        layout.addWidget(self.link_controls)

        self.pack_controls = QWidget()
        pack_layout = QVBoxLayout(self.pack_controls)
        pack_layout.setContentsMargins(0, 0, 0, 0)
        title_row = QHBoxLayout()
        self.pack_title = label("", "sectionTitle", True)
        title_row.addWidget(self.pack_title, 1)
        self.select_all = button(tr('Выбрать все'), callback=lambda: self.grid.selectAll())
        self.select_none = button(tr('Снять выделение'), callback=lambda: self.grid.clearSelection())
        title_row.addWidget(self.select_all)
        title_row.addWidget(self.select_none)
        pack_layout.addLayout(title_row)
        self.grid = QListWidget()
        self.grid.setAccessibleName(tr('Эмодзи пака. Щёлкните для выбора или снятия выделения.'))
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.grid.setIconSize(QSize(72, 72))
        self.grid.setGridSize(QSize(116, 124))
        self.grid.setWordWrap(False)
        self.grid.setMinimumHeight(150)
        self.grid.itemSelectionChanged.connect(self.update_selection)
        pack_layout.addWidget(self.grid, 1)
        self.selected_count = label("", "muted")
        pack_layout.addWidget(self.selected_count)
        folder_row = QHBoxLayout()
        downloads = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        directory = context.store.setting("telegram_download_dir", downloads or str(Path.home() / "Downloads"))
        self.directory = QLineEdit(directory, readOnly=True)
        self.directory.setAccessibleName(tr('Папка для эмодзи'))
        folder_row.addWidget(self.directory, 1)
        self.choose_folder_button = button(tr('Выбрать папку…'), "folder", callback=self.choose_folder)
        folder_row.addWidget(self.choose_folder_button)
        pack_layout.addLayout(folder_row)
        actions = QHBoxLayout()
        self.download_button = button(tr('Скачать выбранные'), "save", True, self.download_selected)
        self.retry_button = button(tr('Повторить неудачные'), "refresh", callback=self.retry_failed)
        self.open_button = button(tr('Открыть папку'), "folder", callback=self.open_folder)
        self.convert_button = button(tr('Конвертировать'), "refresh", callback=self.convert_saved)
        actions.addWidget(self.download_button)
        actions.addWidget(self.retry_button)
        actions.addWidget(self.open_button)
        actions.addWidget(self.convert_button)
        actions.addStretch()
        pack_layout.addLayout(actions)
        layout.addWidget(self.pack_controls, 1)
        self.status = label("", "muted", True)
        layout.addWidget(self.status)
        self.progress = QProgressBar(textVisible=False)
        layout.addWidget(self.progress)
        self.cancel_button = button(tr('Отменить'), "stop", callback=self.cancel)
        layout.addWidget(self.cancel_button)
        layout.addStretch()
        self.reset_pack()
        self.set_busy(False)
        try:
            saved = load_connection(context.root)
            if saved:
                self.token, self.username = saved
        except OSError as error:
            self.status.setText(str(error))
        self.update_connection()

    def update_connection(self):
        self.connected_row.setVisible(bool(self.token))
        self.credentials.setVisible(not self.token)
        self.bot_label.setText(tr('Подключён @{0}', self.username))
        self.link_controls.setEnabled(bool(self.token) and self.process is None)

    def change_bot(self):
        if self.process is not None:
            return
        try:
            forget_connection(self.context.root)
        except OSError:
            self.status.setText(tr('Не удалось удалить сохранённое подключение. Проверьте доступ к папке данных.'))
            return
        self.token = self.username = ""
        self.token_input.clear()
        self.reset_pack()
        self.update_connection()
        self.token_input.setFocus()

    def connect_bot(self):
        if self.process is not None:
            return
        self.pending_token = self.token_input.text().strip()
        if not self.pending_token:
            self.status.setText(tr('Вставьте токен бота из @BotFather.'))
            return
        self.reset_pack()
        self.start_task("connect", {}, self.pending_token)

    def reset_pack(self):
        if self.process is not None:
            self.cancel()
            return
        self.pack = None
        self.items = {}
        self.grid.clear()
        self.pack_controls.hide()
        self.retry_button.hide()
        self.open_button.hide()
        self.convert_button.hide()
        self.saved = {}
        self.failed = {}
        self.status.clear()

    def lookup(self):
        if self.process is not None or not self.token:
            return
        self.reset_pack()
        try:
            name = pack_name(self.link.text())
        except ValueError as error:
            self.status.setText(str(error))
            return
        self.start_task("inspect", {"name": name})

    def load_pack(self, pack):
        self.pack = pack
        self.pack_title.setText(tr('{0} · {1} эмодзи', pack.title, len(pack.emojis)))
        self.grid.clear()
        self.items = {}
        for emoji in pack.emojis:
            pixmap = QPixmap(72, 72)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setFont(QFont("Segoe UI Emoji", 28))
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji.symbol or str(emoji.position))
            painter.end()
            item = QListWidgetItem(QIcon(pixmap), f"{emoji.symbol or emoji.position} · {emoji.kind.upper()}")
            item.setData(Qt.ItemDataRole.UserRole, emoji.id)
            item.setToolTip(f"{emoji.symbol} · {emoji.kind.upper()} · ID {emoji.id}")
            self.grid.addItem(item)
            self.items[emoji.id] = item
        self.pack_controls.show()
        self.update_selection()

    def show_thumbnail(self, identity, path):
        pixmap = QPixmap(str(path))
        if identity in self.items and not pixmap.isNull():
            self.items[identity].setIcon(QIcon(pixmap))

    def selected_emojis(self):
        selected = {item.data(Qt.ItemDataRole.UserRole) for item in self.grid.selectedItems()}
        return [emoji for emoji in self.pack.emojis if emoji.id in selected] if self.pack else []

    def update_selection(self):
        count = len(self.grid.selectedItems())
        self.selected_count.setText(tr('Выбрано {0} из {1}', count, len(self.items)))
        can_download = self.process is None or self.action == "inspect" and self.pack is not None
        self.download_button.setEnabled(count > 0 and can_download and bool(self.token)
                                        and self.pending_download is None)

    def choose_folder(self):
        directory = QFileDialog.getExistingDirectory(self, tr('Куда сохранить эмодзи'), self.directory.text())
        if directory:
            self.directory.setText(directory)
            self.context.store.set_setting("telegram_download_dir", directory)

    def download_selected(self):
        self.begin_download(self.selected_emojis(), reset=True)

    def retry_failed(self):
        if self.pack:
            self.begin_download([emoji for emoji in self.pack.emojis if emoji.id in self.failed], reset=False)

    def begin_download(self, emojis, *, reset):
        if not emojis or not self.token:
            return
        if self.process is not None:
            if self.action == "inspect":
                self.pending_download = (emojis, reset)
                self.cancel()
                self.update_selection()
            return
        try:
            self.output_folder = Path(self.directory.text()).resolve() / self.pack.name
            self.output_folder.mkdir(parents=True, exist_ok=True)
            self.work_dir = Path(tempfile.mkdtemp(prefix=".item40-telegram-", dir=self.output_folder))
        except OSError:
            self.status.setText(tr('Не удалось подготовить папку для сохранения. Выберите другую папку.'))
            self.update_selection()
            return
        if reset:
            self.saved = {}
            self.failed = {}
        self.requested = emojis
        for emoji in emojis:
            self.failed.pop(emoji.id, None)
        self.start_task("download", {"emojis": emojis, "folder": self.work_dir})

    def start_task(self, action, params, token=None):
        self.action = action
        self.status.setText({"connect": tr('Подключение бота…'), "inspect": tr('Получение эмодзи-пака…'),
                             "download": tr('Скачивание эмодзи…')}[action])
        self.events = self.mp.Queue()
        self.cancel_event = self.mp.Event()
        self.process = self.mp.Process(target=worker, args=(self.context.root, token or self.token, action,
                                                           params, self.events, self.cancel_event), daemon=True)
        self.set_busy(True)
        try:
            self.process.start()
        except (OSError, RuntimeError):
            self.finish("failed", error=tr('Не удалось запустить операцию Telegram. Повторите попытку.'))
            return
        self.timer.start()

    def set_busy(self, busy):
        self.connection.setEnabled(not busy)
        self.link_controls.setEnabled(not busy and bool(self.token))
        for control in (self.grid, self.select_all, self.select_none, self.choose_folder_button):
            control.setEnabled(not busy or self.action == "inspect")
        self.retry_button.setEnabled(not busy and bool(self.token))
        self.open_button.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)
        self.update_selection()

    def cancel(self):
        if self.process is not None and self.cancel_time is None:
            self.cancel_event.set()
            self.cancel_time = time.monotonic()
            self.status.setText(tr('Отмена…'))
            self.cancel_button.setEnabled(False)

    def handle_event(self, kind, values):
        if kind == "pack":
            self.load_pack(values["pack"])
            self.status.setText(tr('Загрузка миниатюр…'))
        elif kind == "thumbnail":
            self.show_thumbnail(values["id"], values["path"])
        elif kind == "saved":
            self.saved[values["id"]] = values["path"]
            self.failed.pop(values["id"], None)
        elif kind == "file_failed":
            self.failed[values["id"]] = values["error"]
        elif kind == "progress" and self.cancel_time is None:
            self.status.setText(values["stage"])
            fraction = values["progress"]
            self.progress.setRange(0, 0 if fraction is None else 1000)
            if fraction is not None:
                self.progress.setValue(round(fraction * 1000))

    def poll(self):
        for _ in range(100):
            try:
                kind, values = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in {"completed", "connected", "failed", "cancelled"}:
                self.finish("cancelled" if self.cancel_time is not None else kind, **values)
                return
            self.handle_event(kind, values)
        now = time.monotonic()
        if self.cancel_time is not None and now - self.cancel_time > 1.5:
            self.finish("cancelled")
        elif not self.process.is_alive():
            if self.dead_since is None:
                self.dead_since = now
            elif now - self.dead_since > 0.5:
                self.finish("failed", error=tr('Операция Telegram прервалась. Повторите попытку.'))

    def finish(self, kind, **values):
        self.stop_process()
        if kind == "connected":
            self.token, self.username = self.pending_token, values["username"]
            self.token_input.clear()
            try:
                save_connection(self.context.root, self.token, self.username)
                self.status.setText(tr('Подключён @{0}', self.username))
            except OSError:
                self.status.setText(tr('Бот подключён. Сохранить подключение не удалось, при следующем запуске введите токен.'))
        elif self.action == "download":
            for emoji in self.requested:
                if emoji.id not in self.saved and emoji.id not in self.failed:
                    self.failed[emoji.id] = tr('Загрузка прервана.')
            summary = tr('Сохранено {0}', len(self.saved))
            if self.failed:
                summary += tr(' · Осталось {0}', len(self.failed))
            if kind == "cancelled":
                summary = tr('Отменено · ') + summary
            elif kind == "failed":
                summary += " · " + values["error"]
            self.status.setText(summary)
            self.status.setToolTip("\n".join(dict.fromkeys(self.failed.values())))
            self.retry_button.setVisible(bool(self.failed))
            self.open_button.setVisible(bool(self.saved))
            self.convert_button.setVisible(bool(self.saved))
        elif kind == "failed":
            self.status.setText(values["error"])
        elif kind == "cancelled":
            self.status.setText(tr('Отменено'))
        else:
            self.status.setText(tr('Выберите эмодзи для скачивания.'))
        self.pending_token = ""
        self.cleanup()
        if values.get("auth"):
            self.token = self.username = ""
            try:
                forget_connection(self.context.root)
            except OSError:
                pass
        self.set_busy(False)
        self.update_connection()
        if self.pending_download is not None:
            emojis, reset = self.pending_download
            self.pending_download = None
            self.begin_download(emojis, reset=reset)

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
            shutil.rmtree(self.work_dir, ignore_errors=True)
            self.work_dir = None
        if self.pack and self.token:
            cache = thumbnail_cache(self.context.root, self.token.partition(":")[0], self.pack, self.pack.emojis[0])
            try:
                for path in cache.parent.glob("*.part"):
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    def open_folder(self):
        if self.output_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_folder)))

    def convert_saved(self):
        self.context.open_tool("files.convert")
        self.context.tool_views["files.convert"].add_files([str(path) for path in self.saved.values()])

    def shutdown(self):
        self.pending_download = None
        self.cancel()
        self.stop_process()
        self.cleanup()
