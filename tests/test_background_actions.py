"""Native window workflows for stale errors, cancellation and safe shutdown."""

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.domain.state import new_profile
from journal_radar.services.translations import TranslationJob
from journal_radar.ui.main_window import MainWindow
from journal_radar.ui.settings_dialog import SettingsDialog
from journal_radar.ui.workers import TranslateWorker


class BackgroundActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, JOURNAL_RADAR_HOME=folder.name)
        env.start()
        self.addCleanup(env.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.profile = self.window.state["profiles"][0]
        source = create_source("Example", "rss", "https://example.org/rss")
        self.profile["sources"] = [source]
        self.window.state["settings"].update(
            api_endpoint="https://example.org/api", api_model="model", refresh_minutes=0
        )
        self.papers = [
            make_paper(
                source, f"Paper {i}", f"https://example.org/{i}", "", abstract="An abstract."
            )
            for i in range(3)
        ]
        self.window.state["papers"][self.profile["id"]] = self.papers
        self.window.update_profile_ui()
        self.window.show()
        self.settle()

    def settle(self):
        for _ in range(5):
            self.app.processEvents()

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.settle()
            time.sleep(0.005)
        self.assertTrue(condition())

    def start_blocked_jobs(self, count, release):
        def execute(job, key, cancelled=None):
            release.wait(2)
            return "A completed translation"

        with (
            patch("journal_radar.ui.main_window.load_api_key", return_value="fake-key"),
            patch.object(TranslationJob, "execute", autospec=True, side_effect=execute),
        ):
            for paper in self.papers[:count]:
                self.window.translate_abstract(paper)
            # Keep the patched execution in place until all workers are released by the caller.
            yield
            release.set()
            self.wait_until(lambda: not self.window.translation_workers)

    def test_cancel_running_and_queued_jobs_never_caches_results(self):
        from contextlib import contextmanager

        release = threading.Event()
        with contextmanager(self.start_blocked_jobs)(3, release):
            self.assertEqual(len(self.window.translation_queue.active), 2)
            self.assertEqual(len(self.window.translation_queue.waiting), 1)
            self.window.view.cancel_button.click()
            self.assertFalse(self.window.translation_queue.waiting)
            queued_parts = self.window.abstract_parts[self.papers[2]["id"]]
            self.assertTrue(queued_parts[1].isEnabled())
        self.assertFalse(self.window.state["translations"])
        self.assertFalse(self.window.view.cancel_button.isEnabled())
        for paper in self.papers:
            self.assertTrue(self.window.abstract_parts[paper["id"]][1].isEnabled())

    def test_closing_requests_cancel_and_closes_after_worker_exits(self):
        from contextlib import contextmanager

        release = threading.Event()
        with contextmanager(self.start_blocked_jobs)(1, release):
            self.window.close()
            self.assertTrue(self.window.closing)
            self.assertTrue(self.window.isVisible())
            self.assertTrue(
                next(iter(self.window.translation_workers.values())).isInterruptionRequested()
            )
        self.wait_until(lambda: not self.window.isVisible())
        self.assertFalse(self.window.state["translations"])

    def test_cancel_after_network_finishes_but_before_queued_result_is_delivered(self):
        with (
            patch("journal_radar.ui.main_window.load_api_key", return_value="fake-key"),
            patch.object(TranslationJob, "execute", return_value="Result"),
        ):
            self.window.translate_abstract(self.papers[0])
            worker = next(iter(self.window.translation_workers.values()))
            self.assertTrue(worker.wait(2000))
            self.window.cancel_tasks()
            self.settle()
        self.assertFalse(self.window.state["translations"])
        self.assertFalse(self.window.translation_workers)

    def test_parent_close_cancels_active_settings_test_and_waits_for_exit(self):
        release = threading.Event()
        dialog = SettingsDialog(self.window.state, self.window)
        dialog.key_edit.setText("fake-key")
        dialog.show()

        def execute(job, key, cancelled=None):
            release.wait(2)
            return "Result"

        with patch.object(TranslationJob, "execute", autospec=True, side_effect=execute):
            dialog.test_translation()
            self.window.close()
            try:
                self.assertTrue(dialog.cancel_when_finished)
                self.assertTrue(self.window.closing)
                self.assertTrue(self.window.isVisible())
                self.assertTrue(dialog.test_worker.isInterruptionRequested())
            finally:
                release.set()
            self.wait_until(lambda: not dialog.test_worker.isRunning())
            self.wait_until(lambda: not self.window.isVisible())
        self.assertFalse(dialog.isVisible())
        self.assertNotIn("测试成功", dialog.test_label.text())

    def test_old_failure_does_not_touch_replaced_abstract_or_current_model(self):
        paper = self.papers[0]
        old = TranslationJob.from_settings(
            paper["abstract"], self.window.state["settings"], "abstract"
        )
        paper["abstract"] = "新的中文摘要"
        self.window.update_paper_card(paper["id"])
        button = self.window.abstract_parts[paper["id"]][1]
        before = (button.text(), self.window.view.status_label.text())
        with patch.object(QMessageBox, "warning") as warning:
            self.window.translation_failed(
                paper, "old failure", "abstract", old, self.profile["id"]
            )
            self.assertEqual((button.text(), self.window.view.status_label.text()), before)
            self.assertFalse(warning.called)
        current = TranslationJob.from_settings(paper["title"], self.window.state["settings"])
        self.window.state["settings"]["api_model"] = "another-model"
        self.window.translation_failed(
            paper, "old model failure", "title", current, self.profile["id"]
        )
        self.assertEqual(self.window.view.status_label.text(), before[1])

    def test_other_profile_failure_is_ignored_and_matching_failure_allows_retry(self):
        paper = self.papers[0]
        job = TranslationJob.from_settings(paper["title"], self.window.state["settings"])
        other = new_profile("Other")
        self.window.state["profiles"].append(other)
        status = self.window.view.status_label.text()
        self.window.translation_failed(paper, "wrong profile", "title", job, other["id"])
        self.assertEqual(self.window.view.status_label.text(), status)
        self.window.translation_failed(paper, "request failed", "title", job, self.profile["id"])
        button = self.window.card_parts[paper["id"]][1]
        self.assertTrue(button.isEnabled())
        self.assertIn("request failed", button.toolTip())

    def test_cancel_intent_survives_worker_completion(self):
        worker = TranslateWorker("paper:title", "Title", "", "model", "fake", "")
        worker.requestInterruption()
        with patch.object(TranslationJob, "execute", return_value="Result"):
            results = []
            worker.translated.connect(lambda *args: results.append(args))
            worker.run()
        self.assertTrue(worker.isInterruptionRequested())
        self.assertFalse(results)
        self.assertEqual(worker.api_key, "")
