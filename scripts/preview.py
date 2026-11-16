"""Render the real application for layout QA, without adding sample records."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from item40.jobs import JobManager
from item40.storage import Store
from item40.ui.theme import STYLE
from item40.ui.window import MainWindow


def main():
    app = QApplication([])
    for filename in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
        font = Path("C:/Windows/Fonts") / filename
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    with TemporaryDirectory() as temp:
        root = Path(temp)
        store = Store(root / "preview.sqlite3")
        window = MainWindow(store, JobManager(store, root), root)
        window.resize(int(os.environ.get("PREVIEW_WIDTH", 1360)), int(os.environ.get("PREVIEW_HEIGHT", 900)))
        if page := os.environ.get("PREVIEW_PAGE"):
            window.navigate(page)
        window.show()

        def capture():
            destination = Path("artifacts")
            destination.mkdir(exist_ok=True)
            window.grab().save(str(destination / "preview.png"))
            window.close()
            app.quit()

        QTimer.singleShot(300, capture)
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
