"""Rank schema, credential privacy, venue identity and cache regressions."""

import json
import os
import tempfile
import time
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from journal_radar.adapters.ranks import _NoRedirect, fetch_ranks, parse_ranks
from journal_radar.adapters.rss import parse_rss
from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.domain.state import default_state, validate_state
from journal_radar.platform import macos_keychain
from journal_radar.services.ranks import apply_rank, cached_rank, paper_rank_text, store_rank
from journal_radar.services.refresh import apply_refresh
from journal_radar.services.workspaces import WorkspaceService
from journal_radar.storage import StateRepository
from journal_radar.ui.rank_dialog import RankDialog
from journal_radar.ui.settings_dialog import SettingsDialog


def payload(values=None, custom=None):
    return json.dumps(
        {
            "code": 200,
            "data": {
                "officialRank": {"all": values or {}, "select": {"sci": "wrong"}},
                "customRank": custom or {},
            },
        }
    ).encode()


def record(name="Computers & Education"):
    result = parse_ranks(payload({"sci": "Q1", "ccf": "A"}), name)
    result["retrieved_at"] = datetime.now(UTC).isoformat()
    return result


class RankTests(unittest.TestCase):
    def test_standard_and_custom_labels_preserve_unknown_year(self):
        result = parse_ranks(
            payload(
                {"sci": "Q1", "sciUp": "教育学1区", "pku": "北大中文核心"},
                {
                    "rankInfo": [{"uuid": "u", "abbName": "School", "twoRankText": "B"}],
                    "rank": ["u&&&2", "missing&&&1", "u&&&9"],
                },
            ),
            "Journal",
        )
        self.assertEqual(
            [label["value"] for label in result["labels"]], ["Q1", "教育学1区", "北大中文核心", "B"]
        )
        self.assertTrue(all(label["year"] == "" for label in result["labels"]))
        self.assertNotIn("wrong", str(result))

    def test_invalid_or_denied_response_is_not_empty_success(self):
        for data in (
            [1],
            {"code": 200, "data": None},
            {"code": 200, "data": {"officialRank": {"all": []}}},
            {"code": 40002, "msg": "secret-example-key"},
        ):
            with self.subTest(data=data), self.assertRaises(Exception) as caught:
                parse_ranks(json.dumps(data).encode(), "Journal")
            self.assertNotIn("secret-example-key", str(caught.exception))
        self.assertEqual(parse_ranks(payload(), "Journal")["labels"], [])

    def test_http_error_cannot_expose_key_and_redirects_are_rejected(self):
        opener = Mock()
        opener.open.side_effect = RuntimeError("https://service/?secretKey=secret-example-key")
        with patch("journal_radar.adapters.ranks.build_http_opener", return_value=opener):
            with self.assertRaises(RuntimeError) as caught:
                fetch_ranks("Journal", "secret-example-key")
            self.assertNotIn("secret-example-key", str(caught.exception))
        with self.assertRaises(ValueError):
            _NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")

    def test_serialized_request_spacing_and_pre_cancel(self):
        starts = []
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = payload({"sci": "Q1"})
        opener = Mock()

        def opened(*args, **kwargs):
            starts.append(time.monotonic())
            return response

        opener.open.side_effect = opened
        with (
            patch("journal_radar.adapters.ranks.build_http_opener", return_value=opener),
            patch("journal_radar.adapters.ranks._LAST_START", 0),
        ):
            fetch_ranks("One", "fake-key")
            fetch_ranks("Two", "fake-key")
            self.assertGreaterEqual(starts[1] - starts[0], 0.64)
            with self.assertRaisesRegex(ValueError, "取消"):
                fetch_ranks("Three", "fake-key", cancelled=lambda: True)
            self.assertEqual(len(starts), 2)

    def test_cache_is_by_venue_not_alias_and_expiry_is_distinct_from_absence(self):
        state = default_state()
        state["settings"]["rank_enabled"] = True
        item = record()
        store_rank(state, item)
        paper = {"source_name": "CE", "publication_name": "Computers & Education"}
        self.assertIn("Q1", paper_rank_text(paper, state)[0])
        self.assertIn("接口未提供", paper_rank_text(paper, state)[1])
        self.assertEqual(paper_rank_text({"source_name": "CE"}, state), ("", ""))
        item["retrieved_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        self.assertIsNone(cached_rank(state, item["name"], fresh_only=True))
        self.assertIsNotNone(cached_rank(state, item["name"]))
        state["settings"]["rank_enabled"] = False
        self.assertEqual(paper_rank_text(paper, state), ("", ""))

    def test_formal_name_refresh_is_retained_and_source_change_overrides_it(self):
        state = default_state()
        profile = state["profiles"][0]
        source = create_source("AI", "rss", "https://example.org/rss")
        profile["sources"] = [source]
        old = make_paper(source, "Paper", "https://example.org/1", "")
        old["publication_name"] = "Confirmed Venue"
        state["papers"][profile["id"]] = [old]
        fresh = make_paper(source, old["title"], old["url"], "")
        apply_refresh(state, profile["id"], {source["id"]: [fresh]}, {})
        self.assertEqual(state["papers"][profile["id"]][0]["publication_name"], "Confirmed Venue")
        fresh["publication_name"] = "Other Venue"
        apply_refresh(state, profile["id"], {source["id"]: [fresh]}, {})
        self.assertEqual(state["papers"][profile["id"]][0]["publication_name"], "Other Venue")

    def test_feed_formal_title_is_distinct_from_alias_and_arxiv_category(self):
        xml = b"<rss><channel><title>ScienceDirect Publication: Computers &amp; Education</title><item><title>Paper</title><link>https://example.org/1</link></item></channel></rss>"
        source = create_source(
            "CE", "rss", "https://rss.sciencedirect.com/publication/science/03601315"
        )
        self.assertEqual(parse_rss(xml, source)[0]["publication_name"], "Computers & Education")
        source["value"] = "https://rss.arxiv.org/rss/cs.AI"
        self.assertEqual(parse_rss(xml, source)[0]["publication_name"], "")

    def test_keychain_namespaces_preserve_translation_account(self):
        backend = Mock()
        with patch(
            "journal_radar.platform.macos_keychain._keychain", return_value=backend
        ) as factory:
            macos_keychain.load_api_key(Path("api-key.bin"))
            self.assertEqual(factory.call_args.args, ("translation-api-key",))
            macos_keychain.save_api_key(Path("easyscholar-key.bin"), "fake-key")
            self.assertEqual(factory.call_args.args, ("easyscholar-key",))
            macos_keychain.load_api_key(Path("api-key.bin"))
            self.assertEqual(factory.call_args.args, ("translation-api-key",))

    def test_failed_settings_save_rolls_back_both_separate_keys(self):
        state = default_state()
        before = deepcopy(state)
        with tempfile.TemporaryDirectory() as folder:
            repo = StateRepository(Path(folder))
            service = WorkspaceService(state, repo)
            with (
                patch(
                    "journal_radar.services.workspaces.load_api_key",
                    side_effect=["old-translation", "old-rank"],
                ),
                patch("journal_radar.services.workspaces.save_api_key") as saved,
                patch.object(repo, "save", side_effect=OSError("disk full")),
            ):
                with self.assertRaises(OSError):
                    service.save_settings(
                        {**state["settings"], "rank_enabled": True}, "new-translation", "new-rank"
                    )
                self.assertEqual(
                    [(call.args[0].name, call.args[1]) for call in saved.call_args_list],
                    [
                        ("api-key.bin", "new-translation"),
                        ("easyscholar-key.bin", "new-rank"),
                        ("api-key.bin", "old-translation"),
                        ("easyscholar-key.bin", "old-rank"),
                    ],
                )
            self.assertEqual(state, before)

    def test_removed_or_changed_paper_does_not_gain_a_venue_from_late_result(self):
        state = default_state()
        profile = state["profiles"][0]
        source = create_source("Alias", "rss", "https://example.org/feed")
        profile["sources"] = [source]
        paper = make_paper(source, "Paper", "https://example.org/1", "")
        state["papers"][profile["id"]] = [paper]
        snapshot = deepcopy(paper)
        paper["title"] = "Changed"
        self.assertFalse(apply_rank(state, profile["id"], snapshot, record()))
        paper["title"] = snapshot["title"]
        profile["sources"].clear()
        self.assertFalse(apply_rank(state, profile["id"], snapshot, record()))
        self.assertEqual(state["publication_ranks"], {})

    def test_changing_rank_key_invalidates_account_specific_cache(self):
        state = default_state()
        store_rank(state, record())
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("journal_radar.services.workspaces.load_api_key", return_value="old"),
            patch("journal_radar.services.workspaces.save_api_key"),
        ):
            service = WorkspaceService(state, StateRepository(Path(folder)))
            service.save_settings(state["settings"], rank_credential="new-fake-key")
            self.assertEqual(state["publication_ranks"], {})

    def test_invalid_cached_labels_are_rejected(self):
        state = default_state()
        state["publication_ranks"] = {
            "journal": {"name": "Journal", "retrieved_at": "now", "labels": [{"value": "Q1"}]}
        }
        with self.assertRaises(ValueError):
            validate_state(state)


class RankUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_fields_and_key_never_enter_json(self):
        state = default_state()
        repository = Mock(folder=Path("/tmp"))
        dialog = SettingsDialog(state, repository=repository)
        dialog.rank_key.setText("fake-rank-key")
        dialog.rank_enabled.setChecked(True)
        with patch.object(dialog.workspaces, "save_settings") as save:
            dialog.save()
            args = save.call_args.args
            self.assertNotIn("fake-rank-key", json.dumps(args[0]))
            self.assertEqual(args[2], "fake-rank-key")
            self.assertTrue(args[0]["rank_enabled"])
        dialog.reject()

    def test_rank_dialog_does_not_guess_or_call_api_without_explicit_query(self):
        state = default_state()
        source = create_source("AI", "rss", "https://rss.arxiv.org/rss/cs.AI")
        paper = make_paper(source, "Paper", "https://arxiv.org/abs/2202.01037", "")
        dialog = RankDialog(state, state["profiles"][0]["id"], paper, Mock(folder=Path("/tmp")))
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.name_edit.text(), "")
        self.assertIsNone(dialog.worker)
        dialog.query_button.click()
        self.assertIn("请填写", dialog.status.text())
        self.assertIsNone(dialog.worker)
        dialog.reject()
