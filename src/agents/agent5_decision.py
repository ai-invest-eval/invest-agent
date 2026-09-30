"""Agent 5 InvestmentDecision.

LLM(Judge): 영역별 6회 호출로 질문별 점수·근거·출처 번호·근거 문장을 구조화 출력한다.
코드: 출처·근거 문장 검증 → 결측 점수 교체 → 총점·결측 비중 → 관문 → 판정 → 이력 1건.
채점 기준은 docs/investment_criteria_v4.md, 형식은 docs/data_contracts.md를 따른다.
"""

import copy
import json
import re
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.agents import agent5_config as cfg
from src.agents import agent5_scoring as scoring
from src.agents.agent5_rubric import PROMPT, rubric_text
from src.schemas import EvaluationRecord, InvestmentDecision, InvestmentDecisionUpdate
from src.state import InvestmentState


# ── LLM 출력 형식 (Pydantic 검증) ──────────────────────────────
class JudgeItem(BaseModel):
    question: Literal[
        "QA",
        "QB",
        "QC",
        "QD",
        "QE",
        "QF",
        "QG",
        "QH",
        "QI",
        "QJ",
        "QK",
        "QL",
        "QM",
        "QN",
        "QO",
    ]
    score: int | None = Field(
        None, ge=1, le=5, description="기준표 1~5점. 근거 없으면 null"
    )
    reason: str = Field(
        description="점수를 정한 핵심 사실 한 문장. 결측이면 '정보 없음'"
    )
    ref_ids: list[str] = Field(
        default_factory=list, description="출처 목록 번호. 예: ['R1']"
    )
    quote: str | None = Field(
        None, description="근거 문장을 입력 자료에서 글자 그대로 복사"
    )
    missing: bool = Field(description="입력 자료에 근거가 없으면 true")


class JudgeResult(BaseModel):
    items: list[JudgeItem]


# ── 프롬프트 ─────────────────────────────────────────────────
def _as_text(value) -> str:
    if value in (None, ""):
        return "(없음)"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=1)


def _ref_line(ref_id: str, ref: dict) -> str:
    where = ref.get("url") or (
        f"p.{ref['page']}" if ref.get("page") is not None else ""
    )
    return f"[{ref_id}] {ref.get('title')} | {ref.get('issuer') or '발행처 미확인'} | {ref.get('year') or '연도 미확인'} | {where}"


def build_prompts(
    state: InvestmentState, ref_catalog: dict[str, dict]
) -> list[tuple[str, list[str], str]]:
    """영역별 (영역 키, 질문 목록, 프롬프트) 6개."""
    profile = state.get("startup_profile") or {}
    business_model = profile.get("business_model", "unknown")
    lead_market = (
        profile.get("lead_indication") or profile.get("lead_service") or "미지정"
    )
    refs = "\n".join(_ref_line(i, r) for i, r in ref_catalog.items()) or "(없음)"
    prompts = []
    for area, qs in cfg.QUESTIONS.items():
        if business_model not in ("pipeline", "platform"):
            qs = [q for q in qs if q != "QD"]  # unknown → QD는 코드가 결측 처리
        context = "\n\n".join(
            f"### {key}\n{_as_text(state.get(key))}" for key in cfg.AREA_CONTEXT[area]
        )
        prompt = PROMPT.format(
            company=state["selected_startup"]["name"],
            business_model=business_model,
            lead_market=lead_market,
            today=datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat(),
            area_name=cfg.AREA_NAMES[area],
            rubric=rubric_text(qs, business_model),
            context=context,
            references=refs,
            questions=", ".join(qs),
        )
        prompts.append((area, qs, prompt))
    return prompts


# ── LLM 호출 ─────────────────────────────────────────────────
def _get_llm():
    """import 시점이 아니라 실행 시점에 모델을 만든다 (CONTRIBUTING: import 시 API 호출 금지)."""
    from langchain_openai import ChatOpenAI

    from src.config import LLM_MODEL, LLM_TEMPERATURE

    return ChatOpenAI(
        model=LLM_MODEL, temperature=LLM_TEMPERATURE
    ).with_structured_output(JudgeResult)


def _items_of(result) -> list[dict]:
    items = result.items if isinstance(result, JudgeResult) else result["items"]
    return [it.model_dump() if hasattr(it, "model_dump") else dict(it) for it in items]


def call_judge(llm, prompts) -> dict:
    """영역별 batch 호출. 실패한 영역만 재시도하고, 그래도 실패하면 예외를 낸다.

    API 오류는 근거 부족과 다른 기술적 실패이므로 결측으로 바꾸지 않는다 (data_contracts 8장).
    """
    pending = list(prompts)
    raw: dict = {}
    for attempt in range(cfg.LLM_RETRIES + 1):
        results = llm.batch([p for _, _, p in pending], return_exceptions=True)
        failed = []
        for (area, qs, prompt), res in zip(pending, results):
            if isinstance(res, Exception) or res is None:
                failed.append(((area, qs, prompt), res))
                continue
            for item in _items_of(res):
                if item.get("question") in qs:  # 다른 영역 질문은 무시
                    raw[item["question"]] = item
        if not failed:
            return raw
        pending = [p for p, _ in failed]
    errors = "; ".join(
        f"{p[0]}: {type(e).__name__ if e else 'None'}" for p, e in failed
    )
    raise RuntimeError(
        f"Agent 5 LLM 호출 실패 (재시도 {cfg.LLM_RETRIES}회 후): {errors}"
    )


# ── 분석 글 출처 표기 연결 ───────────────────────────────────
_SOURCE_LINE = re.compile(
    r"^- \[([^\]]+)\] (.+?) / (\S+) / 원문 쪽 (.+)$", re.MULTILINE
)


def analysis_source_aliases(state: InvestmentState, refs: list[dict]) -> dict:
    """분석 글 '사용 출처' 목록의 표기(예: M6:p1:t0)를 State 출처와 연결한다.

    제목·쪽(RAG) 또는 URL(웹)이 같은 출처만 연결하고, 못 찾으면 연결하지 않는다.
    """
    aliases = {}
    for key in ("tech_analysis", "market_analysis"):
        for tag, title, url, page in _SOURCE_LINE.findall(state.get(key) or ""):
            for ref in refs:
                same_rag = (
                    ref.get("source") == "RAG"
                    and ref.get("title") == title.strip()
                    and str(ref.get("page")) == page.strip()
                )
                same_web = ref.get("source") == "web" and ref.get("url") == url
                if same_rag or same_web:
                    aliases[tag] = ref
                    break
    return aliases


# ── 판정 조립 ────────────────────────────────────────────────
def evaluate(state: InvestmentState, llm) -> InvestmentDecision:
    profile = state["startup_profile"]
    refs = scoring.collect_references(state)
    ref_catalog = {f"R{i + 1}": ref for i, ref in enumerate(refs)}
    # 3-A·3-B 분석 글은 출처를 [M6:p1:t0]처럼 표기한다. 같은 출처를 그 표기로도
    # 찾을 수 있게 목록에 추가해, LLM이 분석 글의 표기를 그대로 인용해도 연결되게 한다.
    ref_catalog.update(analysis_source_aliases(state, refs))

    raw = call_judge(llm, build_prompts(state, ref_catalog))
    evidence = scoring.finalize_evidence(
        raw, ref_catalog, scoring.build_corpus(state), profile.get("business_model")
    )
    area_scores, total, missing_weight = scoring.compute_scores(evidence)
    gate_hits, eligibility_unknown, unconfirmed = scoring.check_gates(profile)
    verdict, hold_reason = scoring.decide(
        total, area_scores, missing_weight, gate_hits, eligibility_unknown
    )

    decision: InvestmentDecision = {
        "total": total,
        "area_scores": area_scores,
        "question_scores": {q: e["score"] for q, e in evidence.items()},
        "question_evidence": evidence,
        "verdict": verdict,
        "hold_reason": hold_reason,
        "unconfirmed_gates": unconfirmed,
        "missing_weight": missing_weight,
        "rationale": scoring.make_rationale(
            verdict, hold_reason, total, area_scores, evidence, unconfirmed
        ),
    }
    scoring.validate_decision(decision)
    return decision


def build_update(state: InvestmentState, llm) -> InvestmentDecisionUpdate:
    decision = evaluate(state, llm)
    # 다음 후보 평가 때 원본이 바뀌어도 이력이 따라 바뀌지 않도록 복사해서 저장한다.
    record: EvaluationRecord = copy.deepcopy(
        {
            **decision,
            "name": state["selected_startup"]["name"],
            "startup_profile": state["startup_profile"],
            "tech_analysis": state.get("tech_analysis", ""),
            "market_analysis": state.get("market_analysis", ""),
            "competitor_analysis": state.get("competitor_analysis", ""),
        }
    )
    return {"investment_decision": decision, "evaluation_history": [record]}


def investment_decision(state: InvestmentState) -> InvestmentDecisionUpdate:
    """입력: selected_startup, startup_profile, tech_analysis, market_analysis, competitor_analysis, references.

    출력: investment_decision, evaluation_history (State 변경분만 반환).
    """
    return build_update(state, _get_llm())
