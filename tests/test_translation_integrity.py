"""Exercise response completion, lossless chunking and cancellation without API costs."""

import io
import json
import unittest
from unittest.mock import patch

from journal_radar.adapters import translation
from journal_radar.domain.state import default_state
from journal_radar.services.translations import TranslationJob


class TranslationIntegrityTests(unittest.TestCase):
    def request(self, responses, text="An abstract.", cancelled=None):
        captured = []

        class Opener:
            def open(self, request, timeout):
                captured.append(json.loads(request.data))
                item = responses.pop(0)
                if isinstance(item, Exception):
                    raise item
                return io.BytesIO(json.dumps({"choices": [item]}).encode())

        with patch.object(translation, "build_http_opener", return_value=Opener()):
            result = translation.translate_title(
                text,
                "https://example.org/api",
                "model",
                "key",
                content_type="abstract",
                cancelled=cancelled,
            )
        return result, captured

    @staticmethod
    def response(text, reason="stop"):
        return {"message": {"content": text}, "finish_reason": reason}

    def test_truncated_output_retries_with_larger_budget(self):
        text, requests = self.request(
            [self.response("partial", "length"), self.response("complete")]
        )
        self.assertEqual(text, "complete")
        self.assertGreaterEqual(requests[0]["max_tokens"], 2048)
        self.assertEqual(requests[1]["max_tokens"], requests[0]["max_tokens"] * 2)

    def test_repeated_truncation_is_failure_instead_of_partial_success(self):
        with self.assertRaisesRegex(ValueError, "未保存不完整"):
            self.request([self.response("partial", "length")] * 2)

    def test_later_chunk_failure_cannot_return_earlier_partial_translation(self):
        with self.assertRaisesRegex(ValueError, "未保存不完整"):
            self.request(
                [
                    self.response("first"),
                    self.response("second", "length"),
                    self.response("second", "length"),
                ],
                "A" * 2000,
            )

    def test_chunking_retains_all_characters_and_order(self):
        text = ("First sentence. Second sentence!\n\n中文段落。\n" * 150) + "last"
        parts = translation.split_translation_text(text)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(0 < len(part) <= 1500 for part in parts))
        result, requests = self.request([self.response(str(i)) for i in range(len(parts))], text)
        self.assertEqual([r["messages"][1]["content"] for r in requests], parts)
        self.assertEqual(result, "\n\n".join(str(i) for i in range(len(parts))))

    def test_cancel_between_chunks_does_not_send_more_requests(self):
        calls = 0

        def cancelled():
            nonlocal calls
            calls += 1
            return calls >= 4

        with self.assertRaises(translation.TranslationCancelled):
            self.request([self.response("first")], "A" * 2000, cancelled)

    def test_non_completion_and_invalid_content_are_not_success(self):
        for content, reason in (
            ("partial", "content_filter"),
            ("", "stop"),
            (None, "stop"),
            ([{"text": "not a chat completion"}], "stop"),
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.request([self.response(content, reason)])

    def test_english_abstract_with_chinese_author_keeps_chinese_target(self):
        self.assertFalse(translation.contains_cjk("This research investigates learning with 李明."))
        self.assertTrue(translation.contains_cjk("本研究采用 AI 和 LLM 支持学生自主学习。"))
        self.assertTrue(translation.contains_cjk("AI教育"))

    def test_legacy_abstract_cache_is_not_reused_but_title_cache_is(self):
        settings = default_state()["settings"]
        abstract = TranslationJob.from_settings("A long abstract", settings, "abstract")
        old = translation.translation_key(
            settings["api_endpoint"], settings["api_model"], "摘要：A long abstract", "zh"
        )
        self.assertNotEqual(abstract.cache_key, old)
        title = TranslationJob.from_settings("Learning", settings)
        self.assertEqual(
            title.cache_key,
            translation.translation_key(
                settings["api_endpoint"], settings["api_model"], "Learning", "zh"
            ),
        )
