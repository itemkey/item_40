from __future__ import annotations

import logging
import multiprocessing
import sys


def main():
    # This must run before Qt is imported in frozen multiprocessing children.
    multiprocessing.freeze_support()
    if len(sys.argv) == 4 and sys.argv[1] == "--smoke-test":
        from .diagnostics import smoke_test
        return smoke_test(sys.argv[2], sys.argv[3])
    from PySide6.QtCore import QLockFile
    from PySide6.QtGui import QColor, QFont, QPalette
    from PySide6.QtWidgets import QApplication, QMessageBox

    from .jobs import JobManager
    from .paths import data_dir, database_path
    from .storage import Store
    from .ui.theme import STYLE
    from .ui.window import MainWindow
    from .worker import nvidia_gpu

    root = data_dir()
    logging.basicConfig(filename=root / "app.log", encoding="utf-8", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("item-40")
    app.setOrganizationName("item-40")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#171717"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e9edf5"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#191919"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e9edf5"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#252d3b"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e9edf5"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#414141"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)
    lock = QLockFile(str(root / "app.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "item-40", "Приложение уже запущено.")
        return 0
    store = Store(database_path(root))
    gpu = nvidia_gpu()
    if store.setting("model") is None:
        store.set_setting("model", "large-v3" if gpu else "small")
    manager = JobManager(store, root)
    window = MainWindow(store, manager, root, gpu)
    window.show()
    if len(sys.argv) > 1:
        window.tool_views["audio.transcribe"].add_files(sys.argv[1:])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
