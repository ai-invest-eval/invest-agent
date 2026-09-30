"""기사의 정보 누락과 확인된 부적격 사유를 구분한다. 외부 API는 호출하지 않는다."""

from unittest.mock import Mock, patch

import pytest

from src.agents.agent1_search import Assessment, Lead, qualify


def assess(field=None, value=None, evidence=True):
    text = "Alpha develops AI drugs and raised Seed funding. Alpha status confirmed."
    citation = [{"document_id": "company0_0", "quote": "Alpha status confirmed."}]
    facts = {
        "ai_drug_discovery": {"value": True, "evidence": citation},
        "privately_held": {"value": None, "evidence": []},
        "exit_not_completed": {"value": None, "evidence": []},
        "not_large_corp_subsidiary": {"value": None, "evidence": []},
    }
    if field:
        facts[field] = {"value": value, "evidence": citation if evidence else []}
    result = Assessment(
        **facts,
        stage="seed",
        stage_original="Seed",
        stage_region=None,
        funding_evidence=citation,
        region_evidence=[],
    )
    generator, search = Mock(), Mock()
    generator.generate.return_value = result
    search.search.return_value = {
        "results": [{"url": "https://example.com/alpha", "content": text}]
    }
    lead = Lead(name="Alpha", aliases=[], country=None, evidence=[])
    with patch.dict("os.environ", {"ALLOW_RELAXED_QUALIFY": "1"}):
        return qualify(lead, [], generator, search, 0, lambda message: None)


def test_unknown_ownership_does_not_reject_candidate():
    candidate, _, assessment = assess()
    assert candidate["name"] == "Alpha"
    assert assessment.privately_held.value is None


@pytest.mark.parametrize(
    "field", ["privately_held", "exit_not_completed", "not_large_corp_subsidiary"]
)
def test_confirmed_disqualification_rejects_candidate(field):
    assert assess(field, False)[0] is None


@pytest.mark.parametrize("value", [True, False])
def test_unsupported_status_becomes_unknown(value):
    candidate, _, assessment = assess("privately_held", value, evidence=False)
    assert candidate is not None
    assert assessment.privately_held.value is None


def test_ai_business_still_requires_evidence():
    assert assess("ai_drug_discovery", None, evidence=False)[0] is None
