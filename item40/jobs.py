from __future__ import annotations

import json
import multiprocessing as mp
import queue
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .domain import JobRequest, format_transcript
from .exports import save_result
from .i18n import tr
from .storage import Store
from .worker import run_job


class JobManager(QObject):
    changed = Signal(str)
    notice = Signal(str)
    download_changed = Signal(str, float)

    def __init__(self, store: Store, root, parent=None):
        super().__init__(parent)
        self.store = store
        self.root = str(root)
        self.context = mp.get_context("spawn")
        self.process = None
        self.events = None
        self.cancel_event = None
        self.active: str | None = None
        self.download_only = False
        self.enabled = False
        self.cancel_time = None
        self.segments: list[dict] = []
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def enqueue(self, paths, model, language, device):
        ids = []
        for path in paths:
            job = JobRequest(source=str(path), model=model, language=language, device=device)
            self.store.add(job)
            ids.append(job.id)
            self.changed.emit(job.id)
        return ids

    def start(self):
        self.enabled = True
        self._next()

    def combine_sources(self, job_ids, paths, model, language, device):
        if len(paths) < 2:
            raise ValueError(tr('Выберите хотя бы два файла.'))
        request = JobRequest(source=paths[0], source_files=list(paths), model=model,
                             language=language, device=device)
        self.store.combine_sources(request, job_ids)
        self.changed.emit(request.id)
        return request.id

    def pause(self):
        self.enabled = False

    def _next(self):
        if self.active or not self.enabled:
            return
        pending = self.store.pending()
        if pending:
            job = pending[0]
            self._launch(JobRequest(**json.loads(job["options"])))
        else:
            self.enabled = False

    def _launch(self, request, download_only=False):
        self.active = request.id
        self.download_only = download_only
        self.segments = []
        self.cancel_time = None
        self.events = self.context.Queue()
        self.cancel_event = self.context.Event()
        if not download_only:
            self.store.update(request.id, status="running", progress=0, stage=tr('Подготовка'), error="",
                              transcript="", segments=[], edited=0)
        self.process = self.context.Process(target=run_job,
            args=(request, self.root, self.events, self.cancel_event), daemon=True)
        try:
            self.process.start()
        except Exception as error:
            self._finish("failed", str(error))
            return
        self.changed.emit(request.id)

    def download_model(self, model):
        if self.active:
            self.notice.emit(tr('Дождитесь завершения текущей задачи или отмените её.'))
            return
        self._launch(JobRequest(source="", model=model, tool_id="models.download"), download_only=True)

    def retry(self, job_id):
        job = self.store.get(job_id)
        if job and job["status"] in {"failed", "cancelled", "interrupted"}:
            self.store.restore_source(job_id)
            self.store.update(job_id, status="queued", progress=0, error="", stage=tr('Повторная попытка'))
            self.changed.emit(job_id)

    def cancel(self, job_id):
        if job_id == self.active:
            self.cancel_event.set()
            self.cancel_time = time.monotonic()
        elif self.store.get(job_id):
            self.store.update(job_id, status="cancelled", stage=tr('Отменено'))
            self.changed.emit(job_id)

    def remove_sources(self, job_ids):
        for job_id in job_ids:
            self.store.hide_source(job_id)
            if job_id == self.active:
                self.cancel(job_id)
        for job_id in job_ids:
            self.changed.emit(job_id)

    def poll(self):
        if not self.active:
            self._next()
            return
        # Bounded drain keeps the UI responsive on very large transcripts.
        for _ in range(150):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind, data = event["kind"], event["data"]
            if kind in {"completed", "failed", "cancelled"}:
                self._finish(kind, data.get("error", ""))
                return
            if kind == "notice":
                self.notice.emit(data["message"])
            elif kind == "progress":
                if self.download_only:
                    self.download_changed.emit(data["stage"], data["progress"])
                else:
                    self.store.update(self.active, stage=data["stage"], progress=data["progress"])
                    self.changed.emit(self.active)
            elif kind == "segment" and not self.download_only:
                self.segments.append(data["segment"])
                job = self.store.get(self.active)
                values = {"segments": self.segments}
                if not job["edited"]:
                    values["transcript"] = format_transcript(self.segments)
                self.store.update(self.active, **values)
                self.changed.emit(self.active)

        if self.cancel_time and time.monotonic() - self.cancel_time > 2:
            self.process.terminate()
            self._finish("cancelled")
        elif self.process is not None and not self.process.is_alive():
            # Allow the multiprocessing queue feeder time to deliver terminal events.
            if not hasattr(self, "dead_since") or self.dead_since is None:
                self.dead_since = time.monotonic()
            elif time.monotonic() - self.dead_since > 1:
                self._finish("cancelled" if self.cancel_time else "failed",
                             tr('Процесс обработки завершился неожиданно. Попробуйте режим процессора.'))
        else:
            self.dead_since = None

    def _finish(self, status, error=""):
        job_id = self.active
        if self.process and self.process.pid is not None:
            self.process.join(timeout=0.2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=1)
            self.process.close()
        elif self.process:
            self.process.close()
        if self.events:
            self.events.close()
            self.events.cancel_join_thread()
        if self.download_only:
            message = {"completed": tr('Модель скачана'), "cancelled": tr('Загрузка отменена')}.get(status, error)
            self.download_changed.emit(message, 1 if status == "completed" else 0)
        elif job_id:
            job = self.store.get(job_id)
            values = {"status": status, "error": error,
                      "stage": {"completed": tr('Готово') if job["transcript"] else tr('Речь не обнаружена'),
                                "cancelled": tr('Отменено · частичный текст сохранён'), "failed": error}[status]}
            if status == "completed":
                values["progress"] = 1
            self.store.update(job_id, **values)
            if status == "completed":
                save_result(self.store, job_id)
        self.active = None
        self.process = None
        self.events = None
        self.cancel_time = None
        self.dead_since = None
        self.changed.emit(job_id or "")

    def shutdown(self):
        self.enabled = False
        self.timer.stop()
        if self.active:
            self.cancel_event.set()
            self.process.join(timeout=0.3)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=2)
            if not self.download_only:
                self.store.update(self.active, status="interrupted", stage=tr('Прервано при закрытии программы'))
            self.process.close()
            self.events.close()
            self.events.cancel_join_thread()
