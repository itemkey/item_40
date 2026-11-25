"""Exercise Telegram's normal Qt and spawned-worker entry points in a frozen build."""
import json
import time
from pathlib import Path


class FixtureResponse:
    status_code = 200

    def __init__(self, data=None, file=None):
        self.data, self.file = data, file

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def json(self):
        return {"ok": True, "result": self.data}

    def iter_content(self, size):
        with self.file.open("rb") as stream:
            while block := stream.read(size):
                yield block


class FixtureSession:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.pack = json.loads((self.folder / "pack.json").read_text(encoding="utf-8"))

    def post(self, url, *, json, **kwargs):
        method = url.rsplit("/", 1)[1]
        if method == "getMe":
            return FixtureResponse({"is_bot": True, "username": "fixture_bot"})
        if method == "getStickerSet":
            return FixtureResponse(self.pack)
        if method == "getFile":
            file = self.folder / json["file_id"]
            return FixtureResponse({"file_path": file.name, "file_size": file.stat().st_size})
        raise AssertionError("Unexpected fixture method")

    def get(self, url, **kwargs):
        return FixtureResponse(file=self.folder / url.rsplit("/", 1)[1])

    def close(self):
        pass


def fixture_worker(root, token, action, params, events, cancel):
    import requests

    from .telegram import worker

    requests.Session = lambda: FixtureSession(Path(root) / "fixture")
    worker(root, token, action, params, events, cancel)


def smoke_test(request, report_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from .jobs import JobManager
    from .paths import data_dir, database_path
    from .storage import Store
    from .telegram import TOOL_ID
    from .telegram_credentials import load_connection
    from .ui import telegram_page
    from .ui.theme import STYLE
    from .ui.window import MainWindow

    if request.get("telegram_fixture"):
        telegram_page.worker = fixture_worker
    app = QApplication([])
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguiemj.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont("Segoe UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    root = data_dir()
    store = Store(database_path(root))
    window = MainWindow(store, JobManager(store, root), root)
    window.resize(1080, 760)
    window.open_tool(TOOL_ID)
    window.show()
    page = window.tool_views[TOOL_ID]
    page.directory.setText(request["directory"])
    started = time.monotonic()
    phase = "connect"
    snapshots = []

    def capture(name):
        if folder := request.get("screenshots"):
            path = Path(folder) / f"telegram-{name}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(path))
            snapshots.append(str(path))

    def finish(error=""):
        timer.stop()
        report = {"error": error, "mock_api": bool(request.get("telegram_fixture")),
                  "sticker_type": page.pack.sticker_type if page.pack else None,
                  "saved": [str(path) for path in page.saved.values()], "screenshots": snapshots}
        if not error and request.get("telegram_fixture"):
            report["connection_saved"] = load_connection(root) == ("123456:FIXTURE_ONLY_TOKEN", "fixture_bot")
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        window.close()
        app.exit(1 if error else 0)

    def check():
        nonlocal phase
        if time.monotonic() - started > request.get("timeout_seconds", 90):
            finish(f"Timeout: {page.status.text()}")
            return
        if page.process is not None:
            return
        if phase == "connect":
            if not page.token:
                finish(page.status.text() or "Connect a bot before the live smoke test.")
                return
            capture("connected")
            phase = "inspect"
            page.link.setText(request["telegram_pack_url"])
            page.lookup()
        elif phase == "inspect":
            if page.pack is None:
                finish(page.status.text())
                return
            identities = request.get("sticker_ids", request.get("emoji_ids", [emoji.id for emoji in page.pack.emojis[:3]]))
            for identity in identities:
                page.items[identity].setSelected(True)
            capture("selected")
            phase = "download"
            page.download_selected()
        else:
            capture("downloaded")
            error = page.status.text() if page.failed or not page.saved else ""
            finish(error)

    capture("initial")
    if request.get("telegram_fixture") and not page.token:
        page.token_input.setText("123456:FIXTURE_ONLY_TOKEN")
        page.connect_bot()
    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(200)
    return app.exec()
