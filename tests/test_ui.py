"""Headless regressions for card actions, dialogs and asynchronous caching."""

import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from journal_radar.adapters.abstracts import AbstractResult
from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.domain.state import default_state
from journal_radar.services import TranslationJob
from journal_radar.services.abstracts import AbstractJob
from journal_radar.storage import StateRepository
from journal_radar.ui.main_window import MainWindow
from journal_radar.ui.paper_card import PaperCard
from journal_radar.ui.settings_dialog import SettingsDialog
from journal_radar.ui.source_editor import SourceEditor
from journal_radar.ui.workers import TranslateWorker


class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_missing_abstract_can_be_fetched_and_shown_by_background_worker(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
        ):
            window = MainWindow()
            source = create_source("Example", "rss", "https://example.org/rss")
            paper = make_paper(source, "Learning", "https://doi.org/10.1000/a", "")
            profile = window.state["profiles"][0]
            profile["sources"] = [source]
            window.state["papers"][profile["id"]] = [paper]
            window.render_papers()
            card = window.view.paper_layout.itemAt(0).widget()
            self.assertIsNotNone(card.enrichment_button)
            self.assertIsNone(card.abstract_parts)
            result = AbstractResult("An abstract about learning. " * 30, "10.1000/a")
            with patch.object(AbstractJob, "execute", return_value=result):
                card.enrichment_button.click()
                self.assertEqual(len(window.abstract_workers), 1)
                deadline = time.monotonic() + 3
                while window.abstract_workers and time.monotonic() < deadline:
                    self.application.processEvents()
                    time.sleep(0.005)
            self.assertFalse(window.abstract_workers)
            updated = window.view.paper_layout.itemAt(0).widget()
            self.assertIsNone(updated.enrichment_button)
            self.assertTrue(updated.abstract_parts[1].isEnabled())
            self.assertTrue(
                any(button.text() == "展开摘要" for button in updated.findChildren(QPushButton))
            )
            self.assertEqual(
                window.repository.load()["papers"][profile["id"]][0]["abstract"], result.text
            )
            window.close()

    def test_failed_enrichment_explains_reason_and_reenables_retry(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
        ):
            window = MainWindow()
            source = create_source("Example", "rss", "https://example.org/rss")
            paper = make_paper(
                source, "Learning", "https://example.org/p", "", abstract="A teaser…"
            )
            profile = window.state["profiles"][0]
            profile["sources"] = [source]
            window.state["papers"][profile["id"]] = [paper]
            job = AbstractJob.for_paper(profile["id"], paper)
            window.abstract_done(job, error="出版社未提供摘要")
            card = window.view.paper_layout.itemAt(0).widget()
            self.assertTrue(card.enrichment_button.isEnabled())
            self.assertEqual(paper["abstract"], "A teaser…")
            self.assertTrue(
                any("出版社未提供摘要" in label.text() for label in card.findChildren(QLabel))
            )
            window.close()

    def test_card_expand_and_translate_actions_are_independent(self):
        state = default_state()
        source = create_source("Example", "rss", "https://example.org/rss")
        text = "An abstract about learning. " * 40
        paper = make_paper(source, "Paper", "https://example.org/paper", "", abstract=text)
        card = PaperCard(paper, state["settings"], {})
        title_events, abstract_events = [], []
        card.title_requested.connect(lambda: title_events.append(True))
        card.abstract_requested.connect(lambda: abstract_events.append(True))
        toggle = next(
            button for button in card.findChildren(QPushButton) if button.text() == "展开摘要"
        )
        abstract_label = next(
            label for label in card.findChildren(QLabel) if label.objectName() == "abstract"
        )
        toggle.click()
        self.assertEqual(abstract_label.text(), text.strip())
        toggle.click()
        self.assertLess(len(abstract_label.text()), len(text))
        card.abstract_parts[1].click()
        card.title_parts[1].click()
        self.assertEqual(title_events, [True])
        self.assertEqual(abstract_events, [True])
        card.close()

    def test_metadata_cannot_be_translated_as_an_abstract(self):
        source = create_source("Example", "rss", "https://example.org/rss")
        paper = make_paper(
            source, "Paper", "https://example.org/p", "", abstract="Publication date: January 2027"
        )
        card = PaperCard(paper, default_state()["settings"], {})
        self.assertFalse(card.abstract_parts[1].isEnabled())
        card.close()

    def test_settings_and_source_fields_are_visible_and_expand_with_dialog(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
        ):
            settings = SettingsDialog(default_state(), repository=StateRepository())
            editor = SourceEditor()
            for dialog in (settings, editor):
                dialog.show()
                self.application.processEvents()
            self.assertGreater(settings.endpoint.width(), 400)
            self.assertGreater(editor.value_edit.width(), 400)
            self.assertLess(editor.name_edit.y(), 150)
            self.assertTrue(settings.endpoint.isVisible())
            settings.close()
            editor.close()

    def test_old_model_result_is_cached_under_snapshot_and_not_shown_under_new_model(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
        ):
            window = MainWindow()
            source = create_source("Example", "rss", "https://example.org/rss")
            paper = make_paper(source, "Learning", "https://example.org/p", "")
            job = TranslationJob.from_settings(paper["title"], window.state["settings"])
            window.state["settings"]["api_model"] = "new-model"
            card = window.make_paper_card(paper)
            window.translation_done(paper, "Old model translation", job)
            self.assertEqual(window.state["translations"][job.cache_key], "Old model translation")
            self.assertEqual(card.title_parts[0].text(), "")
            window.close()
            card.close()

    def test_worker_clears_secret_after_request(self):
        worker = TranslateWorker(
            "paper", "Learning", "https://example.org/api", "model", "fake-key", ""
        )
        events = []
        worker.translated.connect(lambda _, text: events.append(text))
        with patch.object(TranslationJob, "execute", return_value="学习"):
            worker.run()
        self.assertEqual(events, ["学习"])
        self.assertEqual(worker.api_key, "")

    def test_refreshed_abstract_does_not_display_a_previous_text_translation(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
        ):
            window = MainWindow()
            source = create_source("Example", "rss", "https://example.org/rss")
            paper = make_paper(
                source, "Learning", "https://example.org/p", "", abstract="Old abstract"
            )
            old_job = TranslationJob.from_settings(
                paper["abstract"], window.state["settings"], "abstract"
            )
            paper["abstract"] = "Updated abstract"
            window.state["papers"][window.state["active_profile_id"]] = [paper]
            window.render_papers()
            window.translation_done(paper, "旧摘要译文", old_job)
            self.assertEqual(window.abstract_parts[paper["id"]][0].text(), "")
            self.assertEqual(window.state["translations"][old_job.cache_key], "旧摘要译文")
            window.close()

    def test_failed_cache_write_still_displays_translation_and_reports_failure(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.dict(os.environ, JOURNAL_RADAR_HOME=folder),
        ):
            window = MainWindow()
            source = create_source("Example", "rss", "https://example.org/rss")
            paper = make_paper(source, "Learning", "https://example.org/p", "")
            card = window.make_paper_card(paper)
            job = TranslationJob.from_settings(paper["title"], window.state["settings"])
            with patch.object(window.repository, "save", side_effect=OSError("disk full")):
                window.translation_done(paper, "学习", job)
            self.assertEqual(card.title_parts[0].text(), "学习")
            self.assertIn("缓存保存失败", window.view.status_label.text())
            window.close()
            card.close()
