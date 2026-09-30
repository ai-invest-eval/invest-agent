"""Agent 5 단독 검증 (가짜 LLM, API 키 불필요).

실행: uv run --with pytest python -m pytest -q tests/test_agent5_decision.py
"""

import copy
import json
from pathlib import Path

import pytest

from src.agents import agent5_config as cfg
from src.agents import agent5_scoring as scoring
from src.agents.agent5_decision import JudgeItem, JudgeResult, build_update, evaluate

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
QUOTE = "생명과학 박사"  # 샘플 프로필에 실제로 있는 문장


def load(kind: str) -> dict:
    return json.loads(
        (SAMPLES / f"state_agent5_{kind}.json").read_text(encoding="utf-8")
    )


def ans(score, ref_ids=("R1",), quote=QUOTE, missing=False, reason="근거"):
    return {
        "score": score,
        "ref_ids": list(ref_ids),
        "quote": quote,
        "missing": missing,
        "reason": reason,
    }


MISSING = {
    "score": None,
    "ref_ids": [],
    "quote": None,
    "missing": True,
    "reason": "정보 없음",
}


def answers(score=4, **override):
    a = {q: ans(score) for q in cfg.ALL_QUESTIONS}
    a.update(override)
    return a


class FakeLLM:
    """영역별 프롬프트에서 질문 목록을 읽어 정해 둔 답을 돌려준다."""

    def __init__(self, table, fail_areas=(), fail_times=99):
        self.table, self.fail_areas, self.fail_times, self.calls = (
            table,
            set(fail_areas),
            fail_times,
            0,
        )

    def batch(self, prompts, return_exceptions=False):
        self.calls += 1
        out = []
        for p in prompts:
            qs = p.rsplit("질문 ", 1)[1].split(" 각각")[0].split(", ")
            if self.calls <= self.fail_times and any(
                f"({cfg.AREA_NAMES[a]})" in p for a in self.fail_areas
            ):
                out.append(RuntimeError("API 오류"))
                continue
            out.append(
                JudgeResult(
                    items=[
                        JudgeItem(question=q, **self.table[q])
                        for q in qs
                        if q in self.table
                    ]
                )
            )
        return out


@pytest.fixture
def state():
    return load("pipeline")


# ── 반환 계약 ────────────────────────────────────────────────
def test_update_contract(state):
    before = copy.deepcopy(state)
    out = build_update(state, FakeLLM(answers(4)))
    assert set(out) == {"investment_decision", "evaluation_history"}
    assert len(out["evaluation_history"]) == 1
    rec = out["evaluation_history"][0]
    assert (
        rec["name"] == "가상 바이오 A"
        and rec["total"] == out["investment_decision"]["total"]
    )
    assert rec["startup_profile"] == state["startup_profile"]
    assert state == before  # 입력 State를 바꾸지 않음
    d = out["investment_decision"]
    assert set(d) == {
        "total",
        "area_scores",
        "question_scores",
        "question_evidence",
        "verdict",
        "hold_reason",
        "unconfirmed_gates",
        "missing_weight",
        "rationale",
    }
    ev = d["question_evidence"]["QA"]
    assert set(ev) == {"score", "rationale", "references", "missing"}
    assert ev["references"][0]["url"] == "https://example.invalid/company-a/ir"


def test_all_confirmed_pass(state):
    d = evaluate(state, FakeLLM(answers(4)))
    assert d["total"] == pytest.approx(80) and d["missing_weight"] == 0
    assert d["verdict"] == "통과" and d["hold_reason"] is None


# ── 결측·근거 검증 ────────────────────────────────────────────
def test_missing_scores_and_weight_include_deal(state):
    d = evaluate(state, FakeLLM(answers(4, QA=MISSING, QN=MISSING)))
    assert d["question_scores"]["QA"] == 2 and d["question_scores"]["QN"] == 3
    assert (
        d["question_evidence"]["QN"]["missing"]
        and d["question_evidence"]["QN"]["references"] == []
    )
    assert d["missing_weight"] == pytest.approx(0.30 / 3 + 0.10 / 2)  # QN도 포함


def test_bad_ref_id_and_made_up_quote(state):
    table = answers(
        4, QA=ans(5, ref_ids=["R99"]), QE=ans(5, quote="승인 치료제가 없다")
    )
    d = evaluate(state, FakeLLM(table))
    assert d["question_evidence"]["QA"]["rationale"] == "정보 없음 (출처 없음)"
    assert d["question_evidence"]["QE"]["rationale"] == "정보 없음 (근거 문장 불일치)"


def test_other_company_reference_excluded(state):
    state["references"].append(
        {**state["references"][0], "company": "다른 회사", "url": "https://x.invalid"}
    )
    refs = scoring.collect_references(state)
    assert all(r["company"] == "가상 바이오 A" for r in refs)
    urls = [r.get("url") for r in refs]
    assert len(urls) == len(set(urls))  # 같은 출처 중복 없음


def test_unknown_business_model_only_qd_missing(state):
    state["startup_profile"]["business_model"] = "unknown"
    d = evaluate(state, FakeLLM(answers(4)))
    assert d["question_evidence"]["QD"]["missing"]
    assert d["question_evidence"]["QD"]["rationale"] == "사업 모델 미확인으로 정보 부족"
    assert sum(e["missing"] for e in d["question_evidence"].values()) == 1


def test_platform_uses_platform_qd_rubric():
    from src.agents.agent5_decision import build_prompts

    s = load("platform")
    prompts = build_prompts(s, {})
    market = next(p for a, _, p in prompts if a == "market")
    assert "플랫폼형" in market and "50억 달러 이상" in market


# ── 관문과 판정 순서 ──────────────────────────────────────────
def test_eligibility_none_holds(state):
    state["startup_profile"]["gates"]["subsidiary_of_large_corp"] = None
    d = evaluate(state, FakeLLM(answers(5)))
    assert d["hold_reason"] == "자격 미확인"


def test_risk_true_holds_with_label(state):
    state["startup_profile"]["gates"]["clinical_failure"] = True
    d = evaluate(state, FakeLLM(answers(5)))
    assert d["hold_reason"] == "관문 (주력 파이프라인 임상 중단·실패)"


def test_risk_none_continues_and_recorded(state):
    d = evaluate(state, FakeLLM(answers(4)))  # 샘플의 리스크 관문 3개가 None
    assert d["verdict"] == "통과"
    assert d["unconfirmed_gates"] == [
        "clinical_failure",
        "patent_loss",
        "funding_gap_restructuring",
    ]
    assert (
        state["startup_profile"]["gates"]["clinical_failure"] is None
    )  # 원본 None 유지


def test_missing_30_before_total(state):
    d = evaluate(state, FakeLLM(answers(5, QA=MISSING, QB=MISSING, QC=MISSING)))
    assert (
        d["missing_weight"] == pytest.approx(0.30) and d["hold_reason"] == "근거 부족"
    )


def test_float_boundary_75(state):
    # 수학적으로 정확히 75점이지만 부동소수점으로는 74.99999999999999가 되는 조합
    scores = {
        "QA": 4,
        "QB": 4,
        "QC": 4,
        "QD": 3,
        "QE": 5,
        "QF": 5,
        "QG": 5,
        "QH": 5,
        "QI": 2,
        "QJ": 3,
        "QK": 3,
        "QL": 3,
        "QM": 2,
        "QN": 3,
        "QO": 1,
    }
    d = evaluate(state, FakeLLM({q: ans(v) for q, v in scores.items()}))
    assert d["total"] < 75  # 오차가 실제로 생기는 경우
    assert d["verdict"] == "통과"  # 그래도 75점 이상으로 판정


def test_founder_below_60(state):
    d = evaluate(state, FakeLLM(answers(5, QA=ans(2), QB=ans(3), QC=ans(3))))
    assert d["total"] >= 75 and d["hold_reason"] == "창업자 미달"


def test_exact_75_passes_without_rounding(state):
    table = answers(4, QD=ans(3), QE=ans(3), QF=ans(3))  # 시장성 60 → 총점 75
    d = evaluate(state, FakeLLM(table))
    assert d["total"] == pytest.approx(75) and d["verdict"] == "통과"


def test_no_rounding_in_scores(state):
    d = evaluate(state, FakeLLM(answers(4, QA=ans(5))))
    assert d["area_scores"]["founder"] == pytest.approx(86.6666666, rel=1e-6)


# ── LLM 오류는 결측으로 위장하지 않음 ───────────────────────────
def test_api_error_retried_then_ok(state):
    llm = FakeLLM(answers(4), fail_areas={"founder"}, fail_times=1)
    d = evaluate(state, llm)
    assert llm.calls == 2 and not d["question_evidence"]["QA"]["missing"]


def test_api_error_raises_after_retry(state):
    with pytest.raises(RuntimeError, match="LLM 호출 실패"):
        evaluate(state, FakeLLM(answers(4), fail_areas={"founder"}))


def test_validate_decision_catches_mismatch():
    ev = {
        q: {"score": 3, "rationale": "", "references": [], "missing": False}
        for q in cfg.ALL_QUESTIONS
    }
    d = {
        "question_scores": {**{q: 3 for q in cfg.ALL_QUESTIONS}, "QA": 4},
        "question_evidence": ev,
        "area_scores": dict.fromkeys(cfg.WEIGHTS, 60.0),
        "missing_weight": 0.0,
    }
    with pytest.raises(ValueError):
        scoring.validate_decision(d)


# ── 리뷰 반영 ────────────────────────────────────────────────
def test_confirmed_none_from_profile_json_is_not_missing():
    # 플랫폼 B: 자체 파이프라인 없음이 확인된 사실([])이면 결측이 아니다
    s = load("platform")
    table = answers(4, QH=ans(1, quote='"pipeline": []'))
    d = evaluate(s, FakeLLM(table))
    assert not d["question_evidence"]["QH"]["missing"]
    assert d["question_scores"]["QH"] == 1


def test_history_record_is_copy(state):
    out = build_update(state, FakeLLM(answers(4)))
    rec = out["evaluation_history"][0]
    assert rec["startup_profile"] == state["startup_profile"]
    assert rec["startup_profile"] is not state["startup_profile"]
    assert (
        rec["question_evidence"] is not out["investment_decision"]["question_evidence"]
    )


def test_unknown_business_model_does_not_ask_qd(state):
    from src.agents.agent5_decision import build_prompts

    state["startup_profile"]["business_model"] = "unknown"
    market = next(p for a, _, p in build_prompts(state, {}) if a == "market")
    assert "[QD]" not in market and "질문 QE, QF 각각" in market


def test_analysis_source_tag_links_to_reference():
    from src.agents.agent5_decision import analysis_source_aliases

    rag = {
        "company": "가상 바이오 A",
        "agent": "market",
        "title": "글로벌 AI 기반 생명공학 시장 현황 및 전망(KBIOIS 브리프 Vol.91)",
        "source": "RAG",
        "page": 1,
    }
    state = {
        "market_analysis": "## 사용 출처\n- [M6:p1:t0] 글로벌 AI 기반 생명공학 시장 현황 및 전망(KBIOIS 브리프 Vol.91) / https://www.kbiois.or.kr / 원문 쪽 1"
    }
    assert analysis_source_aliases(state, [rag]) == {"M6:p1:t0": rag}
