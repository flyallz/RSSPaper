"""Registered citation identity, caching and explicit clipboard workflows."""

import json
import os
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QPushButton

from journal_radar.adapters.citations import CitationResult, arxiv_doi, fetch_citation
from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.domain.state import default_state, validate_state
from journal_radar.services.citations import CitationJob, apply_citation
from journal_radar.services.refresh import apply_refresh
from journal_radar.ui.citation_dialog import CitationDialog
from journal_radar.ui.paper_card import PaperCard


class CitationTests(unittest.TestCase):
    def setUp(self):
        self.state = default_state()
        self.profile = self.state["profiles"][0]
        self.source = create_source("Journal", "rss", "https://example.org/rss")
        self.profile["sources"] = [self.source]
        self.paper = make_paper(self.source, "Learning & AI", "https://example.org/article", "")
        self.state["papers"][self.profile["id"]] = [self.paper]
        self.result = CitationResult("10.1000/a", "apa", "Author. (2026). Learning & AI.")

    def metadata(self, **kwargs):
        return json.dumps(
            {
                "DOI": "10.1000/a",
                "title": "Learning &amp; AI",
                "author": [{"family": "Author"}],
                "issued": {"date-parts": [[2026]]},
                **kwargs,
            }
        ).encode()

    def test_apa_negotiates_csl_and_plain_text(self):
        with patch(
            "journal_radar.adapters.citations.read_bytes",
            side_effect=[self.metadata(), b"Author. (2026). <i>Learning &amp; AI</i>."],
        ) as read:
            result = fetch_citation("10.1000/A", self.paper["title"], self.paper["url"])
        self.assertEqual(result.text, "Author. (2026). Learning & AI.")
        self.assertIn("style=apa", read.call_args.kwargs["accept"])
        self.assertEqual(
            read.call_args_list[0].kwargs["accept"], "application/vnd.citationstyles.csl+json"
        )

    def test_wrong_doi_or_title_stops_before_formatting(self):
        for change in ({"DOI": "10.1000/b"}, {"title": "Other paper"}):
            with patch(
                "journal_radar.adapters.citations.read_bytes", return_value=self.metadata(**change)
            ) as read:
                with self.assertRaises(ValueError):
                    fetch_citation("10.1000/a", self.paper["title"], "")
                self.assertEqual(read.call_count, 1)

    def test_missing_metadata_is_warned_without_invention(self):
        with patch(
            "journal_radar.adapters.citations.read_bytes",
            side_effect=[
                self.metadata(author=[], issued={}, type="article-journal"),
                b"Learning & AI. (n.d.).",
            ],
        ):
            result = fetch_citation("10.1000/a", self.paper["title"], "")
        self.assertIn("作者", result.warnings)
        self.assertIn("年份", result.warnings)
        self.assertIn("期刊", result.warnings)

    def test_invalid_service_response_and_structured_formats(self):
        for format, body in (
            ("apa", b"<html>Failure</html>"),
            ("bibtex", b"Error"),
            ("ris", b"TY  - JOUR\nMissing end"),
        ):
            with patch(
                "journal_radar.adapters.citations.read_bytes", side_effect=[self.metadata(), body]
            ):
                with self.assertRaises(ValueError):
                    fetch_citation("10.1000/a", self.paper["title"], "", format)
        for format, body in (
            ("bibtex", b"@article{a, title={Learning & AI}}"),
            ("ris", b"TY  - JOUR\nTI  - Learning & AI\nER  -"),
        ):
            with patch(
                "journal_radar.adapters.citations.read_bytes", side_effect=[self.metadata(), body]
            ):
                self.assertEqual(
                    fetch_citation("10.1000/a", self.paper["title"], "", format).text, body.decode()
                )

    def test_cancellation_stops_subsequent_request(self):
        flags = iter([False, False, True])
        with patch(
            "journal_radar.adapters.citations.read_bytes", return_value=self.metadata()
        ) as read:
            with self.assertRaisesRegex(ValueError, "取消"):
                fetch_citation("10.1000/a", self.paper["title"], "", cancelled=lambda: next(flags))
            self.assertEqual(read.call_count, 1)

    def test_arxiv_identifiers_validate_host_and_remove_version(self):
        self.assertEqual(
            arxiv_doi("https://arxiv.org/pdf/2202.01037v2.pdf"), "10.48550/arxiv.2202.01037"
        )
        self.assertEqual(
            arxiv_doi("https://arxiv.org/abs/astro-ph/9901234"), "10.48550/arxiv.astro-ph/9901234"
        )
        self.assertEqual(arxiv_doi("https://example.org/abs/2202.01037"), "")

    def test_refresh_retains_citations_only_for_same_paper(self):
        job = CitationJob.for_paper(self.profile["id"], self.paper)
        self.assertTrue(apply_citation(self.state, job, self.result))
        fresh = deepcopy(self.paper)
        for key in ("citations", "citation_doi", "citation_warning"):
            fresh.pop(key)
        apply_refresh(self.state, self.profile["id"], {self.source["id"]: [fresh]}, {})
        self.assertEqual(
            self.state["papers"][self.profile["id"]][0]["citations"]["apa"], self.result.text
        )
        fresh["title"] = "Other paper"
        apply_refresh(self.state, self.profile["id"], {self.source["id"]: [fresh]}, {})
        self.assertNotIn("citations", self.state["papers"][self.profile["id"]][0])

    def test_deleted_source_or_changed_paper_ignores_completion(self):
        job = CitationJob.for_paper(self.profile["id"], self.paper)
        self.paper["title"] = "Changed"
        self.assertFalse(apply_citation(self.state, job, self.result))
        self.paper["title"] = job.title
        self.profile["sources"] = []
        self.assertFalse(apply_citation(self.state, job, self.result))

    def test_cache_validation(self):
        self.paper["citations"] = {"apa": {"bad": "nested"}}
        with self.assertRaisesRegex(ValueError, "引用缓存"):
            validate_state(self.state)


class CitationUITests(unittest.TestCase):
    setUp = CitationTests.setUp

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, condition):
        deadline = time.monotonic() + 3
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.assertTrue(condition())

    def test_metadata_no_longer_offers_copy_publication_info(self):
        self.paper.update(abstract="Publication date: January 2027", abstract_kind="metadata")
        card = PaperCard(self.paper, self.state["settings"], {})
        card.show()
        self.app.processEvents()
        visible = [button.text() for button in card.findChildren(QPushButton) if button.isVisible()]
        self.assertNotIn("复制出版信息", visible)
        self.assertIn("复制引用", visible)
        card.close()

    def test_preview_does_not_change_clipboard_until_user_copies(self):
        self.paper.update(citation_doi=self.result.doi, citations={"apa": self.result.text})
        self.app.clipboard().setText("Keep me")
        dialog = CitationDialog(self.state, self.profile["id"], self.paper, Mock())
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.format_combo.currentData(), "apa")
        self.assertEqual(dialog.preview.toPlainText(), self.result.text)
        self.assertEqual(self.app.clipboard().text(), "Keep me")
        dialog.copy_button.click()
        self.assertEqual(self.app.clipboard().text(), self.result.text)
        dialog.doi_edit.setText("10.1000/b")
        self.assertFalse(dialog.copy_button.isEnabled())
        dialog.reject()

    def test_successful_query_saves_verified_reference_and_failure_preserves_clipboard(self):
        repository = Mock()
        self.app.clipboard().setText("Keep me")
        with patch.object(CitationJob, "execute", return_value=self.result):
            dialog = CitationDialog(self.state, self.profile["id"], self.paper, repository)
            dialog.show()
            self.wait_until(lambda: dialog.copy_button.isEnabled())
            self.wait_until(lambda: not dialog.worker.isRunning())
            self.assertEqual(self.paper["citations"]["apa"], self.result.text)
            repository.save.assert_called_once_with(self.state)
            self.assertEqual(self.app.clipboard().text(), "Keep me")
            dialog.reject()
        with patch.object(CitationJob, "execute", side_effect=ValueError("Unmatched paper")):
            dialog = CitationDialog(
                self.state, self.profile["id"], {**self.paper, "citations": {}}, Mock()
            )
            dialog.show()
            self.wait_until(lambda: "Unmatched paper" in dialog.status.text())
            self.assertFalse(dialog.copy_button.isEnabled())
            self.assertEqual(self.app.clipboard().text(), "Keep me")
            dialog.reject()

    def test_close_waits_for_cancelled_worker_without_saving(self):
        release = threading.Event()

        def execute(job, cancelled=None):
            release.wait(2)
            return self.result

        repository = Mock()
        with patch.object(CitationJob, "execute", autospec=True, side_effect=execute):
            dialog = CitationDialog(self.state, self.profile["id"], self.paper, repository)
            dialog.show()
            self.wait_until(lambda: dialog.worker is not None and dialog.worker.isRunning())
            dialog.reject()
            self.assertTrue(dialog.isVisible())
            release.set()
            self.wait_until(lambda: not dialog.isVisible())
            self.assertNotIn("citations", self.paper)
            repository.save.assert_not_called()
