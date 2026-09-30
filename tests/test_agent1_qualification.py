"""자격 관문·미확인·검색 장애·호출 상한을 외부 API 없이 검증한다."""

import unittest
from datetime import date
from unittest.mock import Mock, patch

from src.agents.agent1_discovery import CandidateLead
from src.agents.agent1_qualification import (
    CHECK_KEYS,
    EvidenceAudit,
    QualificationAssessment,
    assessment_with_quotes,
    audit_assessment,
    qualification_documents,
    qualification_outcome,
    qualify_candidate,
    validate_assessment,
)
from src.tools.structured_llm import StructuredLLMError
from src.tools.web_search import WebSearchError

TEXT = "Alpha is a private independent AI drug discovery company. No completed acquisition. Series A."


def candidate():
    return CandidateLead(
        name="Alpha",
        aliases=[],
        country=None,
        funding_stage_original=None,
        official_website=None,
        evidence=[],
    )


def assessment(stage="series_a", **checks):
    evidence = [{"document_id": "qual0000", "passage_id": "p0000"}]
    return QualificationAssessment.model_validate(
        {
            **{
                key: {
                    "value": checks.get(key, True),
                    "reason": "원문 확인",
                    "evidence": evidence,
                }
                for key in CHECK_KEYS
            },
            "funding": {
                "stage": stage,
                "stage_original": "Series A",
                "reason": "원문 확인",
                "evidence": [{"document_id": "qual0000", "passage_id": "p0002"}],
            },
        }
    )


def response(text=TEXT):
    return {
        "results": [
            {"url": "https://example.com/alpha", "title": "Alpha", "content": text}
        ]
    }


class QualificationTests(unittest.TestCase):
    def setUp(self):
        # 검색/분류 테스트는 충분성 모델을 분리한다. 충분성 처리는 별도 테스트한다.
        audit_patch = patch(
            "src.agents.agent1_qualification.audit_assessment", return_value={}
        )
        audit_patch.start()
        self.addCleanup(audit_patch.stop)

    def test_insufficient_meaning_becomes_unknown(self):
        docs = qualification_documents([{"status": "ok", "response": response()}])
        audit = EvidenceAudit.model_validate(
            {
                key: {
                    "sufficient": key != "not_large_corp_subsidiary",
                    "reason": "지배 관계 근거 부족",
                }
                for key in (*CHECK_KEYS, "funding")
            }
        )
        claim = assessment()
        audit_assessment(Mock(generate=Mock(return_value=audit)), claim, docs)
        self.assertIsNone(claim.not_large_corp_subsidiary.value)
        self.assertEqual(qualification_outcome(claim)["status"], "unconfirmed")

    def test_supported_false_claim_remains_false(self):
        docs = qualification_documents([{"status": "ok", "response": response()}])
        audit = EvidenceAudit.model_validate(
            {
                key: {"sufficient": True, "reason": "현재 주장 확인"}
                for key in (*CHECK_KEYS, "funding")
            }
        )
        claim = assessment(not_large_corp_subsidiary=False)
        audit_assessment(Mock(generate=Mock(return_value=audit)), claim, docs)
        self.assertIs(claim.not_large_corp_subsidiary.value, False)
        self.assertEqual(qualification_outcome(claim)["status"], "excluded")

    def test_audit_error_preserves_searches_without_confirming(self):
        with patch(
            "src.agents.agent1_qualification.audit_assessment",
            side_effect=StructuredLLMError("검증 호출 실패"),
        ):
            result = self.run_candidate(
                Mock(search=Mock(return_value=response())),
                Mock(generate=Mock(return_value=assessment())),
            )
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["model_status"], "error")
        self.assertEqual(len(result["searches"]), 2)

    def test_all_checks_confirmed(self):
        self.assertEqual(qualification_outcome(assessment())["status"], "eligible")

    def test_unknown_is_not_true(self):
        result = qualification_outcome(assessment(privately_held=None))
        self.assertEqual(result["status"], "unconfirmed")
        self.assertIn("privately_held", result["missing_checks"])

    def test_false_wins_over_missing(self):
        self.assertEqual(
            qualification_outcome(
                assessment(privately_held=None, not_large_corp_subsidiary=False)
            )["status"],
            "excluded",
        )

    def test_stage_bounds(self):
        for stage in ("seed", "pre_a", "series_a", "series_b", "series_c"):
            self.assertEqual(
                qualification_outcome(assessment(stage))["status"], "eligible"
            )
        for stage in ("pre_seed", "series_d", "series_e", "series_f", "later"):
            self.assertEqual(
                qualification_outcome(assessment(stage))["status"], "excluded"
            )
        for stage in (None, "bridge"):
            self.assertEqual(
                qualification_outcome(assessment(stage))["status"], "unconfirmed"
            )

    def test_bad_evidence_becomes_unknown(self):
        claim = assessment()
        claim.privately_held.evidence[0].passage_id = "invented"
        docs = qualification_documents([{"status": "ok", "response": response()}])
        self.assertTrue(validate_assessment(claim, candidate(), docs))
        self.assertIsNone(claim.privately_held.value)

    def test_stage_original_must_appear_in_quote(self):
        claim = assessment()
        claim.funding.stage_original = "Series B"
        docs = qualification_documents([{"status": "ok", "response": response()}])
        validate_assessment(claim, candidate(), docs)
        self.assertIsNone(claim.funding.stage)

    def test_other_company_and_document_rejected(self):
        for text in ("Other corporation. Series A.", TEXT):
            claim = assessment()
            if text == TEXT:
                claim.ai_drug_discovery.evidence[0].document_id = "missing"
            source = response(text)
            if text != TEXT:
                source["results"][0]["title"] = "Other corporation"
            docs = qualification_documents([{"status": "ok", "response": source}])
            validate_assessment(claim, candidate(), docs)
            self.assertIsNone(claim.ai_drug_discovery.value)

    def test_excerpt_is_explicitly_limited(self):
        docs = qualification_documents(
            [{"status": "ok", "response": response("x" * 7000)}]
        )
        self.assertEqual(len(docs[0]["text"]), 6000)
        self.assertTrue(docs[0]["truncated"])

    def test_quote_is_copied_by_code(self):
        docs = qualification_documents([{"status": "ok", "response": response()}])
        claim = assessment()
        self.assertEqual(validate_assessment(claim, candidate(), docs), [])
        result = assessment_with_quotes(claim, docs)
        self.assertEqual(result["funding"]["evidence"][0]["quote"], "Series A.")

    def run_candidate(self, search, generator):
        return qualify_candidate(
            generator, search, candidate(), as_of=date(2026, 9, 30)
        )

    def test_confirmed_candidate_uses_two_searches(self):
        search = Mock(search=Mock(return_value=response()))
        generator = Mock(generate=Mock(return_value=assessment()))
        result = self.run_candidate(search, generator)
        self.assertEqual(result["status"], "eligible")
        self.assertEqual(search.search.call_count, 2)
        self.assertEqual(generator.generate.call_count, 1)

    def test_missing_triggers_one_retry_with_new_documents(self):
        search = Mock(
            search=Mock(
                side_effect=[
                    response(),
                    response(),
                    response(TEXT + " New ownership details."),
                ]
            )
        )
        generator = Mock(
            generate=Mock(side_effect=[assessment(privately_held=None), assessment()])
        )
        result = self.run_candidate(search, generator)
        self.assertEqual(result["status"], "eligible")
        self.assertEqual(result["search_count"], 3)
        self.assertEqual(len(result["attempts"]), 2)

    def test_same_documents_do_not_repeat_model(self):
        search = Mock(search=Mock(return_value=response()))
        generator = Mock(generate=Mock(return_value=assessment(privately_held=None)))
        result = self.run_candidate(search, generator)
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["search_count"], 3)
        self.assertEqual(generator.generate.call_count, 1)

    def test_all_search_errors_are_distinct(self):
        search = Mock(search=Mock(side_effect=WebSearchError("검색 실패")))
        generator = Mock()
        result = self.run_candidate(search, generator)
        self.assertEqual(result["search_status"], "error")
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(result["search_count"], 3)
        generator.generate.assert_not_called()

    def test_empty_search_success_not_api_error(self):
        search = Mock(search=Mock(return_value={"results": []}))
        result = self.run_candidate(search, Mock())
        self.assertEqual(result["search_status"], "ok")
        self.assertEqual(result["model_status"], "not_called")
        self.assertEqual(result["status"], "unconfirmed")

    def test_model_error_preserves_searches(self):
        search = Mock(search=Mock(return_value=response()))
        result = self.run_candidate(
            search, Mock(generate=Mock(side_effect=StructuredLLMError("호출 실패")))
        )
        self.assertEqual(result["model_status"], "error")
        self.assertEqual(result["status"], "unconfirmed")
        self.assertEqual(len(result["searches"]), 2)

    def test_official_domain_is_used_only_for_first_search(self):
        lead = candidate()
        lead.official_website = "https://example.com"
        search = Mock(search=Mock(return_value=response()))
        qualify_candidate(
            Mock(generate=Mock(return_value=assessment())),
            search,
            lead,
            as_of=date(2026, 9, 30),
        )
        self.assertEqual(
            search.search.call_args_list[0].kwargs["include_domains"], ["example.com"]
        )
        self.assertIsNone(search.search.call_args_list[1].kwargs["include_domains"])
