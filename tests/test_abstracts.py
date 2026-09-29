"""Abstract lookup regressions: identity, provenance, failures and cache isolation."""

import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from journal_radar.adapters.abstracts import AbstractResult, fetch_abstract
from journal_radar.adapters.rss import parse_rss
from journal_radar.domain.papers import make_paper, paper_abstract_kind
from journal_radar.domain.sources import create_source
from journal_radar.domain.state import default_state, new_profile, validate_state
from journal_radar.services.abstracts import AbstractJob, apply_abstract
from journal_radar.services.refresh import apply_refresh


def response(message):
    return json.dumps({"message": message}).encode()


class AbstractLookupTests(unittest.TestCase):
    def test_doi_lookup_preserves_paragraphs_and_encodes_identifier(self):
        message = {
            "DOI": "10.1000/a&b",
            "abstract": "<jats:abstract><jats:title>Abstract</jats:title><jats:p>First &amp; second.</jats:p><jats:p>Results follow.</jats:p></jats:abstract>",
        }
        with patch(
            "journal_radar.adapters.abstracts.read_bytes", return_value=response(message)
        ) as read:
            result = fetch_abstract(
                "https://doi.org/10.1000/A%26B", "Paper", "http://localhost:1234"
            )
        self.assertEqual(result.text, "First & second.\n\nResults follow.")
        self.assertEqual(result.doi, "10.1000/a&b")
        self.assertEqual(
            read.call_args.args,
            ("https://api.crossref.org/works/10.1000%2Fa%26b", "http://localhost:1234"),
        )

    def test_search_uses_unique_exact_title_not_first_result(self):
        search = {
            "items": [
                {"DOI": "10.1000/wrong", "title": ["Another study"]},
                {"DOI": "10.1000/right", "title": ["Learning &amp; AI: A Study"]},
            ]
        }
        work = {"DOI": "10.1000/right", "abstract": "<p>Complete source abstract.</p>"}
        with patch(
            "journal_radar.adapters.abstracts.read_bytes",
            side_effect=[response(search), response(work)],
        ) as read:
            result = fetch_abstract("", "Learning & AI — A Study")
        self.assertEqual(result.doi, "10.1000/right")
        self.assertEqual(read.call_count, 2)

    def test_ambiguous_and_similar_titles_are_not_accepted(self):
        for items in (
            [{"DOI": "10.1000/a", "title": ["Learning in classrooms"]}],
            [
                {"DOI": "10.1000/a", "title": ["Learning"]},
                {"DOI": "10.1000/b", "title": ["Learning"]},
            ],
            [],
        ):
            with (
                self.subTest(items=items),
                patch(
                    "journal_radar.adapters.abstracts.read_bytes",
                    return_value=response({"items": items}),
                ) as read,
            ):
                with self.assertRaisesRegex(ValueError, "没有唯一"):
                    fetch_abstract("", "Learning")
                self.assertEqual(read.call_count, 1)

    def test_absent_partial_or_metadata_abstract_is_not_reported_as_full(self):
        for value in (None, "", "A truncated abstract...", "Publication date: January 2027"):
            work = {"DOI": "10.1000/a", "abstract": value}
            with (
                self.subTest(value=value),
                patch("journal_radar.adapters.abstracts.read_bytes", return_value=response(work)),
            ):
                with self.assertRaises(ValueError):
                    fetch_abstract("10.1000/a", "Paper")

    def test_mismatched_doi_and_invalid_response_are_rejected(self):
        for payload in (response({"DOI": "10.1000/wrong", "abstract": "Text"}), b"{}", b"[]"):
            with (
                self.subTest(payload=payload),
                patch("journal_radar.adapters.abstracts.read_bytes", return_value=payload),
            ):
                with self.assertRaises(ValueError):
                    fetch_abstract("10.1000/a", "Paper")


class AbstractCacheTests(unittest.TestCase):
    def setUp(self):
        self.state = default_state()
        self.profile = self.state["profiles"][0]
        self.source = create_source("Example", "rss", "https://example.org/feed")
        self.profile["sources"] = [self.source]
        self.paper = make_paper(
            self.source, "Learning", "https://example.org/p", "", abstract="Short teaser…"
        )
        self.state["papers"][self.profile["id"]] = [self.paper]
        self.job = AbstractJob.for_paper(self.profile["id"], self.paper)
        self.result = AbstractResult("A complete abstract from the publisher.", "10.1000/a")

    def test_switching_profiles_does_not_misroute_completion(self):
        other = new_profile("Other")
        self.state["profiles"].append(other)
        self.state["active_profile_id"] = other["id"]
        self.assertTrue(apply_abstract(self.state, self.job, self.result))
        self.assertNotIn(other["id"], self.state["papers"])
        self.assertEqual(paper_abstract_kind(self.paper), "full")
        self.assertEqual(self.paper["abstract_source"], "Crossref")
        self.assertEqual(validate_state(self.state), self.state)

    def test_removed_profile_source_and_changed_paper_ignore_completion(self):
        for change in ("profile", "source", "title"):
            state = deepcopy(self.state)
            if change == "profile":
                state["profiles"] = []
            elif change == "source":
                state["profiles"][0]["sources"] = []
            else:
                state["papers"][self.profile["id"]][0]["title"] = "Changed title"
            with self.subTest(change=change):
                self.assertFalse(apply_abstract(state, self.job, self.result))

    def test_failure_preserves_teaser_and_allows_successful_retry(self):
        apply_abstract(self.state, self.job, error="Source did not provide an abstract")
        self.assertEqual(self.paper["abstract"], "Short teaser…")
        self.assertTrue(self.paper["abstract_error"])
        apply_abstract(self.state, self.job, self.result)
        self.assertEqual(self.paper["abstract_error"], "")

    def test_successful_refresh_preserves_enrichment_but_not_changed_identity(self):
        apply_abstract(self.state, self.job, self.result)
        fresh = make_paper(
            self.source, "Learning", "https://example.org/p", "2026-09-29", abstract="Short teaser…"
        )
        apply_refresh(self.state, self.profile["id"], {self.source["id"]: [fresh]}, {})
        cached = self.state["papers"][self.profile["id"]][0]
        self.assertEqual(cached["abstract"], self.result.text)
        self.assertEqual(cached["date"], "2026-09-29")
        fresh["title"] = "Replaced article"
        apply_refresh(self.state, self.profile["id"], {self.source["id"]: [fresh]}, {})
        self.assertEqual(self.state["papers"][self.profile["id"]][0]["abstract"], "Short teaser…")

    def test_old_full_rss_flag_is_not_proof_of_completeness(self):
        self.paper.update(abstract="A source description without ellipsis", abstract_kind="full")
        self.assertEqual(paper_abstract_kind(self.paper), "available")

    def test_rss_content_and_doi_are_not_lost_to_short_description(self):
        payload = b'<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"><channel><item><title>Paper</title><link>https://example.org/p</link><description>Publication date: January 2027</description><content:encoded><![CDATA[<p>An abstract from the source.</p>]]></content:encoded><prism:doi>10.1000/PAPER</prism:doi></item></channel></rss>'
        paper = parse_rss(payload, self.source)[0]
        self.assertEqual(paper["abstract"], "An abstract from the source.")
        self.assertEqual(paper["doi"], "10.1000/paper")
        self.assertEqual(paper["date"], "2027-01")
        self.assertEqual(paper_abstract_kind(paper), "available")
