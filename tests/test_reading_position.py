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
        self.window.translation_workers[worker_id] = SimpleNamespace(
            job=job, isInterruptionRequested=lambda: False
        )
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

    def test_refresh_keeps_anchor_with_new_papers_inserted_above_reader(self):
        self.card(9).abstract_toggle.click()
        self.settle()
        paper_id = self.papers[9]["id"]
        offset = self.read(9)
        self.window.refresh_profile_id = self.profile["id"]
        source = self.profile["sources"][0]
        newest = make_paper(source, "New paper", "https://example.org/new", "2028-01", "month")
        self.window.apply_refresh({source["id"]: [newest] + self.papers}, {})
        self.settle()
        card = next(c for c in self.window.reading_state.cards() if c.paper_id == paper_id)
        self.assertTrue(card.abstract_toggle.isChecked())
        self.assertEqual(card.y() - self.scroll.value(), offset)

    def test_load_more_and_settings_render_keep_both_expansion_states(self):
        self.window.visible_limit = 5
        self.window.render_papers()
        self.settle()
        self.complete_translation(3)
        card = self.card(3)
        card.abstract_toggle.click()
        card.translation_toggle.click()
        self.settle()
        offset = self.read(3)
        self.window.load_more()
        self.settle()
        self.assertEqual(len(self.window.reading_state.cards()), 20)
        self.assertEqual(self.card(3).y() - self.scroll.value(), offset)
        self.assertTrue(self.card(3).abstract_toggle.isChecked())
        self.assertTrue(self.card(3).translation_toggle.isChecked())
        self.window.state["settings"]["refresh_minutes"] = 60
        self.window.render_papers()
        self.settle()
        self.assertEqual(self.card(3).y() - self.scroll.value(), offset)
        self.assertTrue(self.card(3).translation_toggle.isChecked())

    def test_original_and_translation_copy_full_content_when_folded(self):
        self.complete_translation(3)
        card = self.card(3)
        original = card.findChild(QLabel, "abstract")
        translated = card.abstract_parts[0]
        self.assertTrue(original.text().endswith("…"))
        self.assertTrue(translated.text().endswith("…"))
        original.copy_button.click()
        self.assertEqual(self.application.clipboard().text(), self.papers[3]["abstract"].strip())
        translated.copy_button.click()
        self.assertEqual(self.application.clipboard().text(), "中文译文。" * 350)
        card.translation_toggle.click()
        self.assertEqual(translated.text(), "中文译文。" * 350)
        self.assertFalse(card.abstract_toggle.isChecked())

    def test_small_window_long_names_and_action_buttons_fit_card(self):
        from PySide6.QtWidgets import QPushButton

        self.window.resize(920, 620)
        self.settle()
        card = self.card(0)
        self.assertGreater(card.width(), 500)
        self.window.resize(820, 500)
        self.settle()
        self.assertGreater(self.window.view.paper_scroll.height(), 220)
        for button in card.findChildren(QPushButton):
            if button.isVisible():
                self.assertLessEqual(button.x() + button.width(), card.width())
                self.assertLessEqual(button.y() + button.height(), card.height())

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
        self.assertGreater(meta.width(), self.card(0).width() * 0.4)
        paper = self.papers[0]
        paper["abstract"] = "Publication date: February 2027 Source: Learning and Instruction"
        paper["abstract_kind"] = "metadata"
        self.window.update_paper_card(paper["id"])
        self.settle()
        card = self.card(0)
        self.assertTrue(card.abstract_parts[1].isHidden())
        self.assertTrue(card.enrichment_button.isVisible())
