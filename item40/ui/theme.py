from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

PATHS = {
    "grid": '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
    "audio": '<path d="M4 10v4m4-8v12m4-15v18m4-15v12m4-8v4"/>',
    "tasks": '<path d="M9 6h11M9 12h11M9 18h11M3 6l1 1 2-2m-3 7 1 1 2-2m-3 7 1 1 2-2"/>',
    "history": '<path d="M3 11a9 9 0 1 1 2.6 7.4M3 4v7h7m2-4v6l4 2"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
    "upload": '<path d="M12 16V3m-5 5 5-5 5 5M4 16v4h16v-4"/>',
    "file": '<path d="M14 3H5v18h14V8Zm0 0v5h5M8 12h8m-8 4h6"/>',
    "copy": '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
    "save": '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
    "play": '<path d="m8 4 12 8-12 8Z"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="3"/>',
    "search": '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Zm-4 9 3 3 5-6"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "refresh": '<path d="M20 8a9 9 0 1 0 0 8m0-14v6h-6"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "folder": '<path d="M3 7V4h7l3 3h8v13H3Z"/>',
}


def icon(name, color="#aaaaaa", size=20):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="square" stroke-linejoin="miter">{PATHS[name].replace(' rx="2"', '').replace(' rx="3"', '')}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


STYLE = """
* { font-family: 'Segoe UI'; font-size: 13px; color: #dedede; border-radius: 0px; }
QWidget { background: transparent; }
QMainWindow, QDialog, QWidget#root { background: #171717; }
QFrame#sidebar { background: #121212; border-right: 1px solid #343434; }
QFrame#panel, QFrame#card { background: #1b1b1b; border: 1px solid #383838; }
QFrame#inset { background: #171717; border: 1px solid #383838; }
QLabel#brand { font-size: 18px; font-weight: 600; }
QLabel#title { font-size: 22px; font-weight: 600; }
QLabel#subtitle, QLabel#muted { color: #949494; }
QLabel#eyebrow { color: #949494; font-size: 11px; }
QLabel#sectionTitle { font-size: 13px; font-weight: 600; }
QLabel#accent { color: #e5b8b8; }
QPushButton { background: #242424; border: 1px solid #494949; padding: 7px 11px; font-weight: 400; }
QPushButton:hover { background: #303030; border-color: #777777; }
QPushButton:pressed { background: #191919; }
QPushButton:disabled { color: #686868; background: #202020; border-color: #333333; }
QPushButton#primary { color: #151515; background: #dddddd; border: 1px solid #dddddd; }
QPushButton#primary:hover { background: #ffffff; }
QPushButton#primary:disabled { background: #444444; border-color: #444444; color: #777777; }
QPushButton#nav { text-align: left; border: none; background: transparent; padding: 10px 12px; color: #a5a5a5; }
QPushButton#nav:hover { background: #242424; }
QPushButton#nav:checked { background: #2d2d2d; color: #ffffff; border-left: 2px solid #dddddd; }
QPushButton#quiet { background: transparent; border: 1px solid #444444; }
QLineEdit, QComboBox { background: #171717; border: 1px solid #494949; padding: 7px 9px; selection-background-color: #484848; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #999999; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: #242424; selection-background-color: #444444; padding: 3px; }
QPlainTextEdit { background: #1b1b1b; border: none; font-size: 14px; selection-background-color: #484848; padding: 2px; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border-bottom: 1px solid #333333; padding: 10px 6px; }
QListWidget::item:selected { background: #353535; color: #ffffff; }
QListWidget::item:hover { background: #292929; }
QProgressBar { border: none; background: #353535; height: 3px; max-height: 3px; }
QProgressBar::chunk { background: #bbbbbb; }
QScrollBar:vertical { width: 7px; background: transparent; }
QScrollBar::handle:vertical { background: #484848; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QSplitter::handle { background: transparent; width: 12px; }
QToolTip { background: #242424; border: 1px solid #666666; padding: 5px; }
QStatusBar { background: #171717; color: #999999; border-top: 1px solid #333333; }
QMessageBox, QMenu { background: #1b1b1b; }
QMenu::item { padding: 6px 14px; }
QMenu::item:selected { background: #3b3b3b; }
QCheckBox { spacing: 8px; }
"""
