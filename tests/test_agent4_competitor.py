"""4번 노드가 근거 수준과 State 반환 계약을 지키는지 검증한다."""

from copy import deepcopy

from src.agents.agent4_competitor import CompetitorAgent


def state():
    return {
        "selected_startup": {"name": "가상 바이오"},
        "startup_profile": {
            "name": "가상 바이오",
            "business_model": "platform",
            "lead_service": "AI 후보물질 설계",
        },
        "tech_analysis": "AI 설계 기술은 공개된 근거만 확인했다.",
        "market_analysis": "제약사 수요는 산업 자료로 확인했다.",
        "references": [],
    }


def draft(source_id, quote):
    claim = {
        "text": "경쟁 제품과 차이가 확인됐다.",
        "status": "supported",
        "citations": [{"source_id": source_id, "quote": quote}],
    }
    return {
        "competitors": [
            {
                "name": "경쟁사 A",
                "category": "peer",
                "product": "AI 후보물질 설계",
                "relevance": claim,
            }
        ],
        "criterion_evidence": {
            "QI": {"availability": "found", "claims": [claim]},
        },
    }


def test_web_quote_is_linked_and_only_new_reference_returned():
    source = {
        "url": "https://example.com/competitor",
        "title": "경쟁사 비교 자료",
        "content": "동일 조건에서 검증한 AI 후보물질 설계 사례",
    }

    def analyze(payload):
        web = next(item for item in payload["sources"] if item["kind"] == "web")
        return draft(web["source_id"], "동일 조건에서 검증한")

    input_state = state()
    original = deepcopy(input_state)
    result = CompetitorAgent(lambda _: {"results": [source]}, analyze, 1)(input_state)
    assert input_state == original
    assert set(result) == {"competitor_analysis", "references"}
    assert "자료 상태: 근거 있음" in result["competitor_analysis"]
    assert result["references"][0]["url"] == source["url"]
    assert "투자 추천" not in result["competitor_analysis"]


def test_invalid_quote_becomes_unknown_without_reference():
    source = {
        "url": "https://example.com/competitor",
        "title": "경쟁사 비교 자료",
        "content": "비교 조건은 공개되지 않았다.",
    }

    def analyze(payload):
        web = next(item for item in payload["sources"] if item["kind"] == "web")
        return draft(web["source_id"], "임상 성공률 99%")

    result = CompetitorAgent(lambda _: {"results": [source]}, analyze, 1)(state())
    assert "자료 상태: 정보 없음" in result["competitor_analysis"]
    assert "임상 성공률 99%" not in result["competitor_analysis"]
    assert result["references"] == []


def test_upstream_analysis_is_inference_not_company_proof():
    result = CompetitorAgent(
        lambda _: {"results": []},
        lambda _: draft("tech_analysis", "AI 설계 기술은 공개된 근거만 확인했다."),
        1,
    )(state())
    assert "[추론]" in result["competitor_analysis"]
    assert "자료 상태: 정보 없음" in result["competitor_analysis"]
    assert result["references"] == []
