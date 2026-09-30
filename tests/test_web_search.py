"""API 호출 없이 Tavily 검색 경계를 확인한다."""

import unittest
from unittest.mock import Mock

from src.tools.web_search import TavilySearch, WebSearchError


class SearchTests(unittest.TestCase):
    def test_response_and_request_options(self):
        response = {
            "results": [
                {
                    "title": "기업 발표",
                    "url": "https://example.invalid/ir",
                    "content": "검색 발췌",
                    "raw_content": "본문 원본",
                }
            ],
            "request_id": "test-request",
        }
        client = Mock()
        client.search.return_value = response
        search = TavilySearch(client=client, timeout=12)
        self.assertIs(search.search("  키워드  ", max_results=4), response)
        client.search.assert_called_once_with(
            query="키워드",
            topic="general",
            search_depth="advanced",
            max_results=4,
            include_answer=False,
            include_raw_content="text",
            include_images=False,
            auto_parameters=False,
            timeout=12,
        )

    def test_error_does_not_expose_sdk_message(self):
        client = Mock()
        client.search.side_effect = RuntimeError("secret-key and request credentials")
        with self.assertRaises(WebSearchError) as raised:
            TavilySearch(client=client).search("query")
        self.assertNotIn("secret-key", str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)

    def test_domain_filter_is_restrict_and_normalized(self):
        client = Mock()
        client.search.return_value = {"results": []}
        TavilySearch(client=client).search(
            "query", include_domains=[" StartupRecipe.co.kr ", "startuprecipe.co.kr"]
        )
        self.assertEqual(
            client.search.call_args.kwargs["include_domains"], ["startuprecipe.co.kr"]
        )
        self.assertEqual(
            client.search.call_args.kwargs["include_domains_mode"], "restrict"
        )

    def test_invalid_domain_does_not_call_api(self):
        client = Mock()
        for domain in [
            "https://example.com/path",
            "",
            "example.com.evil/path",
            "-bad.com",
        ]:
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                TavilySearch(client=client).search("query", include_domains=[domain])
        client.search.assert_not_called()

    def test_invalid_response_is_not_empty_success(self):
        client = Mock()
        client.search.return_value = {"error": "invalid response"}
        with self.assertRaises(WebSearchError):
            TavilySearch(client=client).search("query")

    def test_invalid_inputs_do_not_call_api(self):
        client = Mock()
        search = TavilySearch(client=client)
        for query, limit in [("", 10), ("x", 0), ("x", 21)]:
            with self.subTest(query=query, limit=limit), self.assertRaises(ValueError):
                search.search(query, max_results=limit)
        client.search.assert_not_called()
        with self.assertRaises(ValueError):
            TavilySearch(api_key=" ")


if __name__ == "__main__":
    unittest.main()
