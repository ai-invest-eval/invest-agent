"""API·비용 없이 원본 수집과 보존을 확인한다."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from collect_candidates import (
    build_queries,
    collect_searches,
    redact_secrets,
    save_collection,
)
from src.agents.agent1_sources import build_search_requests
from src.tools.web_search import WebSearchError


class CollectionTests(unittest.TestCase):
    def test_default_queries(self):
        queries = build_queries("AI 신약개발")
        self.assertEqual(len(queries), 6)
        self.assertEqual(len(set(queries)), 6)
        with self.assertRaises(ValueError):
            build_queries(" ")

    def test_source_plan_and_domains(self):
        requests = build_search_requests("국내 키워드", "custom biotech topic")
        self.assertEqual(
            [r.source_key for r in requests],
            ["startup_recipe"] * 3 + ["cure", "yc", "yc"],
        )
        self.assertTrue(all("국내 키워드" in r.query for r in requests[:3]))
        self.assertTrue(all("custom biotech topic" in r.query for r in requests[3:]))
        self.assertEqual(requests[0].include_domains, ("startuprecipe.co.kr",))
        self.assertEqual(requests[3].include_domains, ("wewillcure.com",))
        self.assertEqual(requests[4].include_domains, ("ycombinator.com",))
        with self.assertRaises(ValueError):
            build_search_requests("국내", " ")

    def test_source_metadata_and_filter_are_preserved(self):
        search = Mock()
        search.search.return_value = {"results": []}
        request = build_search_requests("AI 신약개발")[3]
        result = collect_searches(search, [request])
        search.search.assert_called_once_with(
            request.query,
            max_results=10,
            search_depth="advanced",
            include_domains=("wewillcure.com",),
        )
        record = result["searches"][0]
        self.assertEqual(record["source_key"], "cure")
        self.assertEqual(record["source_scope"], "global_source")
        self.assertEqual(record["source_url"], request.source_url)

    def test_custom_query_remains_unrestricted(self):
        search = Mock()
        search.search.return_value = {"results": []}
        result = collect_searches(search, ["custom query"])
        self.assertIsNone(search.search.call_args.kwargs["include_domains"])
        self.assertEqual(result["searches"][0]["source_key"], "custom")

    def test_partial_failure_preserves_success(self):
        search = Mock()
        response = {"results": [{"title": "원본", "raw_content": "본문"}]}
        search.search.side_effect = [WebSearchError("검색 실패"), response]
        result = collect_searches(search, ["first", "second"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["successful_queries"], 1)
        self.assertEqual(result["failed_queries"], 1)
        self.assertEqual(result["result_count"], 1)
        self.assertEqual(result["searches"][1]["response"], response)

    def test_empty_results_and_all_failure_are_distinct(self):
        search = Mock()
        search.search.return_value = {"results": []}
        result = collect_searches(search, ["query"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result_count"], 0)
        search.search.side_effect = WebSearchError("검색 실패")
        result = collect_searches(search, ["query"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["failed_queries"], 1)

    def test_empty_query_list_is_rejected(self):
        search = Mock()
        for queries in [[], [" "]]:
            with self.assertRaises(ValueError):
                collect_searches(search, queries)
        search.search.assert_not_called()

    def test_redaction_and_unique_files(self):
        raw = {"api_key": "secret", "results": [{"content": "key secret"}]}
        safe = redact_secrets(raw, ["secret", ""])
        self.assertEqual(safe["api_key"], "[REDACTED]")
        self.assertEqual(safe["results"][0]["content"], "key [REDACTED]")
        self.assertEqual(raw["api_key"], "secret")
        with tempfile.TemporaryDirectory() as directory:
            first = save_collection(safe, Path(directory))
            second = save_collection(safe, Path(directory))
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text()), safe)


if __name__ == "__main__":
    unittest.main()
