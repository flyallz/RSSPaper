"""Publisher abstract identity, fragment, browser import and fallback behavior."""

import unittest
from unittest.mock import patch

from journal_radar.adapters.abstract_enrichment import fetch_complete_abstract
from journal_radar.adapters.abstracts import AbstractResult
from journal_radar.adapters.publisher_pages import (
    _PublisherRedirect,
    parse_publisher_abstract,
    publisher_name,
)

SD = "https://www.sciencedirect.com/science/article/pii/example"
CNKI = "https://kns.cnki.net/kcms2/article/abstract?v=example"


class PublisherPageTests(unittest.TestCase):
    def test_sciencedirect_reads_abstract_paragraphs_not_highlights_or_seo(self):
        html = b'<meta name="citation_title" content="Learning &amp; AI"><meta name="description" content="A teaser..."><div class="abstractHighlights"><p>Highlight only.</p></div><div class="abstract author"><h2>Abstract</h2><div><p>First &amp; second.</p><p>Results follow.</p></div></div>'
        result = parse_publisher_abstract(html, SD, "Learning & AI")
        self.assertEqual(result.text, "First & second.\n\nResults follow.")
        self.assertEqual(result.source, "ScienceDirect 论文页面")

    def test_cnki_legacy_encoding_and_imported_full_container(self):
        html = '<meta charset="gb2312"><h1>教育研究</h1><span id="ChDivSummary">摘要：完整的研究背景。研究方法和结论。<button>收起</button></span>'.encode(
            "gb2312"
        )
        result = parse_publisher_abstract(html, CNKI, "教育研究")
        self.assertEqual(result.text, "完整的研究背景。研究方法和结论。")
        self.assertEqual(result.source, "知网 论文页面")

    def test_title_doi_mismatch_and_verification_page_are_rejected(self):
        for html, title, doi in (
            (b'<h1>Other paper</h1><div class="abstract"><p>Abstract.</p></div>', "Paper", ""),
            (
                b'<h1>Paper</h1><meta name="citation_doi" content="10.1000/other"><div class="abstract"><p>Abstract.</p></div>',
                "Paper",
                "10.1000/right",
            ),
            (b"<title>Verification</title><p>Login needed</p>", "Paper", ""),
        ):
            with self.subTest(title=title), self.assertRaises(ValueError):
                parse_publisher_abstract(html, SD, title, doi)

    def test_fragments_and_only_description_are_not_full_abstracts(self):
        for content in (
            '<div class="abstract"><p>A fragment...</p></div>',
            '<div class="abstract"><p>A fragment...Read more</p></div>',
            '<meta name="description" content="SEO description">',
            '<meta name="citation_abstract" content="A fragment...Read more">',
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_publisher_abstract(("<h1>Paper</h1>" + content).encode(), SD, "Paper")

    def test_unsupported_hosts_and_redirects(self):
        self.assertEqual(publisher_name("https://sciencedirect.com.evil.example/article"), "")
        for url in (
            "http://www.sciencedirect.com/article",
            "https://127.0.0.1/article",
            "https://login.example",
        ):
            with self.assertRaises(ValueError):
                _PublisherRedirect().redirect_request(None, None, 302, "", {}, url)

    def test_provider_failure_falls_back_without_erasing_old_data(self):
        result = AbstractResult("Source abstract.", "10.1000/a")
        with (
            patch(
                "journal_radar.adapters.abstract_enrichment.fetch_publisher_abstract",
                side_effect=ValueError("login"),
            ),
            patch(
                "journal_radar.adapters.abstract_enrichment.fetch_abstract", return_value=result
            ) as crossref,
        ):
            self.assertEqual(fetch_complete_abstract("", "Paper", SD), result)
            crossref.assert_called_once()
        with (
            patch(
                "journal_radar.adapters.abstract_enrichment.fetch_abstract",
                side_effect=ValueError("missing"),
            ),
            patch(
                "journal_radar.adapters.abstract_enrichment.fetch_publisher_abstract",
                return_value=result,
            ),
        ):
            self.assertEqual(
                fetch_complete_abstract("10.1000/a", "Paper", "https://doi.org/10.1000/a"), result
            )

    def test_crossref_wrong_registered_title_is_not_used_as_fallback(self):
        from journal_radar.adapters.abstracts import fetch_abstract

        with patch(
            "journal_radar.adapters.abstracts._message",
            return_value={
                "DOI": "10.1000/a",
                "title": ["Other paper"],
                "abstract": "<p>Wrong paper abstract.</p>",
            },
        ):
            with self.assertRaisesRegex(ValueError, "题名"):
                fetch_abstract("10.1000/a", "Paper")

    def test_cancellation_between_providers_stops_fallback(self):
        cancelled = [False]

        def first(*args):
            cancelled[0] = True
            raise ValueError("first failed")

        with (
            patch(
                "journal_radar.adapters.abstract_enrichment.fetch_publisher_abstract",
                side_effect=first,
            ),
            patch("journal_radar.adapters.abstract_enrichment.fetch_abstract") as second,
        ):
            with self.assertRaisesRegex(ValueError, "取消"):
                fetch_complete_abstract("", "Paper", SD, cancelled=lambda: cancelled[0])
            second.assert_not_called()


class ImportedAbstractTests(unittest.TestCase):
    def parse(self, items, title="Paper", url="https://example.org/1", doi="10.1000/a"):
        import json

        from journal_radar.adapters.imported_abstracts import parse_imported_abstract

        return parse_imported_abstract(json.dumps(items).encode(), title, url, doi)

    def test_csl_and_zotero_records_verify_identity_without_certifying_completeness(self):
        for items in (
            [{"title": "Paper", "DOI": "10.1000/a", "abstract": "Complete source text."}],
            {
                "items": [
                    {
                        "data": {
                            "title": "Paper",
                            "DOI": "10.1000/a",
                            "abstractNote": "Complete source text.",
                        }
                    }
                ]
            },
        ):
            result = self.parse(items)
            self.assertEqual(result.text, "Complete source text.")
            self.assertEqual(result.kind, "available")
            self.assertIn("完整性未确认", result.source)

    def test_wrong_missing_ambiguous_or_fragment_records_are_not_imported(self):
        for items in (
            [
                {
                    "title": "Paper",
                    "DOI": "10.1000/b",
                    "URL": "https://example.org/1",
                    "abstract": "Wrong record.",
                }
            ],
            [{"title": "Other paper", "DOI": "10.1000/a", "abstract": "Wrong title."}],
            [{"title": "Paper", "DOI": "10.1000/a"}],
            [{"title": "Paper", "DOI": "10.1000/a", "abstract": "Partial..."}],
            [
                {"title": "Paper", "DOI": "10.1000/a", "abstract": "One."},
                {"title": "Paper", "DOI": "10.1000/a", "abstract": "Other."},
            ],
        ):
            with self.subTest(items=items), self.assertRaises(ValueError):
                self.parse(items)

    def test_doi_missing_requires_original_url_and_exact_title(self):
        result = self.parse(
            [{"title": "Paper", "url": "https://example.org/1", "abstractNote": "Source text."}],
            doi="",
        )
        self.assertEqual(result.doi, "")
        with self.assertRaises(ValueError):
            self.parse(
                [
                    {
                        "title": "Paper",
                        "url": "https://example.org/wrong",
                        "abstractNote": "Source text.",
                    }
                ],
                doi="",
            )
