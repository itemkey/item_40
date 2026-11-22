"""Verify conversion and download entry points in source and frozen Windows builds."""
import json
import time
from pathlib import Path


def smoke_test(request, report_path):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from .i18n import install_qt_translation, language
    from .jobs import JobManager
    from .paths import data_dir, database_path
    from .storage import Store
    from .ui.theme import STYLE
    from .ui.window import MainWindow

    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguiemj.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Segoe UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.ui_translator = install_qt_translation(app)
    root = data_dir()
    store = Store(database_path(root))
    window = MainWindow(store, JobManager(store, root), root)
    window.resize(1360, 900)
    key = "soundcloud.download" if "soundcloud_url" in request else "files.convert"
    window.open_tool(key)
    window.show()
    page = window.tool_views[key]
    page.directory.setText(request["directory"])
    phase = "inspect"
    started = time.monotonic()

    def capture(name):
        if destination := request.get("screenshots"):
            folder = Path(destination)
            folder.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(folder / f"{key}-{name}.png"))

    def finish(error=""):
        timer.stop()
        if key == "files.convert":
            results = [{"source": path, "status": entry["state"], "output": str(entry.get("result", "")),
                        "detail": entry["item"].toolTip(2)} for path, entry in page.entries.items()]
        else:
            results = [{"id": identity, "output": str(path)} for identity, path in page.saved.items()]
        capture("complete")
        Path(report_path).write_text(json.dumps({"error": error, "results": results, "ui_language": language(),
                                               "settings_language": window.settings.ui_language.currentData()},
                                              ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        window.close()
        app.exit(1 if error else 0)

    def check():
        nonlocal phase
        if time.monotonic() - started > request.get("timeout_seconds", 240):
            finish("Timeout: " + page.status.text())
            return
        if page.controller.process is not None:
            return
        if phase == "inspect":
            capture("ready")
            if key == "files.convert":
                for spec in request["conversion_files"]:
                    entry = page.entries[str(Path(spec["source"]).resolve())]
                    chosen = next((target for target in entry["targets"] if target.id == spec["target"]), None)
                    if chosen is None:
                        finish("Target unavailable: " + spec["target"] + " " + entry["item"].toolTip(2))
                        return
                    entry["target"] = chosen
                    entry["item"].setText(1, chosen.extension.upper())
                    entry["options"] = spec.get("options", {})
                page.current = None
                page.select_entry(page.list.currentItem())
                page.start()
            else:
                if not page.tracks:
                    finish(page.status.text())
                    return
                page.select_all(False)
                for track in [track for track in page.tracks if not track.unavailable][:request.get("track_count", 1)]:
                    page.items[track.id].setCheckState(0, Qt.CheckState.Checked)
                wanted = request.get("target", "media:mp3")
                index = next((i for i in range(page.format.count()) if getattr(page.format.itemData(i), "id", "") == wanted), -1)
                if index == -1:
                    finish("Audio target unavailable: " + wanted)
                    return
                page.format.setCurrentIndex(index)
                page.preview.setChecked(request.get("allow_preview", False))
                page.download_selected()
            phase = "convert"
        elif key == "files.convert":
            errors = [entry["item"].toolTip(2) for entry in page.entries.values() if entry["state"] != "completed"]
            finish("\n".join(errors))
        else:
            finish(page.status.text() if page.failed or not page.saved else "")

    if key == "files.convert":
        page.add_files([spec["source"] for spec in request["conversion_files"]])
    else:
        page.link.setText(request["soundcloud_url"])
        page.lookup()
    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(200)
    return app.exec()
