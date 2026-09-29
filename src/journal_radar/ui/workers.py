"""Workers for both desktop platforms."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QThread, Signal

from ..domain.models import ContentType, Language, Source
from ..errors import compact_error
from ..services import TranslationJob, refresh_sources
from ..services.abstracts import AbstractJob
from ..services.citations import CitationJob


class CancellableWorker(QThread):
    """Keep cancellation intent even after Qt resets a finished thread's flag."""

    def __init__(self):
        super().__init__()
        self.cancel_requested = False

    def requestInterruption(self) -> None:
        self.cancel_requested = True
        super().requestInterruption()

    def isInterruptionRequested(self) -> bool:
        return self.cancel_requested or super().isInterruptionRequested()


class AbstractWorker(CancellableWorker):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, job: AbstractJob):
        super().__init__()
        self.job = job

    def run(self) -> None:
        try:
            result = self.job.execute()
            if not self.isInterruptionRequested():
                self.loaded.emit(result)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(compact_error(error))


class RefreshWorker(CancellableWorker):
    progress = Signal(str)
    loaded = Signal(object, object)

    def __init__(self, sources: list[Source], proxy: str):
        super().__init__()
        self.sources = deepcopy(sources)
        self.proxy = proxy

    def run(self) -> None:
        papers, statuses = refresh_sources(
            self.sources,
            self.proxy,
            lambda text: self.progress.emit(text) if not self.isInterruptionRequested() else None,
            self.isInterruptionRequested,
        )
        if not self.isInterruptionRequested():
            self.loaded.emit(papers, statuses)


class TranslateWorker(CancellableWorker):
    translated = Signal(str, str)
    failed = Signal(str, str)

    def __init__(
        self,
        paper_id: str,
        title: str,
        endpoint: str,
        model: str,
        api_key: str,
        proxy: str,
        target_language: Language = "zh",
        content_type: ContentType = "title",
    ):
        super().__init__()
        self.paper_id = paper_id
        self.job = TranslationJob(title, endpoint, model, proxy, content_type, target_language)
        self.api_key = api_key

    def run(self) -> None:
        try:
            result = self.job.execute(self.api_key, self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.translated.emit(self.paper_id, result)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(self.paper_id, compact_error(error))
        finally:
            self.api_key = ""


class CitationWorker(CancellableWorker):
    loaded = Signal(object)
    failed = Signal(str)

    def __init__(self, job: CitationJob):
        super().__init__()
        self.job = job

    def run(self) -> None:
        try:
            result = self.job.execute(self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                self.loaded.emit(result)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(compact_error(error))
