"""quality_eval 판정 테스트 (D 담당). 키 없이 가짜 Judge로 실행한다."""

import json
from pathlib import Path

import pytest

from src.orchestration.quality_eval import (
    JudgeOutput,
    build_evidence_bundle,
    build_quality_eval,
    parse_excerpts,
    rule_checks,
    verify_excerpt,
)


def quality_eval(state, judge_fn, chunks=None):
    """원문 색인 없이 재현되도록 빈 청크를 기본으로 주입한다."""
    return build_quality_eval(judge_fn, {} if chunks is None else chunks)(state)

GOOD_MD = """# 보고서

## SUMMARY

**결론: 투자 추천 — A**

**핵심 리스크**: 관문 1개 미확인.

## 1. 평가 결과 순위표

AI 발굴 물질의 1상 성공률이 높다(Jayatunga 외, 2024). 규제 요구가 늘고 있다(식품의약품안전평가원, 2026).

## REFERENCE

**기관 보고서**

1. 식품의약품안전평가원(2026). *AI 의약품 규제 동향*. URL 미확인
2. 한국바이오협회(2026). *KBIOIS 브리프*. URL 미확인

**학술 논문**

1. Jayatunga, M. K. P., Ayers, M.(2024). How successful are AI-discovered drugs. *Drug Discovery Today*.
"""

GOOD = lambda md, bundle: JudgeOutput(groundedness=4, neutrality=4, bias=4, issues=[])  # noqa: E731
NO_JUDGE = lambda md, bundle: None  # noqa: E731


def _state(md=GOOD_MD, pages=3, **extra):
    return {"final_report": md, "report_pages": pages, "report_attempts": 1,
            "evaluation_history": [], "trace_id": "test", **extra}


def test_normal_report_passes():
    v = quality_eval(_state(), GOOD)["eval_result"]
    assert v["passed"] and not v["can_rewrite"] and v["judge_status"] == "completed"
    assert v["termination_reason"] is None


def test_forbidden_wording_is_fixable():
    u = quality_eval(_state(GOOD_MD.replace("높다", "압도적으로 높다")), GOOD)
    v = u["eval_result"]
    assert not v["passed"] and v["can_rewrite"]
    assert not v["rule_checks"]["neutral_wording"]
    assert any("중립성" in f for f in u["eval_feedback"])


def test_unknown_citation_is_fixable():
    md = GOOD_MD.replace("(Jayatunga 외, 2024)", "(Smith 외, 2023)")
    v = quality_eval(_state(md), GOOD)["eval_result"]
    assert not v["rule_checks"]["grounded_citations"] and v["can_rewrite"]


def test_judge_unavailable():
    u = quality_eval(_state(), NO_JUDGE)
    v = u["eval_result"]
    assert v["judge_status"] == "unavailable" and not v["passed"] and not v["can_rewrite"]
    assert "last_error" in u


def test_few_references_is_structural():
    md = GOOD_MD.split("**학술 논문**")[0].replace(
        "2. 한국바이오협회(2026). *KBIOIS 브리프*. URL 미확인", "")
    md = md.replace("(Jayatunga 외, 2024)", "")
    v = quality_eval(_state(md), GOOD)["eval_result"]
    assert not v["passed"] and not v["can_rewrite"]
    assert any("reference_count" in s for s in v["structural_issues"])


def test_page_over_limit_is_fixable():
    u = quality_eval(_state(pages=12), GOOD)
    assert u["eval_result"]["can_rewrite"]
    assert any("쪽수 초과" in f for f in u["eval_feedback"])


def test_pages_unknown_not_passed():
    v = quality_eval(_state(pages=None), GOOD)["eval_result"]
    assert not v["passed"] and not v["can_rewrite"]


@pytest.mark.parametrize("field", ["groundedness", "neutrality", "bias"])
def test_low_judge_score_gets_default_feedback(field):
    scores = {"groundedness": 4, "neutrality": 4, "bias": 4, field: 2}
    u = quality_eval(_state(), lambda md, b: JudgeOutput(**scores, issues=[]))
    assert u["eval_result"]["can_rewrite"] and u["eval_feedback"]


def test_excerpt_parsing_maps_question():
    text = "## QG 기술 독창성\n- 주장 [T3_1]\n  - 원문 근거: “AI 설계 후보물질” [T3_1]"
    assert parse_excerpts(text) == [{"question": "QG", "text": "AI 설계 후보물질", "source_ids": ["T3_1"]}]


def test_bundle_order_and_kinds():
    records = [
        {"name": "B", "verdict": "보류", "total": 60.0, "missing_weight": 0.1, "hold_reason": "총점 미달",
         "question_evidence": {"QA": {"rationale": "팀 경력", "references": [], "missing": False}},
         "tech_analysis": "## QG 독창성\n  - 원문 근거: “원문에 있는 문장” [T1_1]", "market_analysis": ""},
        {"name": "A", "verdict": "통과", "total": 80.0, "missing_weight": 0.0, "hold_reason": None,
         "question_evidence": {"QA": {"rationale": "x", "references": [], "missing": True}},
         "tech_analysis": "", "market_analysis": ""},
    ]
    state = {"evaluation_history": records,
             "worker_results": [{"company": "A", "task_index": 0}, {"company": "B", "task_index": 1}]}
    bundle, verification = build_evidence_bundle(state, chunks={"T1_1": "원문에 있는 문장 입니다"})
    assert [b["company"] for b in bundle][0] == "A"          # task_index 순
    assert not any(b["company"] == "A" and b["evidence_kind"] == "analysis_rationale" for b in bundle)  # 결측 제외
    assert {b["evidence_kind"] for b in bundle} == {"analysis_rationale", "rule_result", "source_excerpt"}
    excerpt = next(b for b in bundle if b["evidence_kind"] == "source_excerpt")
    assert excerpt["excerpt_verified"] and excerpt["source_locator"] == "T1_1"
    assert verification == "mixed"

    # 원문 청크를 확보하지 못하면 analysis_rationale로 내리고 검증 안 됨으로 기록한다
    bundle, verification = build_evidence_bundle(state, chunks={})
    item = next(b for b in bundle if b["source_locator"] == "T1_1")
    assert item["evidence_kind"] == "analysis_rationale" and not item["excerpt_verified"]
    assert verification == "consistency_only"


def test_verify_excerpt_ignores_space_and_case():
    chunks = {"T5:p3:t0": "AI-discovered molecules had 80-90% success in Phase I"}
    assert verify_excerpt("ai-discovered  molecules had", "T5:p3:t0", chunks)
    assert not verify_excerpt("Phase II success", "T5:p3:t0", chunks)
    assert not verify_excerpt("molecules", "UNKNOWN", chunks)


def test_hash_changes_with_body_and_contract_keys():
    a = quality_eval(_state(), GOOD)
    b = quality_eval(_state(GOOD_MD + "\n추가 문장"), GOOD)
    assert a["eval_result"]["evaluated_body_hash"] != b["eval_result"]["evaluated_body_hash"]
    assert set(a) >= {"eval_result", "eval_feedback", "step_count", "node_status"}
    assert a["step_count"] == 1


def test_sample_report_state_runs():
    """레포 샘플 보고서(가상 데이터)로 끝까지 실행된다."""
    path = Path("outputs/pipeline_state.json")
    if not path.exists():
        pytest.skip("REPORT_USE_LLM=0 python app.py --state samples/report_state.json 먼저 실행")
    state = json.loads(path.read_text(encoding="utf-8"))
    v = quality_eval({**state, "report_pages": 3}, GOOD)["eval_result"]
    assert v["source_verification"] in {"consistency_only", "mixed", "excerpt"}
    assert isinstance(rule_checks(state["final_report"], None, 3)[0], dict)
