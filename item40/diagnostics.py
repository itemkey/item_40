"""Unattended smoke-test entrypoint, including frozen multiprocessing workers."""
import json
import tempfile
import time
from pathlib import Path


def smoke_test(request_path, report_path):
    from PySide6.QtCore import QCoreApplication, QTimer

    from .jobs import JobManager
    from .paths import data_dir
    from .storage import Store

    request = json.loads(Path(request_path).read_text(encoding="utf-8-sig"))
    if "youtube_url" in request:
        return youtube_smoke_test(request, report_path)
    app = QCoreApplication([])
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / "smoke.sqlite3")
        store.set_setting("output_dir", str(Path(temp) / "output"))
        manager = JobManager(store, data_dir())
        if request.get("combine"):
            from .domain import JobRequest
            job = JobRequest(source=request["files"][0], source_files=request["files"],
                             model=request.get("model", "small"), language=request.get("language", "ru"),
                             device=request.get("device", "cpu"))
            store.add(job)
            ids = [job.id]
        else:
            ids = manager.enqueue(request["files"], request.get("model", "small"), request.get("language", "ru"),
                                  request.get("device", "cpu"))
        started = time.monotonic()

        def check():
            jobs = [store.get(job_id) for job_id in ids]
            timeout = time.monotonic() - started > request.get("timeout_seconds", 180)
            if timeout or all(job["status"] in {"completed", "cancelled", "failed"} for job in jobs):
                report = [{"source": job["source"], "status": job["status"], "text": job["transcript"],
                           "error": job["error"], "output_saved": Path(job["output_path"]).is_file(),
                           "output_text": Path(job["output_path"]).read_text(encoding="utf8")
                           if job["output_path"] and Path(job["output_path"]).is_file() else ""} for job in jobs]
                Path(report_path).write_text(json.dumps({"timeout": timeout, "jobs": report},
                                                       ensure_ascii=False, indent=2), encoding="utf-8")
                manager.shutdown()
                store.close()
                app.exit(0 if not timeout and all(job["status"] == "completed" for job in jobs) else 1)

        timer = QTimer()
        timer.setInterval(200)
        timer.timeout.connect(check)
        timer.start()
        manager.start()
        return app.exec()


def youtube_smoke_test(request, report_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .jobs import JobManager
    from .paths import data_dir, database_path
    from .storage import Store
    from .ui.window import MainWindow
    from .youtube import TOOL_ID

    app = QApplication([])
    root = data_dir()
    store = Store(database_path(root))
    window = MainWindow(store, JobManager(store, root), root)
    window.open_tool(TOOL_ID)
    page = window.tool_views[TOOL_ID]
    page.directory.setText(request["directory"])
    page.link.setText(request["youtube_url"])
    started = time.monotonic()
    downloads = []
    steps = ["MP3", "MP4", "WMA"]
    current = None
    page.lookup()

    def finish(error=""):
        report = {"error": error, "downloads": downloads}
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        timer.stop()
        window.close()
        app.exit(1 if error else 0)

    def check():
        nonlocal current
        if time.monotonic() - started > request.get("timeout_seconds", 300):
            finish(f"Timeout: {page.status.text()}")
            return
        if page.process is not None:
            return
        if page.video is None or (current and (page.result is None or page.transcribe_button.isHidden())):
            finish(f"{page.status.text()} {page.status.toolTip()}".strip())
            return
        if current:
            downloads.append({"format": current, "path": str(page.result), "bytes": page.result.stat().st_size})
        if not steps:
            finish()
            return
        current = steps.pop(0)
        if current == "MP3":
            page.kind.setCurrentIndex(1)
            page.format.setCurrentText(current)
        elif current == "MP4":
            page.kind.setCurrentIndex(0)
            page.format.setCurrentText(current)
            page.quality.setCurrentIndex(max(0, page.quality.findData(360)))
        else:
            page.advanced.setChecked(True)
            page.advanced_kind.setCurrentIndex(1)
            index = next((i for i in range(page.muxer.count()) if page.muxer.itemData(i).name == "asf"), -1)
            page.muxer.setCurrentIndex(index)
            page.video_codec.setCurrentIndex(0)
            page.audio_codec.setCurrentText("wmav2")
        page.start_download()

    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(150)
    return app.exec()
