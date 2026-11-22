from __future__ import annotations

import multiprocessing as mp
import queue
import time

from PySide6.QtCore import QObject, QTimer, Signal

from .i18n import tr


def run_task(target, args, events, cancel, language):
    from .i18n import set_language
    from .youtube import contain_processes

    set_language(language)
    try:
        contain_processes()
        target(*args, events, cancel)
    except Exception:
        from .i18n import tr

        events.put(("failed", {"error": tr("Процесс обработки завершился неожиданно.")}))


class TaskController(QObject):
    event = Signal(str, dict)
    finished = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.context = mp.get_context("spawn")
        self.process = None
        self.events = None
        self.cancel_event = None
        self.cancel_time = None
        self.dead_since = None
        self.timer = QTimer(self, interval=80)
        self.timer.timeout.connect(self.poll)

    def start(self, target, *args):
        from .i18n import language

        if self.process is not None:
            return
        self.events = self.context.Queue()
        self.cancel_event = self.context.Event()
        self.process = self.context.Process(target=run_task,
            args=(target, args, self.events, self.cancel_event, language()), daemon=True)
        try:
            self.process.start()
        except (OSError, RuntimeError):
            self.finish("failed", {"error": tr('Не удалось запустить обработку.')})
            return
        self.timer.start()

    def cancel(self):
        if self.process is not None and self.cancel_time is None:
            self.cancel_event.set()
            self.cancel_time = time.monotonic()

    def poll(self):
        for _ in range(100):
            try:
                kind, values = self.events.get_nowait()
            except queue.Empty:
                break
            if kind in {"completed", "failed", "cancelled"}:
                self.finish(kind, values)
                return
            self.event.emit(kind, values)
        now = time.monotonic()
        if self.cancel_time is not None and now - self.cancel_time > 2:
            self.finish("cancelled", {})
        elif not self.process.is_alive():
            if self.dead_since is None:
                self.dead_since = now
            elif now - self.dead_since > 0.5:
                self.finish("failed", {"error": tr('Процесс обработки завершился неожиданно.')})

    def finish(self, kind, values):
        self.shutdown()
        self.finished.emit(kind, values)

    def shutdown(self):
        self.timer.stop()
        if self.process is not None:
            if self.process.pid is not None:
                self.cancel_event.set()
                self.process.join(timeout=0.2)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=2)
            self.process.close()
            self.events.close()
            self.events.cancel_join_thread()
        self.process = self.events = self.cancel_event = self.cancel_time = self.dead_since = None
