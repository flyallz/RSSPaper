"""New metadata workers obey the existing window shutdown and cache rules."""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.ui.main_window import MainWindow
from journal_radar.ui.rank_dialog import RankDialog
from journal_radar.ui.settings_dialog import SettingsDialog


class PublicationBackgroundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, condition):
        deadline = time.monotonic() + 4
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition())

    def test_parent_close_cancels_rank_dialog_and_settings_rank_test(self):
        for settings_test in (False, True):
            with (
                self.subTest(settings_test=settings_test),
                tempfile.TemporaryDirectory() as folder,
                patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
            ):
                window = MainWindow()
                profile = window.state["profiles"][0]
                source = create_source("Example", "rss", "https://example.org/feed")
                profile["sources"] = [source]
                paper = make_paper(source, "Paper", "https://example.org/1", "")
                paper["publication_name"] = "Confirmed Journal"
                window.state["papers"][profile["id"]] = [paper]
                window.state["settings"]["rank_enabled"] = True
                window.show()
                release = threading.Event()

                def query(*args):
                    release.wait(2)
                    return {"name": "Confirmed Journal", "retrieved_at": "2026-09-29", "labels": []}

                with (
                    patch("journal_radar.services.ranks.query_rank", side_effect=query),
                    patch("journal_radar.ui.rank_dialog.load_api_key", return_value="fake"),
                    patch("journal_radar.ui.settings_dialog.load_api_key", return_value="fake"),
                ):
                    if settings_test:
                        dialog = SettingsDialog(window.state, window, window.repository)
                        dialog.show()
                        dialog.test_rank()
                        worker = dialog.test_worker
                    else:
                        dialog = RankDialog(
                            window.state, profile["id"], paper, window.repository, window
                        )
                        dialog.show()
                        dialog.query()
                        worker = dialog.worker
                    self.wait_until(worker.isRunning)
                    try:
                        window.close()
                        self.assertTrue(window.isVisible())
                        self.assertTrue(worker.isInterruptionRequested())
                    finally:
                        release.set()
                    self.wait_until(lambda: not worker.isRunning() and not window.isVisible())
                    self.assertEqual(window.state["publication_ranks"], {})
                    self.assertEqual(paper["publication_name"], "Confirmed Journal")
                    window.close()

    def test_completed_rank_result_queued_before_parent_close_is_ignored(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
        ):
            window = MainWindow()
            profile = window.state["profiles"][0]
            source = create_source("Example", "rss", "https://example.org/feed")
            profile["sources"] = [source]
            paper = make_paper(source, "Paper", "https://example.org/1", "")
            paper["publication_name"] = "Confirmed Journal"
            window.state["papers"][profile["id"]] = [paper]
            window.state["settings"]["rank_enabled"] = True
            window.show()
            with (
                patch("journal_radar.ui.rank_dialog.load_api_key", return_value="fake"),
                patch(
                    "journal_radar.services.ranks.query_rank",
                    return_value={
                        "name": "Confirmed Journal",
                        "retrieved_at": "2026-09-29",
                        "labels": [],
                    },
                ),
            ):
                dialog = RankDialog(window.state, profile["id"], paper, window.repository, window)
                dialog.show()
                dialog.query()
                self.assertTrue(dialog.worker.wait(2000))
                window.close()
                for _ in range(6):
                    self.app.processEvents()
                self.assertEqual(window.state["publication_ranks"], {})
                self.assertTrue(dialog.worker.isInterruptionRequested())

    def test_import_saved_page_updates_only_matching_paper_and_preserves_filters(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
        ):
            window = MainWindow()
            profile = window.state["profiles"][0]
            source = create_source(
                "CE", "rss", "https://rss.sciencedirect.com/publication/science/03601315"
            )
            profile["sources"] = [source]
            paper = make_paper(
                source,
                "Learning Paper",
                "https://www.sciencedirect.com/science/article/pii/example",
                "",
                abstract="Teaser...",
            )
            window.state["papers"][profile["id"]] = [paper]
            window.update_profile_ui()
            window.view.search.setText("Learning")
            path = Path(folder) / "page.html"
            path.write_text(
                '<h1>Learning Paper</h1><div class="abstract"><p>Source abstract.</p></div>'
            )
            with patch(
                "journal_radar.ui.main_window.QFileDialog.getOpenFileName",
                return_value=(str(path), ""),
            ):
                window.import_web_abstract(paper)
            self.assertEqual(paper["abstract"], "Source abstract.")
            self.assertEqual(paper["abstract_kind"], "full")
            self.assertIn("用户导入", paper["abstract_source"])
            self.assertEqual(window.view.search.text(), "Learning")
            window.close()
