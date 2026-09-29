"""Keep the paper being read stable when background results change card heights."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from journal_radar.adapters.abstracts import AbstractResult
from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.services.abstracts import AbstractJob
from journal_radar.services.translations import TranslationJob
from journal_radar.ui.main_window import MainWindow
from journal_radar.ui.theme import STYLE


class ReadingPositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setStyleSheet(STYLE)

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        environment = patch.dict(os.environ, JOURNAL_RADAR_HOME=folder.name)
        environment.start()
        self.addCleanup(environment.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        self.profile = self.window.state["profiles"][0]
        source = create_source("[必读] Learning and Instruction", "rss", "https://example.org/rss")
        self.profile["sources"] = [source]
        self.papers = [
            make_paper(
                source,
                f"Paper {index}: Learning in a prolonged crisis",
                f"https://example.org/{index}",
                "2027-02",
                "month",
                abstract="An abstract about learning at home and school. " * 30,
            )
            for index in range(20)
        ]
        self.window.state["papers"][self.profile["id"]] = self.papers
        self.window.update_profile_ui()
        self.window.show()
        self.settle()
        self.scroll = self.window.view.paper_scroll.verticalScrollBar()

    def settle(self):
        for _ in range(8):
            self.application.processEvents()

    def card(self, index):
        return self.window.view.paper_layout.itemAt(index).widget()

    def read(self, index):
        self.scroll.setValue(self.card(index).y() + 28)
        self.settle()
        return self.card(index).y() - self.scroll.value()

    def complete_translation(self, index, content_type="abstract"):
        paper = self.papers[index]
        text = paper["abstract"] if content_type == "abstract" else paper["title"]
        job = TranslationJob.from_settings(
            text.strip(), self.window.state["settings"], content_type
        )
        worker_id = paper["id"] + ":" + content_type
        self.window.translation_workers[worker_id] = SimpleNamespace(job=job)
        self.window.translation_done(paper, "中文译文。" * 350, job)
        self.window.translation_finished(worker_id)
        self.settle()

    def test_abstract_translation_keeps_current_card_and_expansion(self):
        original = self.card(8)
        original.abstract_toggle.click()
        self.settle()
        offset = self.read(8)
        self.complete_translation(8)
        self.assertIs(self.card(8), original)
        self.assertTrue(original.abstract_toggle.isChecked())
        self.assertEqual(original.y() - self.scroll.value(), offset)
        self.assertTrue(original.abstract_parts[0].isVisible())
        self.assertFalse(original.abstract_parts[1].isEnabled())

    def test_result_above_reader_preserves_visible_paper_even_after_user_scrolls(self):
        # The user can move to another paper while a translation is pending.
        self.read(3)
        offset = self.read(10)
        original = self.card(10)
        old_scroll = self.scroll.value()
        self.complete_translation(1, "title")
        self.assertIs(self.card(10), original)
        self.assertEqual(original.y() - self.scroll.value(), offset)
        self.assertGreater(self.scroll.value(), old_scroll)

    def test_enrichment_replaces_only_changed_card_and_retains_expansion(self):
        self.card(2).abstract_toggle.click()
        self.settle()
        original = self.card(9)
        offset = self.read(9)
        job = AbstractJob.for_paper(self.profile["id"], self.papers[2])
        self.window.abstract_done(
            job, AbstractResult("A much longer abstract. " * 100, "10.1000/a")
        )
        self.settle()
        self.assertIs(self.card(9), original)
        self.assertTrue(self.card(2).abstract_toggle.isChecked())
        self.assertEqual(original.y() - self.scroll.value(), offset)

    def test_multiple_results_in_one_event_cycle_keep_one_reading_anchor(self):
        offset = self.read(10)
        for index in (1, 3):
            paper = self.papers[index]
            job = TranslationJob.from_settings(paper["title"], self.window.state["settings"])
            self.window.translation_done(paper, "中文译文。" * 350, job)
        self.settle()
        self.assertEqual(self.card(10).y() - self.scroll.value(), offset)

    def test_pending_anchor_does_not_restore_after_filter_changes(self):
        self.read(10)
        paper = self.papers[1]
        job = TranslationJob.from_settings(paper["title"], self.window.state["settings"])
        self.window.translation_done(paper, "中文译文。" * 350, job)
        self.window.view.search.setText("Paper 0:")
        self.settle()
        self.assertEqual(self.window.view.paper_layout.count(), 1)
        self.assertEqual(self.scroll.value(), 0)

    def test_long_source_gets_footer_space_and_metadata_has_no_translation_action(self):
        meta = self.card(0).findChild(QLabel, "paperMeta")
        self.assertGreater(meta.width(), 400)
        paper = self.papers[0]
        paper["abstract"] = "Publication date: February 2027 Source: Learning and Instruction"
        paper["abstract_kind"] = "metadata"
        self.window.update_paper_card(paper["id"])
        self.settle()
        card = self.card(0)
        self.assertTrue(card.abstract_parts[1].isHidden())
        self.assertTrue(card.enrichment_button.isVisible())
