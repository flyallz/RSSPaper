"""Bounded scheduling, duplicate prevention and secret cleanup on cancellation."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from journal_radar.ui.translation_queue import TranslationQueue


class FakeWorker(QObject):
    finished = Signal()

    def __init__(self, key):
        super().__init__()
        self.paper_id = key
        self.api_key = "fake-key"
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def requestInterruption(self):
        self.cancelled = True


class TaskQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_two_active_jobs_then_queued_job_starts_when_slot_frees(self):
        queue = TranslationQueue(concurrency=2)
        workers = [FakeWorker(str(i)) for i in range(4)]
        for worker in workers:
            self.assertTrue(queue.submit(worker))
        self.assertEqual([w.started for w in workers], [True, True, False, False])
        workers[0].finished.emit()
        self.assertTrue(workers[2].started)
        self.assertEqual(len(queue.active), 2)
        self.assertEqual(list(queue.waiting), ["3"])

    def test_capacity_and_duplicate_rejections_clear_secrets(self):
        queue = TranslationQueue(capacity=2)
        queue.submit(FakeWorker("a"))
        queue.submit(FakeWorker("b"))
        for key in ("a", "c"):
            rejected = FakeWorker(key)
            self.assertFalse(queue.submit(rejected))
            self.assertEqual(rejected.api_key, "")
            self.assertFalse(rejected.started)

    def test_cancel_removes_waiting_jobs_and_does_not_start_them(self):
        queue = TranslationQueue(concurrency=1)
        first, second = FakeWorker("a"), FakeWorker("b")
        queue.submit(first)
        queue.submit(second)
        self.assertEqual(queue.cancel(), ["b"])
        self.assertTrue(first.cancelled)
        self.assertEqual(second.api_key, "")
        self.assertFalse(second.started)
        first.finished.emit()
        self.assertFalse(queue.workers)
        self.assertFalse(queue.active)
        self.assertFalse(second.started)
