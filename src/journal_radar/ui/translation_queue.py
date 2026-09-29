"""Bounded, cancellable worker scheduling; never terminate a network thread."""

from collections import deque

from PySide6.QtCore import QObject, Signal

from .workers import TranslateWorker


class TranslationQueue(QObject):
    changed = Signal()
    completed = Signal(str, object)

    def __init__(self, parent=None, concurrency=2, capacity=20):
        super().__init__(parent)
        self.concurrency = concurrency
        self.capacity = capacity
        self.workers: dict[str, TranslateWorker] = {}
        self.waiting: deque[str] = deque()
        self.active: set[str] = set()

    def submit(self, worker: TranslateWorker) -> bool:
        key = worker.paper_id
        if key in self.workers or len(self.workers) >= self.capacity:
            worker.api_key = ""
            return False
        self.workers[key] = worker
        self.waiting.append(key)
        worker.finished.connect(lambda: self.finished(key))
        self.pump()
        return True

    def pump(self) -> None:
        while self.waiting and len(self.active) < self.concurrency:
            key = self.waiting.popleft()
            self.active.add(key)
            self.workers[key].start()
        self.changed.emit()

    def finished(self, key: str) -> None:
        self.active.discard(key)
        worker = self.workers.pop(key, None)
        self.completed.emit(key, worker)
        self.pump()

    def cancel(self) -> list[str]:
        removed = list(self.waiting)
        self.waiting.clear()
        for key in removed:
            worker = self.workers.pop(key)
            worker.api_key = ""
            worker.requestInterruption()
        for key in self.active:
            worker = self.workers.get(key)
            if worker:
                worker.api_key = ""
                worker.requestInterruption()
        self.changed.emit()
        return removed
