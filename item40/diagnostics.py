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
    app = QCoreApplication([])
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / "smoke.sqlite3")
        store.set_setting("output_dir", str(Path(temp) / "output"))
        manager = JobManager(store, data_dir())
        ids = manager.enqueue(request["files"], request.get("model", "small"), request.get("language", "ru"),
                              request.get("device", "cpu"))
        started = time.monotonic()

        def check():
            jobs = [store.get(job_id) for job_id in ids]
            timeout = time.monotonic() - started > request.get("timeout_seconds", 180)
            if timeout or all(job["status"] in {"completed", "cancelled", "failed"} for job in jobs):
                report = [{"source": job["source"], "status": job["status"], "text": job["transcript"],
                           "error": job["error"]} for job in jobs]
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
