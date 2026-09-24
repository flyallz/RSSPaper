import io
import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import radar_core as core
from secret_store import load_api_key, save_api_key


class CoreTests(unittest.TestCase):
    def test_profiles_and_persistence(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            state = core.default_state()
            state["profiles"].append(core.new_profile("医学"))
            state["active_profile_id"] = state["profiles"][1]["id"]
            state["settings"]["refresh_minutes"] = 0
            core.save_state(state, folder)
            loaded = core.load_state(folder)
            self.assertEqual(core.current_profile(loaded)["name"], "医学")
            self.assertEqual(loaded["settings"]["refresh_minutes"], 0)

    def test_rss_atom_and_crossref(self):
        source = core.create_source("示例", "rss", "https://example.org/feed")
        rss = "<rss><channel><item><title>人工智能 &amp; 教育</title><link>https://example.org/a</link><pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>".encode()
        self.assertEqual(core.parse_rss(rss, source)[0]["date"], "2026-09-21")
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Open science</title><link rel="alternate" href="/paper"/><updated>2026-09-22T09:00:00Z</updated></entry></feed>'
        self.assertEqual(core.parse_rss(atom, source)[0]["url"], "https://example.org/paper")
        journal = core.create_source("Nature", "crossref", "0028-0836")
        record = {"message": {"items": [{"title": ["Discovery"], "DOI": "10.1000/example", "published": {"date-parts": [[2026, 9, 20]]}}]}}
        self.assertEqual(core.parse_crossref(json.dumps(record).encode(), journal)[0]["date"], "2026-09-20")

    def test_sciencedirect_description_dates_keep_their_precision(self):
        source = core.create_source("Computers & Education", "rss", "https://rss.sciencedirect.com/publication/science/03601315")
        rss = '''<rss><channel>
          <item><title>Future issue</title><link>https://example.org/future</link>
            <description>&lt;p&gt;Publication date: January 2027&lt;/p&gt;&lt;p&gt;Source: Computers &amp; Education&lt;/p&gt;</description>
          </item>
          <item><title>Online paper</title><link>https://example.org/online</link>
            <description>&lt;p&gt;Publication date: Available online 28 August 2026&lt;/p&gt;</description>
          </item>
          <item><title>No date</title><link>https://example.org/unknown</link></item>
        </channel></rss>'''
        future, online, unknown = core.parse_rss(rss.encode(), source)
        self.assertEqual((future["date"], future["date_precision"]), ("2027-01", "month"))
        self.assertEqual(core.paper_date_label(future), "2027-01（来源仅提供月份）")
        self.assertEqual((online["date"], online["date_precision"]), ("2026-08-28", "day"))
        self.assertEqual(core.paper_date_label(online), "2026-08-28（在线发表）")
        self.assertEqual(core.paper_date_label(unknown), "日期未提供")
        self.assertFalse(core.is_recent_publication(future, 30, date(2026, 9, 22)))
        self.assertTrue(core.is_recent_publication(online, 30, date(2026, 9, 22)))
        self.assertFalse(core.is_recent_publication(unknown, 30, date(2026, 9, 22)))

    def test_partial_dates_from_prism_and_crossref_are_not_fabricated_days(self):
        source = core.create_source("Example", "rss", "https://example.org/feed")
        rss = b'<rss xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"><channel><item><title>Paper</title><link>https://example.org/paper</link><prism:coverDate>2027-01</prism:coverDate></item></channel></rss>'
        self.assertEqual(core.parse_rss(rss, source)[0]["date"], "2027-01")
        journal = core.create_source("Nature", "crossref", "0028-0836")
        record = {"message": {"items": [{"title": ["Paper"], "URL": "https://doi.org/10.1000/example", "published": {"date-parts": [[2027, 1]]}}]}}
        paper = core.parse_crossref(json.dumps(record).encode(), journal)[0]
        self.assertEqual((paper["date"], paper["date_precision"]), ("2027-01", "month"))

    def test_issn_and_opml(self):
        self.assertEqual(core.normalize_issn("00280836"), "0028-0836")
        with self.assertRaises(ValueError):
            core.normalize_issn("0028-0837")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "feeds.opml"
            sources = [core.create_source("Nature RSS", "rss", "https://example.org/rss")]
            core.export_opml(path, sources)
            imported = core.import_opml(path)
            self.assertEqual(len(imported), 1)
            self.assertEqual(imported[0]["value"], sources[0]["value"])

    def test_arxiv_topic_and_second_layer_keywords(self):
        source = core.create_source(
            "AR learning",
            "arxiv",
            "cs.HC",
            "augmented reality, mixed reality",
            "survey",
        )
        self.assertEqual(source["value"], "cat:cs.HC")
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><title>Augmented reality for collaborative learning</title><id>https://arxiv.org/abs/2609.1</id><link rel="alternate" href="https://arxiv.org/abs/2609.1"/><updated>2026-09-23T00:00:00Z</updated><summary>A classroom experiment.</summary></entry>
          <entry><title>A survey of augmented reality</title><id>https://arxiv.org/abs/2609.2</id><link rel="alternate" href="https://arxiv.org/abs/2609.2"/><updated>2026-09-22T00:00:00Z</updated><summary>Review paper.</summary></entry>
          <entry><title>Database optimization</title><id>https://arxiv.org/abs/2609.3</id><link rel="alternate" href="https://arxiv.org/abs/2609.3"/><updated>2026-09-21T00:00:00Z</updated><summary>Storage engines.</summary></entry>
        </feed>'''
        with patch.object(core, "_read", return_value=atom) as mocked:
            papers = core.fetch_source(source)
        self.assertEqual([paper["title"] for paper in papers], ["Augmented reality for collaborative learning"])
        self.assertIn("search_query=cat%3Acs.HC", mocked.call_args.args[0])

    def test_https_opener_uses_verified_certifi_context(self):
        opener = core._opener("")
        https_handlers = [handler for handler in opener.handlers if handler.__class__.__name__ == "HTTPSHandler"]
        self.assertEqual(len(https_handlers), 1)
        self.assertEqual(https_handlers[0]._context.verify_mode, 2)

    def test_translation_uses_utf8_and_click_request_parameters(self):
        response = {"choices": [{"message": {"content": "跨学科学习"}}]}
        captured = {}

        class FakeOpener:
            def open(self, request, timeout):
                captured["body"] = json.loads(request.data.decode("utf-8"))
                captured["timeout"] = timeout
                return io.BytesIO(json.dumps(response, ensure_ascii=False).encode("utf-8"))

        with patch.object(core, "_opener", return_value=FakeOpener()):
            result = core.translate_title("Learning", "https://api.deepseek.com/chat/completions", "deepseek-flash", "test-only")
        self.assertEqual(result, "跨学科学习")
        self.assertEqual(captured["body"]["thinking"], {"type": "disabled"})
        self.assertEqual(captured["body"]["max_tokens"], 256)

    def test_bidirectional_title_translation(self):
        self.assertTrue(core.contains_cjk("人工智能教育"))
        self.assertFalse(core.contains_cjk("Artificial intelligence in education"))
        response = {"choices": [{"message": {"content": "AI-enabled learning"}}]}
        captured = {}

        class FakeOpener:
            def open(self, request, timeout):
                captured["body"] = json.loads(request.data.decode("utf-8"))
                return io.BytesIO(json.dumps(response).encode("utf-8"))

        with patch.object(core, "_opener", return_value=FakeOpener()):
            result = core.translate_title("人工智能教育", "https://api.deepseek.com/chat/completions", "deepseek-flash", "test-only", target_language="en")
        self.assertEqual(result, "AI-enabled learning")
        self.assertIn("翻译为英文", captured["body"]["messages"][0]["content"])
        self.assertNotEqual(
            core.translation_key("endpoint", "model", "title", "zh"),
            core.translation_key("endpoint", "model", "title", "en"),
        )

    def test_keychain_key_roundtrip_without_writing_to_disk(self):
        stored = {"value": ""}

        def fake_security(command, *args):
            if command == "find-generic-password":
                if stored["value"]:
                    return subprocess.CompletedProcess([], 0, stored["value"] + "\n", "")
                return subprocess.CompletedProcess([], 44, "", "not found")
            if command == "add-generic-password":
                stored["value"] = args[-1]
                return subprocess.CompletedProcess([], 0, "", "")
            if command == "delete-generic-password":
                stored["value"] = ""
                return subprocess.CompletedProcess([], 0, "", "")
            raise AssertionError(command)

        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "key.bin"
            with patch("secret_store._run_security", side_effect=fake_security):
                self.assertEqual(load_api_key(path), "")
                save_api_key(path, "sk-test-local-only")
                self.assertEqual(load_api_key(path), "sk-test-local-only")
                save_api_key(path, "")
                self.assertEqual(load_api_key(path), "")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
