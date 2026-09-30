"""검색 계획·근거 검사·중복 병합을 가짜 모델로 재현한다."""

import unittest
from unittest.mock import patch

from src.agents.agent1_discovery import (
    CandidateLead,
    DuplicateGroups,
    ExtractedLeads,
    PlannedQuery,
    SearchPlan,
    extract_candidate_leads,
    merge_duplicate_leads,
    plan_searches,
    prepare_documents,
    validate_lead,
)


class FakeGenerator:
    def __init__(self, *responses):
        self.responses = iter(responses)

    def generate(self, schema, system, payload):
        response = next(self.responses)
        assert isinstance(response, schema)
        return response


def lead(name="Alpha", **changes):
    values = {
        "name": name,
        "aliases": [],
        "country": None,
        "funding_stage_original": None,
        "official_website": None,
        "evidence": [{"document_id": "doc0000", "quote": "Alpha develops drugs."}],
    }
    return CandidateLead(**(values | changes))


def collection():
    return {
        "status": "ok",
        "searches": [
            {
                "status": "ok",
                "include_domains": ["example.com"],
                "response": {
                    "results": [
                        {
                            "url": "https://example.com/article",
                            "title": "Alpha",
                            "raw_content": "Alpha develops drugs.",
                        }
                    ]
                },
            }
        ],
    }


class DiscoveryTests(unittest.TestCase):
    def plan(self):
        return SearchPlan(
            queries=[
                PlannedQuery(source_key=k, query=f"{k} discovery")
                for k in ("startup_recipe", "cure", "yc")
            ]
        )

    def test_plan_is_variable_and_domains_fixed(self):
        requests = plan_searches(FakeGenerator(self.plan()), "신약", max_requests=12)
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[0].include_domains, ("startuprecipe.co.kr",))

    def test_missing_source_rejected(self):
        plan = self.plan()
        plan.queries[2].source_key = "cure"
        with self.assertRaises(ValueError):
            plan_searches(FakeGenerator(plan), "신약")

    def test_budget_and_duplicate_rejected(self):
        plan = self.plan()
        plan.queries.append(plan.queries[0])
        for budget in (3, 12):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                plan_searches(FakeGenerator(plan), "신약", max_requests=budget)

    def test_deduplicate_url_and_drop_outside_domain(self):
        data = collection()
        data["searches"][0]["response"]["results"] += [
            {"url": "https://example.com/article#top", "raw_content": "short"},
            {"url": "https://outside.com", "raw_content": "outside"},
        ]
        docs = prepare_documents(data)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["text"], "Alpha develops drugs.")

    def test_split_preserves_tail_and_overlap(self):
        with (
            patch("src.agents.agent1_discovery.DOCUMENT_CHARS", 10),
            patch("src.agents.agent1_discovery.DOCUMENT_OVERLAP", 2),
        ):
            docs = prepare_documents(collection())
        self.assertEqual(docs[0]["text"][-2:], docs[1]["text"][:2])
        restored = docs[0]["text"] + "".join(d["text"][2:] for d in docs[1:])
        self.assertEqual(restored, "Alpha develops drugs.")

    def test_bad_quote_and_document_rejected(self):
        docs = {d["document_id"]: d for d in prepare_documents(collection())}
        for evidence in (
            {"document_id": "missing", "quote": "Alpha"},
            {"document_id": "doc0000", "quote": "Alpha is public"},
        ):
            self.assertIsNotNone(validate_lead(lead(evidence=[evidence]), docs))

    def test_unconfirmed_website_cleared(self):
        candidate = lead(official_website="https://invented.com")
        docs = {d["document_id"]: d for d in prepare_documents(collection())}
        self.assertIsNone(validate_lead(candidate, docs))
        self.assertIsNone(candidate.official_website)

    def test_merge_conflict_is_none(self):
        docs = {d["document_id"]: d for d in prepare_documents(collection())}
        merged = merge_duplicate_leads(
            FakeGenerator(DuplicateGroups(groups=[[0, 1]])),
            [lead(country="KR"), lead("알파", country="US")],
            docs,
        )
        self.assertEqual(len(merged), 1)
        self.assertIsNone(merged[0].country)
        self.assertIn("알파", merged[0].aliases)
        self.assertEqual(len(merged[0].evidence), 1)

    def test_group_cannot_drop_or_repeat_candidate(self):
        docs = {d["document_id"]: d for d in prepare_documents(collection())}
        with self.assertRaises(ValueError):
            merge_duplicate_leads(
                FakeGenerator(DuplicateGroups(groups=[[0, 0]])), [lead(), lead()], docs
            )

    def test_extraction_keeps_unverified_status(self):
        result = extract_candidate_leads(
            FakeGenerator(ExtractedLeads(leads=[lead()])), collection()
        )
        self.assertEqual(result["lead_count"], 1)
        self.assertEqual(result["status"], "extracted_unverified")

    def test_failed_collection_is_not_empty_success(self):
        with self.assertRaises(ValueError):
            extract_candidate_leads(FakeGenerator(), {"status": "error"})
