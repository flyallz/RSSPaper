"""Behavioral regressions for the shared business layer."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from journal_radar.domain.papers import make_paper
from journal_radar.domain.sources import create_source
from journal_radar.domain.state import default_state, new_profile, validate_state
from journal_radar.services import TranslationJob, apply_refresh, refresh_sources, select_papers
from journal_radar.services.workspaces import WorkspaceService
from journal_radar.storage import StateRepository, load_state, save_state


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.state = default_state()
        self.profile = self.state["profiles"][0]
        self.good = create_source("Good", "rss", "https://example.org/good")
        self.failed = create_source("Unavailable", "rss", "https://example.org/bad")
        self.profile["sources"] = [self.good, self.failed]

    def test_refresh_keeps_failed_cache_and_clears_successfully_empty_source(self):
        old_good = make_paper(self.good, "old", "https://example.org/old", "")
        old_failed = make_paper(self.failed, "keep", "https://example.org/keep", "")
        self.state["papers"][self.profile["id"]] = [old_good, old_failed]
        apply_refresh(self.state, self.profile["id"], {self.good["id"]: []}, {})
        self.assertEqual(self.state["papers"][self.profile["id"]], [old_failed])

    def test_refresh_isolation_and_removed_profile(self):
        other = new_profile("Another discipline")
        self.state["profiles"].append(other)
        self.state["active_profile_id"] = other["id"]
        paper = make_paper(self.good, "new", "https://example.org/new", "")
        apply_refresh(self.state, self.profile["id"], {self.good["id"]: [paper]}, {})
        self.assertNotIn(other["id"], self.state["papers"])
        self.state["profiles"].remove(self.profile)
        self.assertFalse(apply_refresh(self.state, self.profile["id"], {}, {}))

    def test_refresh_reports_one_source_failure_without_losing_other_results(self):
        paper = make_paper(self.good, "new", "https://example.org/new", "")

        def fetch(source, proxy):
            if source["id"] == self.failed["id"]:
                raise ValueError("temporarily unavailable")
            return [paper]

        progress = []
        with patch("journal_radar.services.refresh.fetch_source", side_effect=fetch):
            papers, statuses = refresh_sources(self.profile["sources"], progress=progress.append)
        self.assertEqual(papers[self.good["id"]], [paper])
        self.assertFalse(statuses[self.failed["id"]]["ok"])
        self.assertEqual(len(progress), 2)

    def test_translation_snapshot_preserves_model_cache_and_legacy_key_format(self):
        from journal_radar.adapters.translation import translation_key

        settings = self.state["settings"]
        job = TranslationJob.from_settings("Learning", settings)
        settings["api_model"] = "different-model"
        self.assertNotEqual(
            job.cache_key, TranslationJob.from_settings("Learning", settings).cache_key
        )
        abstract = TranslationJob.from_settings("教育研究", settings, "abstract")
        self.assertEqual(abstract.target_language, "en")
        self.assertEqual(
            abstract.cache_key, translation_key("", "different-model", "摘要：教育研究", "en")
        )
        self.assertNotEqual(
            abstract.cache_key, TranslationJob.from_settings("教育研究", settings).cache_key
        )

    def test_legacy_state_migration_retains_ids_translations_and_unknown_fields(self):
        legacy = deepcopy(self.state)
        legacy["extra_metadata"] = {"preserve": True}
        legacy["translations"]["existing-cache"] = "已有译文"
        for source in legacy["profiles"][0]["sources"]:
            del source["include_keywords"], source["exclude_keywords"], source["match_all"]
        original = deepcopy(legacy)
        migrated = validate_state(legacy)
        self.assertEqual(legacy, original)
        self.assertEqual(migrated["profiles"][0]["id"], self.profile["id"])
        self.assertEqual(migrated["translations"], legacy["translations"])
        self.assertTrue(migrated["extra_metadata"]["preserve"])
        with tempfile.TemporaryDirectory() as folder:
            save_state(migrated, Path(folder))
            self.assertEqual(load_state(Path(folder)), migrated)

    def test_invalid_nested_state_is_rejected(self):
        for field, value in (("settings", []), ("profiles", "wrong"), ("papers", [])):
            broken = deepcopy(self.state)
            broken[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_state(broken)

    def test_failed_edit_does_not_change_memory_or_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = StateRepository(Path(folder))
            repo.save(self.state)
            before = deepcopy(self.state)
            service = WorkspaceService(self.state, repo)
            with patch.object(repo, "save", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    service.add_profile("Medicine")
            self.assertEqual(self.state, before)
            self.assertEqual(repo.load(), before)

    def test_invalid_file_cannot_be_overwritten_by_empty_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            path.write_text("{broken", encoding="utf-8")
            repo = StateRepository(Path(folder))
            with self.assertRaises(json.JSONDecodeError):
                repo.load()
            with self.assertRaises(ValueError):
                repo.save(default_state())
            self.assertEqual(path.read_text(), "{broken")

    def test_atomic_save_failure_preserves_previous_file_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = StateRepository(Path(folder))
            repo.save(self.state)
            with patch("journal_radar.storage.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    repo.save(default_state())
            self.assertEqual(repo.load(), self.state)
            self.assertEqual([path.name for path in Path(folder).iterdir()], ["state.json"])

    def test_import_deduplicates_and_delete_removes_only_its_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            service = WorkspaceService(self.state, StateRepository(Path(folder)))
            new = create_source("Other", "rss", "https://example.org/other")
            self.assertEqual(service.import_sources([self.good, new, new]), 1)
            keep = make_paper(self.failed, "Keep", "https://example.org/keep", "")
            remove = make_paper(self.good, "Remove", "https://example.org/remove", "")
            self.state["papers"][self.profile["id"]] = [keep, remove]
            service.delete_source(0)
            self.assertEqual(self.state["papers"][self.profile["id"]], [keep])
            self.assertEqual(select_papers([keep], "keep", self.failed["id"]), [keep])

    def test_settings_failure_restores_key_and_leaves_settings_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = StateRepository(Path(folder))
            service = WorkspaceService(self.state, repo)
            before = deepcopy(self.state)
            changed = {**self.state["settings"], "api_model": "new-model"}
            with (
                patch("journal_radar.services.workspaces.load_api_key", return_value="old-key"),
                patch("journal_radar.services.workspaces.save_api_key") as save_key,
                patch.object(repo, "save", side_effect=OSError("disk full")),
            ):
                with self.assertRaises(OSError):
                    service.save_settings(changed, "new-key")
            self.assertEqual(
                [call.args[1] for call in save_key.call_args_list], ["new-key", "old-key"]
            )
            self.assertEqual(self.state, before)
