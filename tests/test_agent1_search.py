"""Agent 1 단일 파일의 후보 탐색·자격 판단·재진입 계약을 API 없이 확인한다."""

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from src.agents.agent1_search import (
    Agent1SearchError,
    Assessment,
    Lead,
    Leads,
    discover,
    documents_from_response,
    normalize_stage,
    qualify,
    startup_search,
)
from src.state import create_initial_state
from src.tools.web_search import WebSearchError

TEXT = "Alpha is an independent private AI drug discovery startup with Seed funding."
DOC = {
    "document_id": "source0_0",
    "url": "https://startuprecipe.co.kr/alpha",
    "title": "Alpha",
    "text": TEXT,
}


def lead():
    return Lead(
        name="Alpha",
        aliases=["Alpha Bio"],
        country=None,
        evidence=[{"document_id": DOC["document_id"], "quote": TEXT}],
    )


def assessment():
    evidence = [{"document_id": DOC["document_id"], "quote": TEXT}]
    fact = {"value": True, "evidence": evidence}
    return Assessment(
        ai_drug_discovery=fact,
        privately_held=fact,
        exit_not_completed=fact,
        not_large_corp_subsidiary=fact,
        stage="seed",
        stage_original="Seed",
        stage_region=None,
        funding_evidence=evidence,
        region_evidence=[],
    )


class Agent1SearchTests(unittest.TestCase):
    def test_reentry_skips_evaluated_and_does_not_call_api(self):
        state = create_initial_state("AI")
        state["candidate_startups"] = [{"name": "Alpha"}, {"name": "Beta"}]
        state["evaluation_history"] = [{"name": " ALPHA "}]
        before = deepcopy(state)
        with patch("src.agents.agent1_search.GPTStructuredGenerator") as client:
            result = startup_search(state)
        client.assert_not_called()
        self.assertEqual(result["selected_startup"]["name"], "Beta")
        self.assertEqual(state, before)
        self.assertEqual(result["references"], [])
        self.assertIsNone(result["startup_profile"])
        self.assertEqual(result["tech_analysis"], "")
        self.assertNotIn("evaluation_history", result)

    def test_exhausted_candidates_returns_none_without_api(self):
        state = create_initial_state("AI")
        state["evaluation_history"] = [{"name": "Alpha"}]
        with patch("src.agents.agent1_search.TavilySearch") as search:
            self.assertIsNone(startup_search(state)["selected_startup"])
        search.assert_not_called()

    def test_invalid_maximum(self):
        state = create_initial_state("AI")
        for value in (0, -1, True):
            state["max_candidates"] = value
            with self.assertRaises(ValueError):
                startup_search(state)

    def test_foreign_suffix_requires_investment_market(self):
        self.assertEqual(normalize_stage("series_a", None), "시리즈 A")
        self.assertEqual(normalize_stage("series_a", "foreign"), "시리즈 AF")
        self.assertEqual(normalize_stage("series_a", "domestic"), "시리즈 A")

    def test_domain_filter_hacker_news_and_duplicate_url(self):
        response = {
            "results": [
                {"url": "https://news.ycombinator.com/item", "content": TEXT},
                {"url": "https://other.com/alpha", "content": TEXT},
                {"url": "https://ycombinator.com/companies/alpha", "content": "Alpha"},
                {"url": "https://ycombinator.com/companies/alpha#x", "content": TEXT},
            ]
        }
        docs = documents_from_response(response, "source", "ycombinator.com")
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["text"], TEXT)

    def test_long_documents_keep_tail(self):
        docs = documents_from_response(
            {"results": [{"url": DOC["url"], "content": "a" * 24000 + "TAIL"}]},
            "source",
        )
        self.assertTrue(docs[-1]["text"].endswith("TAIL"))

    def test_discover_uses_three_sources_and_deduplicates(self):
        search = Mock()
        search.search.side_effect = [
            {"results": [{"url": DOC["url"], "content": TEXT}]},
            {"results": []},
            {"results": []},
        ]
        duplicate = lead()
        duplicate.name = "Alpha Bio"
        generator = Mock()
        generator.generate.return_value = Leads(companies=[lead(), duplicate])
        leads, docs = discover("AI", 15, generator, search, lambda _: None)
        self.assertEqual(len(leads), 1)
        self.assertEqual(search.search.call_count, 3)
        self.assertEqual(generator.generate.call_count, 1)
        self.assertTrue(docs)

    def test_nonempty_search_without_body_is_error(self):
        search = Mock()
        search.search.return_value = {"results": [{"url": DOC["url"], "content": ""}]}
        with self.assertRaises(Agent1SearchError):
            discover("AI", 15, Mock(), search, lambda _: None)

    def test_qualification_uses_one_search_and_one_judgment(self):
        search = Mock()
        search.search.return_value = {"results": []}
        generator = Mock()
        generator.generate.return_value = assessment()
        candidate, refs, _ = qualify(
            lead(), [DOC], generator, search, 0, lambda _: None
        )
        self.assertEqual(candidate["stage"], "시드")
        self.assertIsNone(candidate["stage_region"])
        self.assertEqual(refs[0]["url"], DOC["url"])
        self.assertEqual(search.search.call_count, 1)
        self.assertEqual(generator.generate.call_count, 1)

    def test_unconfirmed_false_and_missing_evidence_are_not_eligible(self):
        for value, evidence in ((None, []), (False, []), (True, [])):
            result = assessment()
            result.privately_held.value = value
            result.privately_held.evidence = evidence
            generator = Mock()
            generator.generate.return_value = result
            search = Mock()
            search.search.return_value = {"results": []}
            candidate, refs, _ = qualify(
                lead(), [DOC], generator, search, 0, lambda _: None
            )
            self.assertIsNone(candidate)
            self.assertEqual(refs, [])

    def test_outside_stage_and_generated_quote_are_rejected(self):
        for outside in (True, False):
            result = assessment()
            if outside:
                result.stage = "outside"
            else:
                result.funding_evidence[0].quote = "invented funding quote"
            generator = Mock()
            generator.generate.return_value = result
            search = Mock()
            search.search.return_value = {"results": []}
            self.assertIsNone(
                qualify(lead(), [DOC], generator, search, 0, lambda _: None)[0]
            )

    def test_api_failure_is_not_empty_candidate_result(self):
        search = Mock()
        search.search.side_effect = WebSearchError("검색 실패")
        with self.assertRaises(Agent1SearchError):
            startup_search(create_initial_state("AI"), generator=Mock(), search=search)

    def test_full_node_caps_candidates_saves_result_and_new_refs_only(self):
        state = create_initial_state("AI", max_candidates=1)
        state["references"] = [{"company": "Alpha", "url": DOC["url"]}]
        candidate = {
            "name": "Alpha",
            "country": None,
            "stage": "시드",
            "stage_region": None,
            "stage_original": "Seed",
            "source_url": DOC["url"],
        }
        with (
            TemporaryDirectory() as directory,
            patch("src.agents.agent1_search.PROJECT_ROOT", Path(directory)),
            patch(
                "src.agents.agent1_search.discover",
                return_value=([lead(), lead()], [DOC]),
            ),
            patch(
                "src.agents.agent1_search.qualify",
                return_value=(candidate, state["references"], assessment()),
            ) as judgment,
        ):
            result = startup_search(state, generator=Mock(), search=Mock())
            self.assertEqual(
                len(list((Path(directory) / "outputs/agent1").glob("*.json"))), 1
            )
        self.assertEqual(judgment.call_count, 1)
        self.assertEqual(result["references"], [])
        self.assertEqual(result["selected_startup"], candidate)

    def test_successful_empty_search_is_empty_result(self):
        search = Mock()
        search.search.return_value = {"results": []}
        generator = Mock()
        with (
            TemporaryDirectory() as directory,
            patch("src.agents.agent1_search.PROJECT_ROOT", Path(directory)),
        ):
            result = startup_search(
                create_initial_state("AI"), generator=generator, search=search
            )
        self.assertIsNone(result["selected_startup"])
        generator.generate.assert_not_called()
