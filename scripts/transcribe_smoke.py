"""Real end-to-end smoke: CPU/GPU, source files, process isolation, and queue recovery.

Usage: python scripts/transcribe_smoke.py --device cpu audio.m4a audio.flac
Models are cached in the normal app data directory. No artificial transcript is injected.
"""
import argparse
import json
import multiprocessing
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    multiprocessing.freeze_support()
    sys.stdout.reconfigure(encoding="utf-8")
    from PySide6.QtCore import QCoreApplication, QTimer

    from item40.jobs import JobManager
    from item40.paths import data_dir
    from item40.storage import Store

    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["cpu", "cuda", "auto"], default="cpu")
    parser.add_argument("--model", default="small")
    parser.add_argument("files", nargs="+")
    args = parser.parse_args()
    app = QCoreApplication([])
    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    database = artifacts / "smoke.sqlite3"
    store = Store(database)
    store.set_setting("output_dir", str(artifacts / "results"))
    manager = JobManager(store, data_dir())
    ids = manager.enqueue([str(Path(path).resolve()) for path in args.files], args.model, "ru", args.device)
    last_stage = [""]
    last_print = [0.0]

    def check():
        jobs = [store.get(job_id) for job_id in ids]
        if manager.active:
            active = store.get(manager.active)
            stage = active["stage"]
            if stage != last_stage[0] and time.monotonic() - last_print[0] > 5:
                print(stage, flush=True)
                last_stage[0] = stage
                last_print[0] = time.monotonic()
        if all(job["status"] in {"failed", "completed", "cancelled"} for job in jobs):
            report = [{"source": job["source"], "status": job["status"], "text": job["transcript"],
                       "error": job["error"]} for job in jobs]
            (artifacts / f"smoke-{args.device}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                               encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            manager.shutdown()
            store.close()
            app.exit(0 if any(job["status"] == "completed" and job["transcript"] for job in jobs) else 1)

    timer = QTimer()
    timer.timeout.connect(check)
    timer.start(400)
    manager.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
