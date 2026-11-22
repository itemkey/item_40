from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..domain import MODEL_LABELS, STATUS_LABELS, job_files, source_label
from ..exports import output_directory
from ..i18n import tr
from .theme import icon
from .widgets import button, heading, label, panel


class CatalogPage(QWidget):
    def __init__(self, context, tools):
        super().__init__()
        self.context = context
        self.tools = tools
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(24)
        layout.addWidget(heading(tr('Инструменты')))
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('Найти инструмент…'))
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.filter_tools)
        layout.addWidget(self.search)
        self.cards = []
        for tool in tools:
            frame, card = panel()
            row = QHBoxLayout()
            texts = QVBoxLayout()
            texts.addWidget(label(tool.category.upper(), "eyebrow"))
            texts.addWidget(label(tool.title, "sectionTitle"))
            texts.addWidget(label(tool.description, "subtitle", True))
            row.addLayout(texts, 1)
            row.addWidget(button(tr('Открыть'), "arrow", callback=lambda checked=False, key=tool.id: context.open_tool(key)))
            card.addLayout(row)
            layout.addWidget(frame)
            self.cards.append((tool, frame))
        self.no_results = label(tr('Инструменты не найдены. Попробуйте другое название.'), "muted")
        self.no_results.hide()
        layout.addWidget(self.no_results)
        layout.addStretch()

    def filter_tools(self, query):
        count = 0
        for tool, card in self.cards:
            visible = query.casefold() in f"{tool.title} {tool.category} {tool.description}".casefold()
            card.setVisible(visible)
            count += visible
        self.no_results.setVisible(count == 0)


class JobsPage(QWidget):
    def __init__(self, context, history=False):
        super().__init__()
        self.context = context
        self.history = history
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        layout.addWidget(heading(tr('История') if history else tr('Задачи')))
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('Поиск по названию файла…'))
        self.search.textChanged.connect(self.refresh)
        row.addWidget(self.search, 1)
        if not history:
            row.addWidget(button(tr('Запустить очередь'), "play", True, context.manager.start))
            self.pause = button(tr('Пауза очереди'), "stop", callback=self.pause_queue)
            self.pause.setToolTip(tr('Текущий файл будет обработан; следующие будут ждать запуска.'))
            row.addWidget(self.pause)
        layout.addLayout(row)
        frame, card = panel()
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.open_selected)
        card.addWidget(self.list, 1)
        self.empty = label(tr('Список пуст'), "muted")
        card.addWidget(self.empty)
        layout.addWidget(frame, 1)
        controls = QHBoxLayout()
        controls.addWidget(button(tr('Открыть результат'), "file", callback=self.open_selected))
        controls.addWidget(button(tr('Повторить'), "refresh", callback=self.retry))
        controls.addWidget(button(tr('Отменить'), "stop", callback=self.cancel))
        controls.addStretch()
        layout.addLayout(controls)
        context.manager.changed.connect(self.refresh)
        self.refresh()

    def selected_id(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def refresh(self, *_):
        selected = self.selected_id()
        self.list.clear()
        query = self.search.text().casefold()
        for job in self.context.store.jobs():
            if self.history and job["status"] in {"queued", "running"}:
                continue
            if not any(query in Path(source).name.casefold() for source in job_files(job)):
                continue
            date = datetime.fromisoformat(job["created_at"]).astimezone().strftime("%d.%m.%Y  %H:%M")
            item = QListWidgetItem(f"{source_label(job)}\n{STATUS_LABELS[job['status']]}  ·  {date}")
            item.setData(Qt.ItemDataRole.UserRole, job["id"])
            item.setIcon(icon("check" if job["status"] == "completed" else "file"))
            item.setToolTip(tr(job["stage"]))
            self.list.addItem(item)
            if job["id"] == selected:
                self.list.setCurrentItem(item)
        self.empty.setVisible(self.list.count() == 0)

    def open_selected(self, *_):
        if selected := self.selected_id():
            self.context.open_job(selected)

    def retry(self):
        if selected := self.selected_id():
            self.context.manager.retry(selected)
            self.context.manager.start()

    def cancel(self):
        if selected := self.selected_id():
            self.context.manager.cancel(selected)

    def pause_queue(self):
        self.context.manager.pause()
        self.context.show_notice(tr('Очередь приостановлена. Текущий файл продолжит обрабатываться.'))


class SettingsPage(QWidget):
    def __init__(self, context):
        super().__init__()
        self.context = context
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        layout.addWidget(heading(tr('Настройки')))
        from ..i18n import language, save_language

        language_frame, language_layout = panel()
        language_layout.addWidget(label(tr('Язык интерфейса / Interface language'), "sectionTitle"))
        self.ui_language = QComboBox()
        self.ui_language.addItem(tr('Русский'), "ru")
        self.ui_language.addItem("English", "en")
        self.ui_language.setCurrentIndex(max(0, self.ui_language.findData(language())))
        self.language_notice = label("", "muted", True)

        def choose_language():
            try:
                save_language(self.ui_language.currentData())
                self.language_notice.setText(tr('Изменение языка вступит в силу после перезапуска приложения.'))
            except OSError:
                self.language_notice.setText(tr('Не удалось сохранить язык интерфейса.'))

        self.ui_language.currentIndexChanged.connect(choose_language)
        language_layout.addWidget(self.ui_language)
        language_layout.addWidget(self.language_notice)
        layout.addWidget(language_frame)
        output_frame, output = panel()
        output.addWidget(label(tr('Папка результатов'), "sectionTitle"))
        output_row = QHBoxLayout()
        self.output_path = QLineEdit(str(output_directory(context.store)))
        self.output_path.setReadOnly(True)
        self.output_path.setToolTip(self.output_path.text())
        output_row.addWidget(self.output_path, 1)
        output_row.addWidget(button(tr('Выбрать…'), callback=self.choose_output_directory))
        output_row.addWidget(button(tr('Открыть'), callback=self.open_output_directory))
        output.addLayout(output_row)
        output.addWidget(label(tr('Новые расшифровки сохраняются в TXT. Изменения текста обновляют тот же файл.'), "muted", True))
        layout.addWidget(output_frame)
        model_frame, models = panel()
        models.addWidget(label(tr('Модели распознавания'), "sectionTitle"))
        self.model_statuses = {}
        for key, text in MODEL_LABELS.items():
            row = QHBoxLayout()
            description = QVBoxLayout()
            description.addWidget(label(text, "sectionTitle"))
            description.addWidget(label(tr('0,5 ГБ') if key == "small" else tr('3,1 ГБ'), "muted"))
            status = label("", "muted")
            self.model_statuses[key] = status
            description.addWidget(status)
            row.addLayout(description, 1)
            row.addWidget(button(tr('Скачать'), "save", callback=lambda checked=False, model=key: context.manager.download_model(model)))
            models.addLayout(row)
        self.download_stage = label("", "accent", True)
        models.addWidget(self.download_stage)
        self.download_progress = QProgressBar()
        self.download_progress.setTextVisible(False)
        self.download_progress.setRange(0, 1000)
        models.addWidget(self.download_progress)
        self.cancel_download = button(tr('Отменить загрузку'), "stop", callback=self.cancel)
        models.addWidget(self.cancel_download, alignment=Qt.AlignmentFlag.AlignLeft)
        self.cancel_download.hide()
        layout.addWidget(model_frame)

        device_frame, devices = panel()
        devices.addWidget(label(tr('Обработка'), "sectionTitle"))
        devices.addWidget(label(tr('Обнаружено: ') + (context.gpu or tr('процессор')), "muted", True))
        self.device = QComboBox()
        self.device.addItem(tr('Автоматически'), "auto")
        self.device.addItem(tr('Процессор'), "cpu")
        self.device.addItem("NVIDIA GPU", "cuda")
        self.device.setCurrentIndex(max(0, self.device.findData(context.store.setting("device", "auto"))))
        self.device.currentIndexChanged.connect(lambda: context.store.set_setting("device", self.device.currentData()))
        devices.addWidget(self.device)
        devices.addWidget(label(tr('NVIDIA GPU: драйвер NVIDIA и загрузка компонентов (1,3 ГБ) при первом запуске.'), "muted", True))
        layout.addWidget(device_frame)
        storage_frame, storage = panel()
        storage.addWidget(label(tr('Данные приложения'), "sectionTitle"))
        storage.addWidget(label(str(context.root), "muted", True))
        storage.addWidget(button(tr('Открыть папку'), "folder", callback=lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(context.root)))), alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(storage_frame)
        version_row = QHBoxLayout()
        version_row.addWidget(label(f"item-40 {__version__}", "muted"))
        version_row.addStretch()
        version_row.addWidget(button(tr('Релизы на GitHub'), callback=lambda: QDesktopServices.openUrl(
            QUrl("https://github.com/itemkey/item_40/releases/latest"))))
        layout.addLayout(version_row)
        layout.addStretch()
        context.manager.download_changed.connect(self.download_update)
        context.manager.changed.connect(self.refresh)
        self.refresh()

    def download_update(self, stage, progress):
        self.download_stage.setText(stage)
        self.download_progress.setValue(int(progress * 1000))
        self.cancel_download.setVisible(self.context.manager.active is not None)
        self.refresh()

    def cancel(self):
        if self.context.manager.download_only:
            self.context.manager.cancel(self.context.manager.active)

    def refresh(self, *_):
        for key, status in self.model_statuses.items():
            ready = (self.context.root / "models" / key / ".ready").exists()
            status.setText(tr('Скачана') if ready else tr('Не скачана'))
        self.cancel_download.setVisible(self.context.manager.download_only and self.context.manager.active is not None)

    def choose_output_directory(self):
        path = QFileDialog.getExistingDirectory(self, tr('Папка результатов'), self.output_path.text())
        if path:
            self.set_output_directory(path)

    def set_output_directory(self, path):
        folder = Path(path).expanduser().resolve()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=folder):
                pass
        except OSError as error:
            self.context.show_error(tr('Папка недоступна'), str(error))
            return False
        self.context.store.set_setting("output_dir", str(folder))
        self.output_path.setText(str(folder))
        self.output_path.setToolTip(str(folder))
        return True

    def open_output_directory(self):
        folder = output_directory(self.context.store)
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            self.context.show_error(tr('Папка недоступна'), str(error))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
