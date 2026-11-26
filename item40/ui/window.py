from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..registry import builtin_tools
from ..telegram import TOOL_ID as TELEGRAM_TOOL_ID
from ..youtube import TOOL_ID
from .pages import CatalogPage, JobsPage, SettingsPage
from .theme import icon
from .widgets import label


class MainWindow(QMainWindow):
    def __init__(self, store, manager, root, gpu=None):
        super().__init__()
        self.store = store
        self.manager = manager
        self.root = root
        self.gpu = gpu
        self.setWindowTitle("item-40")
        self.setWindowIcon(icon("grid", "#dddddd", 48))
        self.resize(1360, 900)
        self.setMinimumSize(1080, 760)
        self.tool_definitions = builtin_tools()
        self.tool_views = {}
        self.nav_buttons = {}
        container = QWidget()
        container.setObjectName("root")
        self.setCentralWidget(container)
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(190)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 22, 12, 16)
        side.setSpacing(6)
        side.addWidget(label("  item-40", "brand"))
        side.addSpacing(24)
        self.stack = QStackedWidget()
        self.catalog = CatalogPage(self, self.tool_definitions)
        catalog_scroll = QScrollArea()
        catalog_scroll.setFrameShape(QFrame.Shape.NoFrame)
        catalog_scroll.setWidgetResizable(True)
        catalog_scroll.setWidget(self.catalog)
        self.add_page("catalog", tr('Инструменты'), "grid", catalog_scroll, side)
        self.add_page("jobs", tr('Задачи'), "tasks", JobsPage(self), side)
        self.add_page("history", tr('История'), "history", JobsPage(self, history=True), side)
        side.addSpacing(28)
        side.addWidget(label(tr('   КАТЕГОРИИ'), "eyebrow"))
        side.addSpacing(6)
        for category in sorted({tool.category for tool in self.tool_definitions}):
            glyph = next(tool.icon for tool in self.tool_definitions if tool.category == category)
            key = f"category:{category}"
            nav = QPushButton(category)
            nav.setObjectName("nav")
            nav.setCheckable(True)
            nav.setIcon(icon(glyph))
            nav.setCursor(Qt.CursorShape.PointingHandCursor)
            nav.clicked.connect(lambda checked=False, name=category: self.open_category(name))
            side.addWidget(nav)
            self.nav_buttons[key] = (nav, self.nav_buttons["catalog"][1])
        side.addStretch()
        self.settings = SettingsPage(self)
        # Settings can exceed the height of smaller displays.
        settings_scroll = QScrollArea()
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setWidget(self.settings)
        self.add_page("settings", tr('Настройки'), "settings", settings_scroll, side)
        side.addSpacing(18)
        layout.addWidget(sidebar)
        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(22, 22, 22, 14)
        main_layout.addWidget(self.stack)
        layout.addWidget(main, 1)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().hide()
        self.manager.notice.connect(self.show_notice)
        self.manager.download_changed.connect(lambda stage, progress: self.show_notice(stage))
        self.open_tool("audio.transcribe")

        open_action = QAction(self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.browse_audio)
        self.addAction(open_action)
        save_action = QAction(self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self.tool_views["audio.transcribe"].export)
        self.addAction(save_action)
        find_action = QAction(self)
        find_action.setShortcut("Ctrl+K")
        find_action.triggered.connect(self.find_tool)
        self.addAction(find_action)

    def add_page(self, key, text, glyph, page, sidebar):
        index = self.stack.addWidget(page)
        nav = QPushButton(text)
        nav.setObjectName("nav")
        nav.setCheckable(True)
        nav.setCursor(Qt.CursorShape.PointingHandCursor)
        nav.setIcon(icon(glyph))
        nav.clicked.connect(lambda checked=False, page_index=index, name=key: self.navigate(name, page_index))
        sidebar.addWidget(nav)
        self.nav_buttons[key] = (nav, index)

    def navigate(self, key, index=None):
        if "audio.transcribe" in self.tool_views:
            self.tool_views["audio.transcribe"].flush_edit()
        self.stack.setCurrentIndex(self.nav_buttons[key][1] if index is None else index)
        for name, (nav, _) in self.nav_buttons.items():
            nav.setChecked(name == key)

    def open_tool(self, key):
        tool = next(tool for tool in self.tool_definitions if tool.id == key)
        if key not in self.tool_views:
            self.tool_views[key] = tool.create_view(self)
            self.stack.addWidget(self.tool_views[key])
        self.navigate(f"category:{tool.category}")
        self.stack.setCurrentWidget(self.tool_views[key])

    def open_category(self, category):
        self.catalog.search.setText(category)
        self.navigate(f"category:{category}")

    def open_job(self, job_id):
        self.open_tool("audio.transcribe")
        self.tool_views["audio.transcribe"].open_result(job_id)

    def browse_audio(self):
        self.open_tool("audio.transcribe")
        self.tool_views["audio.transcribe"].browse()

    def find_tool(self):
        self.navigate("catalog")
        self.catalog.search.setFocus()

    def show_notice(self, message):
        self.statusBar().show()
        self.statusBar().showMessage("  " + message, 15000)

    def show_error(self, title, message):
        QMessageBox.warning(self, title, message)

    def closeEvent(self, event):
        self.tool_views["audio.transcribe"].flush_edit()
        if TOOL_ID in self.tool_views:
            self.tool_views[TOOL_ID].shutdown()
        if TELEGRAM_TOOL_ID in self.tool_views:
            self.tool_views[TELEGRAM_TOOL_ID].shutdown()
        for key in ("files.convert", "soundcloud.download", "tiktok.download"):
            if key in self.tool_views:
                self.tool_views[key].shutdown()
        self.manager.shutdown()
        self.store.close()
        event.accept()
