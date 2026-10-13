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


def _records():
    return [
        {"name": "B", "verdict": "보류", "total": 60.0, "missing_weight": 0.1, "hold_reason": "총점 미달",
         "question_evidence": {"QA": {"rationale": "B 팀 경력", "references": [], "missing": False}},
         "tech_analysis": "## QG 독창성\n  - 원문 근거: “B 원문 문장입니다” [T9_9]", "market_analysis": ""},
        {"name": "A", "verdict": "통과", "total": 80.0, "missing_weight": 0.0, "hold_reason": None,
         "question_evidence": {"QA": {"rationale": "팀 경력", "references": [], "missing": False},
                               "QN": {"rationale": "x", "references": [], "missing": True}},
         "tech_analysis": "## QG 독창성\n  - 원문 근거: “원문에 있는 문장” [T1_1]", "market_analysis": ""},
    ]


def test_bundle_order_and_kinds():
    state = {"evaluation_history": _records(),
             "worker_results": [{"company": "A", "task_index": 0}, {"company": "B", "task_index": 1}]}
    bundle, verification = build_evidence_bundle(state, chunks={"T1_1": "원문에 있는 문장 입니다"})
    assert [b["company"] for b in bundle][0] == "A"          # task_index 순
    assert not any(b.get("question") == "QN" and b["evidence_kind"] == "analysis_rationale" for b in bundle)  # 결측 제외
    assert {b["evidence_kind"] for b in bundle} == {"analysis_rationale", "rule_result", "source_excerpt"}
    excerpt = next(b for b in bundle if b["evidence_kind"] == "source_excerpt")
    assert excerpt["excerpt_verified"] and excerpt["source_locator"] == "T1_1"
    assert verification == "mixed"

    # 원문 청크를 확보하지 못하면 analysis_rationale로 내리고 검증 안 됨으로 기록한다
    bundle, verification = build_evidence_bundle(state, chunks={})
    item = next(b for b in bundle if b["source_locator"] == "T1_1")
    assert item["evidence_kind"] == "analysis_rationale" and not item["excerpt_verified"]
    assert verification == "consistency_only"


def test_bundle_matches_report_scope():
    """질문별 근거·원문 인용은 보고서가 상세히 다루는 기업(추천 기업)만. 나머지는 판정 요약만."""
    state = {"evaluation_history": _records()}
    bundle, _ = build_evidence_bundle(state, chunks={"T1_1": "원문에 있는 문장 입니다"})
    b_items = [x for x in bundle if x["company"] == "B"]
    assert [x["evidence_kind"] for x in b_items] == ["rule_result"]
    assert "보류 사유 총점 미달" in b_items[0]["text"]
    a_rule = next(x for x in bundle if x["company"] == "A" and x["evidence_kind"] == "rule_result")
    assert "정보 부족 질문 QN" in a_rule["text"]

    # 통과 기업이 없으면 최고점 후보(B)가 상세 기업이 된다
    for r in state["evaluation_history"]:
        r["verdict"] = "보류"
    state["evaluation_history"][1]["total"] = 50.0
    bundle, _ = build_evidence_bundle(state, chunks={})
    assert any(x["company"] == "B" and x["evidence_kind"] == "analysis_rationale" for x in bundle)
    assert [x["evidence_kind"] for x in bundle if x["company"] == "A"] == ["rule_result"]


def test_judge_sees_only_llm_sentences():
    seen = {}

    def judge(view, bundle):
        seen["view"] = view
        return JudgeOutput(groundedness=4, neutrality=4, bias=4, issues=[])

    draft = {"kind": "no_pass", "payload": {"summary_reasons": ["근거 부족 기업이 3곳이다."],
                                            "top_gap": "최고점 후보는 관문에서 보류됐다.",
                                            "recheck": "결측 질문 근거가 확보되면 다시 평가한다."}}
    v = quality_eval(_state(report_draft=draft), judge)["eval_result"]
    assert v["passed"]
    assert "[SUMMARY 보류 사유 1] 근거 부족 기업이 3곳이다." in seen["view"]
    assert "[2.3 재검토 조건]" in seen["view"]
    assert seen["view"].index("평가 대상") < seen["view"].index("참고: 보고서 전문")


def test_pass_draft_targets():
    from src.orchestration.quality_eval import judge_targets

    draft = {"kind": "pass", "payload": {"reasons": [{"text": "이유1", "area": "market"}],
                                         "key_risk": "리스크", "s2_7": "관문 미확인 리스크",
                                         "s2_1": "개요", "s2_6": "", "s2_10": "가상 추가 소항목"}}
    names = [n for n, _ in judge_targets({"report_draft": draft})]
    # 2.7(사업 리스크와 한계점) 포함, 빈 소항목 제외, 숫자 순 정렬
    assert names == ["SUMMARY 투자 이유 1", "SUMMARY 핵심 리스크",
                     "2.1 상세 분석", "2.7 상세 분석", "2.10 상세 분석"]


def test_pass_targets_cover_all_agent6_sections():
    """agent6 DetailDraft의 2장 소항목 필드가 모두 평가 대상에 들어간다."""
    from src.agents.agent6_report import DetailDraft
    from src.orchestration.quality_eval import judge_targets

    fields = [f for f in DetailDraft.model_fields if f.startswith("s2_")]
    payload = {"reasons": [], "key_risk": "", **{f: f"{f} 문장" for f in fields}}
    names = [n for n, _ in judge_targets({"report_draft": {"kind": "pass", "payload": payload}})]
    assert len(names) == len(fields) and "2.7 상세 분석" in names


def test_empty_report_skips_judge():
    called = []
    draft = {"kind": "empty", "payload": {}}
    v = quality_eval(_state(report_draft=draft), lambda md, b: called.append(1))["eval_result"]
    assert not called and v["judge_status"] == "completed" and v["passed"]


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
