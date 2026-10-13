"""Agent 6 ReportWriter: 누적 평가 이력으로 투자 심사 보고서(Markdown·PDF)를 만든다.

역할 분담
- 코드: 정렬·순위표·점수·금액 표시·관문 상태·REFERENCE·목차 순서·쪽수 검사
- LLM: SUMMARY 투자 이유 3줄·핵심 리스크, 2장 소항목 설명 문장, 통과 0곳일 때 미달 원인 설명
- LLM 사용 불가(키 없음·API 오류) 시: 평가 이력의 근거 문장으로 같은 구조를 채운다.

목차는 설계서 8장을 따른다: SUMMARY → 1. 평가 결과 순위표 → 2. 상세 분석 → REFERENCE

Orchestrator-Workers 구조에서는 synthesizer 노드로 쓴다.
- report_writer: 초안 Markdown과 쪽수만 만든다. 최종 저장·품질 결과 블록은 finalize 노드가 담당한다.
- rebuild_markdown: 저장된 구조화 초안(report_draft)으로 LLM 호출 없이 Markdown을 다시 조립한다.
- insert_quality_block: REFERENCE 바로 앞에 품질 평가 결과 블록을 넣거나 교체한다.
"""

import html
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.config import KST, LLM_MODEL, LLM_TEMPERATURE, MAX_REPORT_PAGES
from src.schemas import EvaluationRecord, SynthesizerUpdate
from src.state import InvestmentState
from src.tools.report_format import (
    AREA_LABELS,
    AREA_QUESTIONS,
    GATE_LABELS,
    QUESTION_LABELS,
    collect_references,
    fmt_money,
    fmt_percent,
    fmt_score,
    gate_status,
    hold_line,
    is_pass,
    missing_questions,
    normalize_name,
    rank_records,
    reference_map,
    reference_section,
    reference_sort_key,
    strong_areas,
    uses_fixed_fx,
)

# 초안 단계 쪽수 목표. 과제 기준(최대 10쪽)과 같게 두고, 넘치면 문단 길이·글자 크기를 줄인다.
MAX_PAGES = MAX_REPORT_PAGES
# 통과 기업이 없을 때 상세 검토(3장)를 쓸 상위 후보 수
HELD_DETAIL_COUNT = int(os.getenv("REPORT_HELD_DETAIL_COUNT", "2"))
# 쪽수가 넘칠 때 단계별로 줄이는 LLM 문단 최대 글자 수
SECTION_CHAR_LIMITS = [650, 480, 340, 230]
SECTION_KEYS = ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7"]
# 소항목별 제목·사용 질문·사용 분석 글. LLM에는 소항목별 데이터만 나눠서 준다.
SECTION_SPEC = {
    "2.1": ("기업 개요와 사업 아이디어", [], []),
    "2.2": ("기술력과 AI 검증", ["QG", "QH"], ["tech_analysis"]),
    "2.3": ("시장 규모와 성장성", ["QD", "QE", "QF"], ["market_analysis"]),
    "2.4": ("경쟁 구도와 차별성", ["QI", "QJ"], ["competitor_analysis"]),
    "2.5": ("팀 구성", ["QA", "QB", "QC"], []),
    "2.6": ("실적과 투자 조건", ["QK", "QL", "QM", "QN", "QO"], []),
    "2.7": (
        "사업 리스크와 한계점",
        [],
        ["tech_analysis", "market_analysis", "competitor_analysis"],
    ),
}
# 투자 이유의 영역 → 본문 소항목 (LLM이 아닌 코드가 연결)
AREA_SECTION = {
    "founder": "2.5",
    "market": "2.3",
    "product": "2.2",
    "moat": "2.4",
    "traction": "2.6",
    "deal": "2.6",
}
JUDGE_PASS = 4  # 충실성·관련성 모두 4점 이상이면 통과
# 품질 평가 노드(quality_eval)의 지적을 다음 초안에 반영하는 지시문
REWRITE_WITH_FEEDBACK = """이전 보고서가 품질 평가에서 아래 지적을 받았다.
{eval_feedback}

지적된 부분만 고쳐라. 지적되지 않은 문장, 점수, 순위, 판정, 표는 바꾸지 않는다.
- groundedness 지적: 근거와 다른 문장은 입력 근거에 맞게 고치고, 근거가 없으면 삭제한다.
- neutrality 지적: 과장·우열 표현을 사실 서술로 바꾼다.
- bias 지적: 입력에 있는 리스크·결측 정보를 해당 문단에 한 문장 추가한다.
- 쪽수 초과 지적: 각 문단을 짧게 줄인다. 표와 수치는 유지한다.
- 입력에 없는 사실·수치·출처를 새로 만들지 않는다."""
# 품질 결과 블록 위치 표시 (화면에는 보이지 않음). 같은 블록을 두 번 넣지 않고 교체하는 데 쓴다.
QUALITY_BLOCK_START = "<!-- quality-block:start -->"
QUALITY_BLOCK_END = "<!-- quality-block:end -->"
# SUMMARY에 들어가면 안 되는 개요·서론 표현 (교수님 감점 요소)
INTRO_PATTERNS = re.compile(
    r"본\s*보고서|이\s*보고서|본\s*문서|이\s*문서|본\s*평가는|목적으로\s*(작성|한다)|"
    r"개요|배경|서론|살펴보(고자|겠)"
)
LIMITATION_TEXT = (
    "전문경영인 승계(QB), 특허 권리 범위(QJ), 동일 조건 비교기업 밸류에이션(QN), "
    "투자 계약의 권리·희석 조건(QO)은 공개 정보로 확인하기 어려워 대리 지표를 썼다."
)


# ============================================================ LLM 출력 형식


class Reason(BaseModel):
    text: str = Field(
        description="투자 이유 한 문장 (이 회사의 사실·점수 포함, 40~80자)"
    )
    area: Literal["founder", "market", "product", "moat", "traction", "deal"] = Field(
        description="이 이유의 근거가 속한 평가 영역"
    )


class DetailDraft(BaseModel):
    reasons: list[Reason] = Field(description="투자 이유 정확히 3개")
    key_risk: str = Field(description="가장 중요한 리스크 한 문장")
    s2_1: str = Field(
        description="sections['2.1'] 데이터만 사용: 기업 개요와 사업 아이디어"
    )
    s2_2: str = Field(description="sections['2.2'] 데이터만 사용: 기술력과 AI 검증")
    s2_3: str = Field(description="sections['2.3'] 데이터만 사용: 시장 규모와 성장성")
    s2_4: str = Field(description="sections['2.4'] 데이터만 사용: 경쟁 구도와 차별성")
    s2_5: str = Field(description="sections['2.5'] 데이터만 사용: 팀 구성")
    s2_6: str = Field(description="sections['2.6'] 데이터만 사용: 실적과 투자 조건")
    s2_7: str = Field(description="sections['2.7'] 데이터만 사용: 사업 리스크와 한계점")

    def section_text(self, key: str) -> str:
        return getattr(self, "s" + key.replace(".", "_"))


class SectionGrade(BaseModel):
    """LLM-as-a-Judge 채점 (Form-filling)."""

    section: Literal["summary", "2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7"]
    faithfulness: int = Field(
        ge=1, le=5, description="충실성: 모든 사실·수치가 데이터에 있는가"
    )
    relevance: int = Field(
        ge=1, le=5, description="관련성: 소항목 주제에 맞는 내용만 있는가"
    )
    issues: str = Field(description="감점 이유. 문제가 없으면 빈 문자열")


class JudgeResult(BaseModel):
    grades: list[SectionGrade] = Field(
        description="summary와 2.1~2.7 각각 1개씩, 총 8개"
    )


class NoPassDraft(BaseModel):
    summary_reasons: list[str] = Field(description="투자 추천이 없는 핵심 이유 2~3문장")
    top_gap: str = Field(description="최고점 후보가 기준에 못 미친 영역과 근거")
    recheck: str = Field(description="어떤 정보가 확보되면 다시 평가할지")


class HeldSections(BaseModel):
    """통과 0곳 보고서의 상위 후보 상세 검토 문장. 투자 추천이 아니라 보류 사유를 설명한다."""

    s2_1: str = Field(description="sections['2.1'] 데이터만 사용: 기업 개요와 사업 아이디어")
    s2_2: str = Field(description="sections['2.2'] 데이터만 사용: 기술력과 AI 검증")
    s2_3: str = Field(description="sections['2.3'] 데이터만 사용: 시장 규모와 성장성")
    s2_4: str = Field(description="sections['2.4'] 데이터만 사용: 경쟁 구도와 차별성")
    s2_5: str = Field(description="sections['2.5'] 데이터만 사용: 팀 구성")
    s2_6: str = Field(description="sections['2.6'] 데이터만 사용: 실적과 투자 조건")
    s2_7: str = Field(description="sections['2.7'] 데이터만 사용: 보류 사유·리스크와 한계점")


class HeldDetail(HeldSections):
    company: str


class NoPassReportDraft(NoPassDraft):
    """report_draft.payload 형식. LLM 호출 스키마(NoPassDraft·HeldSections)와 분리한다.

    details가 없는 예전 초안도 그대로 읽힌다(기본값 빈 목록).
    """

    details: list[HeldDetail] = Field(default_factory=list)


SYSTEM_PROMPT = """너는 벤처캐피털 투자 심사역이다. 주어진 평가 데이터만 근거로 투자 심사 보고서 문장을 한국어로 쓴다.
규칙:
1. 주어진 데이터에 없는 사실·수치·기업·출처를 만들지 않는다. 데이터가 없으면 "정보 부족"이라고 쓴다.
2. "본 보고서는", "이 문서는", 개요·배경·서론 문장을 쓰지 않는다. 결론과 근거부터 쓴다.
3. 점수는 주어진 값을 그대로 인용한다. 점수를 다시 매기거나 판정을 바꾸지 않는다.
4. missing=true인 질문은 "정보 부족"으로 표현하고 추정하지 않는다.
5. 문장은 "~다"체로 쓴다. 각 소항목은 3~5문장, {limit}자 이내로 쓰고 수치와 근거를 구체적으로 담는다.
6. 관문 값이 null이면 "미확인"이라고 쓴다. 미확인을 "문제 없음"으로 해석하지 않는다.
7. 각 소항목은 sections의 해당 키 데이터만 사용한다. 다른 소항목의 주제를 섞지 않는다.
8. 업계 평균·문헌 수치(예: AI 발굴 물질의 평균 임상 성공률)는 "업계 기준"으로 구분해 쓰고 이 회사의 성과처럼 쓰지 않는다.
9. 점수는 보고서에 코드로 따로 표시된다. "~점을 부여받았다", "높은 점수의 근거가 된다" 같은 점수 설명 문장을 쓰지 말고 사실과 그 의미를 쓴다.
10. 투자 이유는 각각 한 문장, 80자 이내로 쓴다."""

JUDGE_PROMPT = """You are an expert evaluator of investment reports. 한국어로 답한다.
Task: 보고서 초안의 각 부분(summary, 2.1~2.7)을 평가 데이터와 비교해 채점한다.
Criteria:
- Faithfulness (1~5): 모든 사실·수치가 해당 소항목 데이터(sections[키])에 있는가. 데이터에 없는 내용, 과장, 업계 평균 수치를 회사 성과처럼 쓴 경우 감점. summary는 전체 데이터 기준.
- Relevance (1~5): 소항목 제목의 주제에 맞는 내용만 있는가. 다른 소항목 주제가 섞이면 감점.
- 추가 감점: 점수·영역명을 데이터와 다르게 인용, 데이터 근거 없는 평가 표현("뛰어나다", "명확하다"), 관문 미확인을 언급하지 않은 2.7.
Steps:
1. 소항목 제목과 데이터를 읽는다.
2. 초안 문장마다 데이터에 근거가 있는지 확인한다.
3. 점수와 감점 이유(issues)를 채운다. 관대하게 채점하지 않는다."""


# ============================================================ 공통 도우미


def _log(message: str) -> None:
    print(f"[agent6] {message}", file=sys.stderr)


def _trim(text: str, limit: int) -> str:
    """문장 단위로 잘라 limit 글자 이내로 맞춘다."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[.다])\s+", text)
    out = ""
    for sentence in sentences:
        if len(out) + len(sentence) + 1 > limit:
            break
        out = f"{out} {sentence}".strip()
    return out or text[:limit].rstrip() + "…"


def _remove_intro(text: str) -> str:
    sentences = re.split(r"(?<=[.다])\s+", text.strip())
    kept = [s for s in sentences if not INTRO_PATTERNS.search(s)]
    return " ".join(kept)


def _llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY")) and os.getenv("REPORT_USE_LLM", "1") != "0"


def _call_llm(
    schema: type[BaseModel],
    payload: dict,
    task: str,
    limit: int,
    system: str | None = None,
):
    """구조화 출력으로 LLM 호출. 실패하면 None을 돌려주고 호출부가 대체 문장을 쓴다."""
    if not _llm_available():
        return None
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=LLM_MODEL, temperature=LLM_TEMPERATURE, timeout=60, max_retries=1
        )
        messages = [
            ("system", system or SYSTEM_PROMPT.format(limit=limit)),
            (
                "human",
                f"{task}\n\n평가 데이터(JSON):\n{json.dumps(payload, ensure_ascii=False)}",
            ),
        ]
        return llm.with_structured_output(schema).invoke(messages)
    except Exception as exc:  # noqa: BLE001 — API·파싱 오류 모두 대체 문장으로 전환
        # API 오류는 근거 부족과 구분해 로그에 남긴다.
        _log(f"LLM 호출 실패 → 평가 근거 문장으로 대체: {type(exc).__name__}: {exc}")
        return None


def _llm_payload(record: EvaluationRecord, analysis_chars: int = 2500) -> dict:
    """LLM에 넘길 데이터. 1위 기업의 평가 이력 한 건만 사용한다."""
    profile = record.get("startup_profile") or {}
    keep = [
        "name",
        "founded_year",
        "platform",
        "business_model",
        "business_model_basis",
        "lead_indication",
        "lead_service",
        "pipeline",
        "founder_degree_career",
        "ceo_full_time",
        "gates",
        "missing_fields",
    ]
    evidence = {
        q: {
            "label": QUESTION_LABELS[q],
            "score": e.get("score"),
            "missing": e.get("missing"),
            "rationale": e.get("rationale"),
        }
        for q, e in (record.get("question_evidence") or {}).items()
    }
    return {
        "company": record["name"],
        "verdict": record["verdict"],
        "total": round(record["total"], 1),
        "area_scores": {
            AREA_LABELS[k]: round(v, 1) for k, v in record["area_scores"].items()
        },
        "missing_weight": record["missing_weight"],
        "unconfirmed_gates": record.get("unconfirmed_gates", []),
        "profile": {k: profile.get(k) for k in keep},
        "question_evidence": evidence,
        "tech_analysis": (record.get("tech_analysis") or "")[:analysis_chars],
        "market_analysis": (record.get("market_analysis") or "")[:analysis_chars],
        "competitor_analysis": (record.get("competitor_analysis") or "")[
            :analysis_chars
        ],
    }


def _section_inputs(record: EvaluationRecord, analysis_chars: int = 2000) -> dict:
    """소항목별로 쓸 수 있는 데이터만 나눈다 (내용 섞임 방지)."""
    base = _llm_payload(record, analysis_chars)
    evidence = base["question_evidence"]
    sections = {}
    for key, (title, questions, analyses) in SECTION_SPEC.items():
        data = {"title": title}
        if questions:
            data["questions"] = {q: evidence.get(q) for q in questions}
        for name in analyses:
            data[name] = base[name]
        sections[key] = data
    sections["2.1"]["profile"] = base["profile"]
    sections["2.7"].update(
        {
            "gates": base["profile"].get("gates"),
            "unconfirmed_gates": base["unconfirmed_gates"],
            "missing_questions": [q for q, e in evidence.items() if e.get("missing")],
            "missing_weight": base["missing_weight"],
        }
    )
    return {
        "company": base["company"],
        "total": base["total"],
        "area_scores": base["area_scores"],
        "sections": sections,
    }


def _judge(draft: DetailDraft, inputs: dict) -> dict[str, SectionGrade] | None:
    """LLM-as-a-Judge: 소항목별 충실성·관련성 채점."""
    answer = {
        "summary": {
            "reasons": [f"[{r.area}] {r.text}" for r in draft.reasons],
            "key_risk": draft.key_risk,
        },
        **{key: draft.section_text(key) for key in SECTION_KEYS},
    }
    result = _call_llm(
        JudgeResult,
        {"data": inputs, "draft": answer},
        "평가 데이터(data)와 보고서 초안(draft)을 비교해 summary와 2.1~2.7을 각각 채점하라.",
        0,
        system=JUDGE_PROMPT,
    )
    if result is None:
        return None
    return {g.section: g for g in result.grades}


def _failed(grades: dict[str, SectionGrade]) -> list[str]:
    return [
        key
        for key in ["summary", *SECTION_KEYS]
        if key in grades
        and min(grades[key].faithfulness, grades[key].relevance) < JUDGE_PASS
    ]


def _swap(draft: DetailDraft, keys: list[str], source: DetailDraft) -> DetailDraft:
    """draft의 keys 부분(summary 또는 2.x)만 source 내용으로 바꾼다."""
    merged = draft.model_dump()
    for key in keys:
        if key == "summary":
            merged["reasons"] = source.model_dump()["reasons"]
            merged["key_risk"] = source.key_risk
        else:
            field = "s" + key.replace(".", "_")
            merged[field] = getattr(source, field)
    return DetailDraft(**merged)


def _round_log(
    round_no: int, grades: dict[str, SectionGrade], failed: list[str]
) -> dict:
    return {
        "round": round_no,
        "grades": {k: g.model_dump() for k, g in grades.items()},
        "failed": failed,
    }


def _feedback_task(feedback: list[str] | None) -> str:
    """품질 평가 지적을 LLM 작업 지시에 덧붙일 문장. 지적이 없으면 빈 문자열."""
    if not feedback:
        return ""
    lines = "\n".join(f"- {item}" for item in feedback)
    return "\n\n" + REWRITE_WITH_FEEDBACK.format(eval_feedback=lines)


def _internal_judge_on() -> bool:
    """품질 루프는 그래프의 quality_eval 노드가 담당하므로 기본값은 끈다(REPORT_INTERNAL_JUDGE=0)."""
    return os.getenv("REPORT_INTERNAL_JUDGE", "0") != "0"


def _write_detail(
    record: EvaluationRecord, feedback: list[str] | None = None
) -> tuple[DetailDraft, dict]:
    """초안 작성 → (내장 Judge가 켜져 있으면) 채점 → 미달 부분만 1회 재작성 → 그래도 미달이면 근거 문장으로 대체.

    feedback: 품질 평가 노드가 직전 보고서에 남긴 지적. 있으면 초안 작성부터 반영한다.
    """
    fallback = _fallback_detail(record)
    inputs = _section_inputs(record)
    task = (
        "투자 추천 기업의 SUMMARY 투자 이유 3개(각각 근거 영역 area 지정), 핵심 리스크 1문장, "
        "2.1~2.7 소항목을 작성하라. 소항목마다 sections의 해당 키 데이터만 쓴다."
    ) + _feedback_task(feedback)
    draft = _call_llm(DetailDraft, inputs, task, SECTION_CHAR_LIMITS[0])
    log: dict = {"llm": draft is not None, "rounds": []}
    if draft is None:
        return fallback, log
    if not _internal_judge_on():
        return draft, log

    # 1차 채점
    grades = _judge(draft, inputs)
    if grades is None:  # Judge 호출 자체가 실패: 채점 불가를 기록하고 초안을 쓴다
        log["rounds"].append({"round": 1, "judge": "failed"})
        return draft, log
    failed = _failed(grades)
    log["rounds"].append(_round_log(1, grades, failed))
    if not failed:
        return draft, log

    # 미달 부분만 감점 이유를 붙여 1회 재작성
    retry = _call_llm(
        DetailDraft,
        {**inputs, "judge_feedback": {k: grades[k].issues for k in failed}},
        task + " judge_feedback에 적힌 문제를 반드시 고쳐라.",
        SECTION_CHAR_LIMITS[0],
    )
    if retry is None:  # 재작성 실패: 탈락한 문단을 그대로 두지 않고 근거 문장으로 대체
        log["replaced"] = failed
        return _swap(draft, failed, fallback), log
    draft = _swap(draft, failed, retry)

    # 2차 채점: 재작성한 부분만 다시 확인
    grades = _judge(draft, inputs)
    if grades is None:  # 재작성본을 검증할 수 없음 → 검증 안 된 문단은 대체
        log["rounds"].append({"round": 2, "judge": "failed"})
        log["replaced"] = failed
        return _swap(draft, failed, fallback), log
    still = [k for k in _failed(grades) if k in failed]
    log["rounds"].append(_round_log(2, grades, still))
    if still:  # 재작성 후에도 미달 → 근거 문장으로 대체 (사실 생성 방지)
        log["replaced"] = still
        draft = _swap(draft, still, fallback)
    return draft, log


def _held_inputs(record: EvaluationRecord) -> dict:
    """상세 검토 LLM 입력. 통과 0곳 보고서 계약대로 영역·질문 점수는 빼고 근거만 준다."""
    inputs = _section_inputs(record)
    inputs.pop("area_scores", None)
    inputs.pop("total", None)
    for data in inputs["sections"].values():
        for item in (data.get("questions") or {}).values():
            if isinstance(item, dict):
                item.pop("score", None)
    inputs["hold_detail"] = hold_line(record)
    return inputs


def _write_held_detail(
    record: EvaluationRecord, feedback: list[str] | None = None
) -> HeldDetail:
    """보류된 상위 후보 1곳의 2.1~2.7 검토 문장. LLM 실패 시 근거 문장으로 채운다(사실 생성 없음)."""
    task = (
        "이 기업은 투자 기준에 미달해 보류된 후보다. 투자를 추천하거나 긍정적 결론을 내리지 않는다. "
        "2.1~2.7 소항목을 작성하라. 소항목마다 sections의 해당 키 데이터만 쓰고, "
        "확인된 사실과 정보 부족을 구분한다. 2.7에는 hold_detail의 보류 사유와 미확인 관문·정보 부족을 쓴다."
    ) + _feedback_task(feedback)
    draft = _call_llm(HeldSections, _held_inputs(record), task, SECTION_CHAR_LIMITS[0])
    if draft is None:
        fallback = _fallback_detail(record)
        draft = HeldSections(
            **{k: getattr(fallback, k) for k in HeldSections.model_fields}
        )
        draft.s2_7 = f"보류 사유: {hold_line(record)}."
    return HeldDetail(company=record["name"], **draft.model_dump())


def _evidence_text(record: EvaluationRecord, questions: list[str]) -> str:
    """LLM 대체용: 질문별 근거 문장을 이어 붙인다."""
    evidence = record.get("question_evidence") or {}
    parts = []
    for q in questions:
        e = evidence.get(q) or {}
        if e.get("missing"):
            parts.append(f"{QUESTION_LABELS[q]}은 정보 부족이다.")
        elif e.get("rationale"):
            parts.append(e["rationale"].rstrip(".") + ".")
    return " ".join(parts)


def _fallback_detail(record: EvaluationRecord) -> DetailDraft:
    """LLM 없이 평가 이력의 근거 문장으로 같은 구조를 채운다 (사실 생성 없음)."""
    areas = record["area_scores"]
    top = sorted(
        ["founder", "market", "product", "moat", "traction"], key=lambda k: -areas[k]
    )[:3]
    reasons = []
    for key in top:
        first = _evidence_text(record, AREA_QUESTIONS[key]).split(". ")[0].rstrip(".")
        reasons.append(
            Reason(
                text=f"{AREA_LABELS[key]} {fmt_score(areas[key])}점: {first}.", area=key
            )
        )
    profile = record.get("startup_profile") or {}
    unconfirmed = record.get("unconfirmed_gates") or []
    risk = (
        f"리스크 관문 {len(unconfirmed)}개가 미확인 상태다."
        if unconfirmed
        else f"결측 비중 {fmt_percent(record['missing_weight'])} 항목의 추가 확인이 필요하다."
    )
    return DetailDraft(
        reasons=reasons,
        key_risk=risk,
        s2_1=f"{profile.get('platform') or '플랫폼 정보 부족'}. "
        + ((profile.get("business_model_basis") or {}).get("reason") or ""),
        s2_2=_evidence_text(record, ["QG", "QH"])
        + " "
        + (record.get("tech_analysis") or ""),
        s2_3=_evidence_text(record, ["QD", "QE", "QF"])
        + " "
        + (record.get("market_analysis") or ""),
        s2_4=_evidence_text(record, ["QI", "QJ"])
        + " "
        + (record.get("competitor_analysis") or ""),
        s2_5=_evidence_text(record, ["QA", "QB", "QC"]),
        s2_6=_evidence_text(record, ["QK", "QL", "QM", "QN", "QO"]),
        s2_7=risk,
    )


# ============================================================ 본문 조각 (코드)


def _score_line(record: EvaluationRecord, area: str) -> str:
    evidence = record.get("question_evidence") or {}
    parts = []
    for q in AREA_QUESTIONS[area]:
        e = evidence.get(q) or {}
        tag = " (정보 부족)" if e.get("missing") else ""
        parts.append(f"{q} {QUESTION_LABELS[q]} {e.get('score', '–')}점{tag}")
    return (
        f"**{AREA_LABELS[area]} {fmt_score(record['area_scores'][area])}점** · "
        + " · ".join(parts)
    )


def _ranking_table(ranked, recommended_name: str | None) -> str:
    show_areas = any(is_pass(r) for _, _, r in ranked)
    labels = list(AREA_LABELS.values()) if show_areas else []
    head = "| 순위 | 기업 | 총점 | 판정 | " + "".join(f"{x} | " for x in labels)
    sep = "|" + "---|" * (4 + len(labels))
    rows = [head, sep]
    for rank, tie, record in ranked:
        if is_pass(record):
            verdict = (
                "투자 추천" if record["name"] == recommended_name else "투자 검토 가능"
            )
            areas = [fmt_score(record["area_scores"][k]) for k in AREA_LABELS]
        else:
            verdict = "보류"
            areas = ["–"] * len(AREA_LABELS)
        rank_text = f"{rank} (동점)" if tie else str(rank)
        cells = "".join(f"{a} | " for a in areas) if show_areas else ""
        rows.append(
            f"| {rank_text} | {record['name']} | {fmt_score(record['total'])} | {verdict} | {cells}"
        )
    return "\n".join(rows)


def _verdict_lines(ranked, recommended_name: str | None) -> str:
    lines = []
    for _, _, record in ranked:
        if is_pass(record):
            label = (
                "투자 추천" if record["name"] == recommended_name else "투자 검토 가능"
            )
            detail = (
                "상세 분석은 2장"
                if label == "투자 추천"
                else "강점 " + ", ".join(strong_areas(record))
            )
            lines.append(
                f"- **{record['name']}** ({label}): 총점 {fmt_score(record['total'])}점, {detail}"
            )
        else:
            lines.append(f"- **{record['name']}** (보류): {hold_line(record)}")
    return "\n".join(lines)


def _hold_category(record: EvaluationRecord) -> str:
    reason = record.get("hold_reason") or "보류"
    return "관문" if reason.startswith("관문") else reason


def _result_counts(records: list[EvaluationRecord]) -> str:
    passed = [r for r in records if is_pass(r)]
    held = [r for r in records if not is_pass(r)]
    text = f"후보 {len(records)}곳 평가 · 통과 {len(passed)}곳 · 보류 {len(held)}곳"
    if held:
        counts = Counter(_hold_category(r) for r in held)
        text += " (" + ", ".join(f"{k} {v}" for k, v in counts.items()) + ")"
    return text


def _overview(records, keyword: str) -> str:
    return (
        f"- 대상: {keyword} 중 자격 검증(비상장, Seed~Series C, Exit 전, 대기업 자회사 제외)을 통과한 후보 {len(records)}곳\n"
        "- 기준: 투자평가기준 v4 — 6개 영역(창업자 30%, 시장성 25%, 제품·기술력 15%, 경쟁우위·실적·투자조건 각 10%) × 15개 질문, "
        "관문 확인 후 **총점 75점 이상 + 창업자 60점 이상이면 통과**, 결측 비중 30% 이상이면 근거 부족 보류\n"
        "- 순위: 총점 → 창업자 → 시장성 점수 순 (코드 정렬)"
    )


def _facts_2_1(record: EvaluationRecord) -> str:
    p = record.get("startup_profile") or {}
    model = {"pipeline": "자체 신약형", "platform": "플랫폼형"}.get(
        p.get("business_model"), "사업 모델 미확인으로 정보 부족"
    )
    pipeline = p.get("pipeline")
    if pipeline is None:
        pipe_text = "정보 부족"
    elif not pipeline:
        pipe_text = "자체 파이프라인 없음 (확인)"
    else:
        pipe_text = ", ".join(
            f"{i.get('indication') or '적응증 정보 부족'}({i.get('stage') or '단계 정보 부족'})"
            for i in pipeline[:4]
        )
    market = p.get("lead_indication") or p.get("lead_service") or "정보 부족"
    founded = p.get("founded_year") or "정보 부족"
    return (
        f"- 설립 {founded} · 사업 모델 {model} · 대표 시장 {market}\n"
        f"- 파이프라인: {pipe_text}"
    )


def _facts_2_6(record: EvaluationRecord) -> str:
    p = record.get("startup_profile") or {}
    upfront, valuation = p.get("upfront_payment"), p.get("pre_money_valuation")
    basis = p.get("upfront_payment_basis") or {}
    partner = (
        f" ({basis.get('partner')}, {basis.get('date') or '일자 정보 부족'})"
        if basis.get("partner")
        else ""
    )
    text = (
        f"- 대표 선급금: {fmt_money(upfront)}{partner} · "
        f"기업가치(pre-money): {fmt_money(valuation)} ({p.get('valuation_date') or '기준일 정보 부족'})"
    )
    if uses_fixed_fx([upfront, valuation]):
        text += "\n- 환산 기준: 투자평가기준 v4 고정 가정 1 USD = 1,400 KRW (최신 환율 아님)"
    return text


def _facts_2_7(record: EvaluationRecord) -> str:
    status = gate_status(record)
    unknown = [label for label, s in status if s == "미확인"]
    hit = [label for label, s in status if s == "해당"]
    gate_text = "모두 해당 없음" if not unknown and not hit else ""
    if hit:
        gate_text += "해당: " + ", ".join(hit) + " "
    if unknown:
        gate_text += "미확인: " + ", ".join(unknown)
    missing = missing_questions(record)
    missing_text = (
        ", ".join(f"{q} {QUESTION_LABELS[q]}" for q in missing)
        + f" (결측 비중 {fmt_percent(record['missing_weight'])})"
        if missing
        else "없음"
    )
    lines = [f"- 관문 확인: {gate_text.strip()}", f"- 정보 부족 질문: {missing_text}"]
    if (record.get("startup_profile") or {}).get("business_model") == "unknown":
        lines.append("- 사업 모델 미확인으로 정보 부족 (QD 결측 처리)")
    return "\n".join(lines)


# ============================================================ 보고서 조립


def _header(records, keyword: str) -> str:
    return f'# AI 신약개발 스타트업 투자 심사 보고서\n\n<p class="meta">작성일 {datetime.now(KST):%Y-%m-%d} · 탐색 키워드 "{keyword}" · 평가 후보 {len(records)}곳</p>'


def _build_pass_report(
    records,
    ranked,
    recommended,
    draft: DetailDraft,
    refs,
    limit: int,
    keyword: str,
    order: dict[str, int] | None = None,
) -> str:
    name = recommended["name"]
    reasons = "\n".join(
        f"{i}. {_trim(_remove_intro(r.text), 90)} (→ {AREA_SECTION[r.area]})"
        for i, r in enumerate(draft.reasons[:3], 1)
    )
    sections = {
        "2.1": ("기업 개요와 사업 아이디어", _facts_2_1(recommended), draft.s2_1),
        "2.2": ("기술력과 AI 검증", _score_line(recommended, "product"), draft.s2_2),
        "2.3": ("시장 규모와 성장성", _score_line(recommended, "market"), draft.s2_3),
        "2.4": ("경쟁 구도와 차별성", _score_line(recommended, "moat"), draft.s2_4),
        "2.5": ("팀 구성", _score_line(recommended, "founder"), draft.s2_5),
        "2.6": (
            "실적과 투자 조건",
            _score_line(recommended, "traction")
            + "  \n"
            + _score_line(recommended, "deal")
            + "\n\n"
            + _facts_2_6(recommended),
            draft.s2_6,
        ),
        "2.7": ("사업 리스크와 한계점", _facts_2_7(recommended), draft.s2_7),
    }
    body = []
    for key in SECTION_KEYS:
        title, facts, prose = sections[key]
        body.append(
            f"### {key} {title}\n\n{facts}\n\n{_trim(_remove_intro(prose), limit)}"
        )
    body[-1] += f'\n\n<p class="note">한계: {LIMITATION_TEXT}</p>'

    return "\n\n".join(
        [
            _header(records, keyword),
            "## SUMMARY",
            (
                f"**결론: 투자 추천 — {name}** (총점 {fmt_score(recommended['total'])}점, "
                f"창업자 {fmt_score(recommended['area_scores']['founder'])}점, 통과)"
            ),
            f"**투자 이유**\n\n{reasons}",
            f"**평가 결과**: {_result_counts(records)} (→ 1장)",
            f"**핵심 리스크**: {_trim(_remove_intro(draft.key_risk), 120)} (→ 2.7)",
            "## 1. 평가 결과 순위표",
            "### 1.1 평가 개요\n\n" + _overview(records, keyword),
            "### 1.2 후보별 점수표\n\n"
            + _ranking_table(ranked, name)
            + '\n\n<p class="note">영역별 점수는 통과 기업만 표시한다. 점수는 소수 첫째 자리까지 표시하며 순위는 반올림 전 값으로 정했다.</p>',
            "### 1.3 판정 사유\n\n" + _verdict_lines(ranked, name),
            f"## 2. 투자 추천 기업 상세 분석: {name}",
            *body,
            "## REFERENCE",
            reference_section(refs, order),
        ]
    )


def _gap_facts(record: EvaluationRecord) -> str:
    """통과 0곳 보고서용 미달 사실. 영역별 점수는 표시하지 않는다(통과 기업만 표시 계약)."""
    missing = missing_questions(record)
    unconfirmed = [GATE_LABELS[g] for g in record.get("unconfirmed_gates") or []]
    lines = [
        f"- 판정: 보류 — {hold_line(record)}",
        "- 정보 부족 질문: "
        + (", ".join(f"{q} {QUESTION_LABELS[q]}" for q in missing) or "없음"),
        "- 미확인 리스크 관문: " + (", ".join(unconfirmed) or "없음"),
    ]
    return "\n".join(lines)


def _no_pass_payload(record: EvaluationRecord) -> dict:
    """통과 0곳 LLM 입력. 영역·질문 점수를 넣지 않아 문장에도 점수가 나오지 않게 한다."""
    evidence = record.get("question_evidence") or {}
    return {
        "company": record["name"],
        "hold_detail": hold_line(record),
        "missing_questions": [QUESTION_LABELS[q] for q in missing_questions(record)],
        "unconfirmed_gates": [
            GATE_LABELS[g] for g in record.get("unconfirmed_gates") or []
        ],
        "evidence": {
            QUESTION_LABELS[q]: e.get("rationale")
            for q, e in evidence.items()
            if not e.get("missing")
        },
    }


HELD_SECTION_TITLES = {
    "2.1": "기업 개요와 사업 아이디어",
    "2.2": "기술력과 AI 검증",
    "2.3": "시장 규모와 성장성",
    "2.4": "경쟁 구도와 차별성",
    "2.5": "팀 구성",
    "2.6": "실적과 투자 조건",
    "2.7": "보류 사유와 리스크",
}


def _held_detail_chapter(records, details: list[HeldDetail], limit: int) -> list[str]:
    """3장 상위 후보 상세 검토. 사실 줄은 코드가, 문단은 LLM이 쓴다. 영역별 점수는 표시하지 않는다."""
    if not details:
        return []
    by_name = {normalize_name(r["name"]): r for r in records}
    parts = [
        "## 3. 상위 후보 상세 검토 (보류)",
        '<p class="note">투자 추천이 아니다. 점수가 높았던 보류 후보가 어떤 근거로 기준에 미달했는지 설명한다.</p>',
    ]
    for i, detail in enumerate(details, 1):
        record = by_name.get(normalize_name(detail.company))
        if record is None:
            continue
        facts = {
            "2.1": _facts_2_1(record),
            "2.6": _facts_2_6(record),
            "2.7": _facts_2_7(record),
        }
        parts.append(
            f"### 3.{i} {record['name']} — 총점 {fmt_score(record['total'])}점, 보류\n\n"
            f"- 판정: 보류 — {hold_line(record)}"
        )
        for j, key in enumerate(SECTION_KEYS, 1):
            prose = _trim(_remove_intro(getattr(detail, "s" + key.replace(".", "_"))), limit)
            fact = facts.get(key)
            body = f"{fact}\n\n{prose}" if fact else prose
            parts.append(f"#### 3.{i}.{j} {HELD_SECTION_TITLES[key]}\n\n{body}")
    return parts


def _build_no_pass_report(
    records,
    ranked,
    draft: NoPassDraft,
    refs,
    limit: int,
    keyword: str,
    order: dict[str, int] | None = None,
) -> str:
    top = ranked[0][2]
    counts = Counter(_hold_category(r) for r in records)
    dist = "| 보류 사유 | 기업 수 | 기업 |\n|---|---|---|\n" + "\n".join(
        f"| {k} | {v} | {', '.join(r['name'] for r in records if _hold_category(r) == k)} |"
        for k, v in counts.items()
    )
    reasons = "\n".join(
        f"- {_trim(_remove_intro(t), 150)}" for t in draft.summary_reasons[:3]
    )
    return "\n\n".join(
        [
            _header(records, keyword),
            "## SUMMARY",
            f"**결론: 투자 추천 없음** — 평가한 {len(records)}곳 모두 투자 기준(총점 75점 + 창업자 60점, 관문·근거 충족)에 미달했다.",
            f"**주요 보류 사유** (→ 2.1)\n\n{reasons}",
            f"**최고점 후보**: {top['name']} {fmt_score(top['total'])}점 — {hold_line(top)} (→ 2.2)",
            f"**평가 결과**: {_result_counts(records)} (→ 1장)",
            "## 1. 평가 결과 순위표",
            "### 1.1 평가 개요\n\n" + _overview(records, keyword),
            "### 1.2 후보별 점수표\n\n"
            + _ranking_table(ranked, None)
            + '\n\n<p class="note">통과 기업이 없어 영역별 점수는 표시하지 않는다. 순위는 반올림 전 값으로 정했다.</p>',
            "### 1.3 판정 사유\n\n" + _verdict_lines(ranked, None),
            "## 2. 투자 추천 없음 사유",
            "### 2.1 보류 사유 분포\n\n" + dist,
            f"### 2.2 최고점 후보의 미달 원인: {top['name']}\n\n"
            + _gap_facts(top)
            + "\n\n"
            + _trim(_remove_intro(draft.top_gap), limit),
            "### 2.3 재검토 조건\n\n" + _trim(_remove_intro(draft.recheck), limit),
            *_held_detail_chapter(records, getattr(draft, "details", []), limit),
            "## REFERENCE",
            reference_section(refs, order),
        ]
    )


def _build_empty_report(state: InvestmentState, keyword: str) -> str:
    discovery = [
        r for r in state.get("references") or [] if r.get("agent") == "discovery"
    ]
    refs = [{**r, "cited_pages": []} for r in discovery]
    excluded = _excluded(state)
    reason = (
        f"자격 검증을 통과한 후보 {len(excluded)}곳이 모두 평가 중 실패해 제외되어 "
        if excluded
        else "자격 검증(비상장, Seed~Series C, Exit 전, 대기업 자회사 제외)을 통과한 후보가 없어 "
    )
    return "\n\n".join(
        [
            _header([], keyword),
            "## SUMMARY",
            "**결론: 투자 추천 없음 — 평가 대상 후보 0곳**",
            reason
            + f"채점과 순위표를 만들지 않았다. 탐색 과정에서 확인한 출처는 {len(discovery)}건이다.",
            "## 1. 평가 결과 순위표\n\n평가 대상 없음.",
            "## REFERENCE",
            reference_section(refs, _task_order(state)),
        ]
    )


# ============================================================ 집계 순서·제외 기업


def _task_order(state: InvestmentState) -> dict[str, int]:
    """기업 이름 → task_index. Worker 완료 순서와 무관하게 계획 순서로 집계하기 위해 쓴다."""
    order: dict[str, int] = {}
    for task in state.get("plan") or []:
        name = normalize_name((task.get("company") or {}).get("name"))
        if name and isinstance(task.get("task_index"), int):
            order.setdefault(name, task["task_index"])
    for result in state.get("worker_results") or []:
        name = normalize_name(result.get("company"))
        if name and isinstance(result.get("task_index"), int):
            order.setdefault(name, result["task_index"])
    return order


def _ordered_records(state: InvestmentState) -> list[EvaluationRecord]:
    """evaluation_history를 task_index 순으로 정렬. 계획에 없는 기업은 입력 순서대로 뒤에 둔다."""
    records = list(state.get("evaluation_history") or [])
    order = _task_order(state)
    return [
        r
        for _, r in sorted(
            enumerate(records),
            key=lambda pair: (
                order.get(normalize_name(pair[1].get("name")), len(order) + pair[0]),
                pair[0],
            ),
        )
    ]


def _excluded(state: InvestmentState) -> list[dict]:
    excluded = [
        w for w in state.get("worker_results") or [] if w.get("status") == "excluded"
    ]
    index = lambda w: w["task_index"] if isinstance(w.get("task_index"), int) else 0
    return sorted(excluded, key=index)


def _add_excluded(md_text: str, state: InvestmentState) -> str:
    """Worker 실패로 제외된 기업을 순위표 아래에 "평가 제외: 회사명(사유)" 줄로 표시한다."""
    excluded = _excluded(state)
    if not excluded:
        return md_text
    # 회사명·오류 문구에 <, & 등이 있어도 HTML로 해석되지 않게 escape한다
    lines = "<br>\n".join(
        html.escape(
            f"평가 제외: {w.get('company') or '회사명 미상'}"
            f"({_trim(w.get('error') or '사유 미상', 80)})"
        )
        for w in excluded
    )
    block = f'<p class="note">{lines}</p>'
    # 순위표가 있으면 1.2 바로 뒤(1.3 앞), 없으면(평가 대상 0곳) 1장 끝(REFERENCE 앞)
    anchor = "\n### 1.3 " if "\n### 1.3 " in md_text else "\n## REFERENCE"
    before, after = md_text.split(anchor, 1)
    return f"{before.rstrip()}\n\n{block}\n{anchor}{after}"


# ============================================================ 구조화 초안 → Markdown


def _merge_refs(base: list[dict], extra: list[dict]) -> list[dict]:
    """출처 목록 병합. 같은 문서는 한 번만 두고 인용 쪽수(cited_pages)를 합친다."""
    merged = {(r.get("title"), r.get("url")): {**r, "cited_pages": list(r.get("cited_pages") or [])} for r in base}
    for r in extra:
        key = (r.get("title"), r.get("url"))
        if key not in merged:
            merged[key] = {**r, "cited_pages": list(r.get("cited_pages") or [])}
            continue
        pages = merged[key]["cited_pages"]
        pages.extend(p for p in r.get("cited_pages") or [] if p not in pages)
    return list(merged.values())


def _prepare(state: InvestmentState) -> dict:
    """LLM 없이 계산되는 집계 결과. 같은 State면 항상 같은 값이다."""
    records = _ordered_records(state)
    ranked = rank_records(records)
    passed = [r for _, _, r in ranked if is_pass(r)]
    kind = "empty" if not records else "pass" if passed else "no_pass"
    return {
        "records": records,
        "ranked": ranked,
        "passed": passed,
        "kind": kind,
        "keyword": state.get("input_keyword") or "AI 신약개발 스타트업",
        "order": _task_order(state),
    }


def _make_draft(
    state: InvestmentState, ctx: dict, feedback: list[str]
) -> tuple[BaseModel | None, dict | None]:
    """LLM 문장 초안. 보고서 종류(pass/no_pass/empty)마다 다른 구조를 만든다."""
    if ctx["kind"] == "empty":
        return None, None
    if ctx["kind"] == "pass":
        return _write_detail(ctx["passed"][0], feedback)

    records, ranked = ctx["records"], ctx["ranked"]
    top = ranked[0][2]
    payload = {
        "candidates": [
            {
                "company": r["name"],
                "total": round(r["total"], 1),
                "hold_reason": r.get("hold_reason"),
                "detail": hold_line(r),
            }
            for r in records
        ],
        "top_candidate": _no_pass_payload(top),
    }
    task = (
        "통과 기업이 0곳이다. 투자 기업을 추천하지 말고, 보류 사유를 근거로 핵심 이유 2~3문장, "
        "최고점 후보의 미달 원인, 재검토 조건을 작성하라. 영역별·질문별 점수는 쓰지 않는다."
    ) + _feedback_task(feedback)
    draft = _call_llm(
        NoPassDraft, payload, task, SECTION_CHAR_LIMITS[0]
    ) or NoPassDraft(
        summary_reasons=[hold_line(r) + f" — {r['name']}" for _, _, r in ranked[:3]],
        top_gap=f"{top['name']}은(는) {hold_line(top)}로 보류됐다.",
        recheck="정보 부족으로 결측 처리된 질문("
        + (", ".join(missing_questions(top)) or "없음")
        + ")과 미확인 관문의 근거가 확보되면 다시 평가한다.",
    )
    details = [
        _write_held_detail(r, feedback) for _, _, r in ranked[:HELD_DETAIL_COUNT]
    ]
    return NoPassReportDraft(**draft.model_dump(), details=details), None


def char_level_of(report_draft: dict | None) -> int:
    """report_draft.section_char_limit → SECTION_CHAR_LIMITS 인덱스 (없으면 0)."""
    limit = (report_draft or {}).get("section_char_limit")
    return SECTION_CHAR_LIMITS.index(limit) if limit in SECTION_CHAR_LIMITS else 0


def _draft_payload(report_draft: dict) -> dict:
    # 공용 계약(schemas.ReportDraft)의 키는 payload
    return report_draft.get("payload") or {}


def rebuild_markdown(
    state: InvestmentState, report_draft: dict, char_level: int
) -> str:
    """저장된 구조화 초안으로 Markdown을 다시 조립한다. LLM을 호출하지 않는다.

    char_level: SECTION_CHAR_LIMITS 인덱스(클수록 문단이 짧다). 순위표·점수·REFERENCE 번호는
    같은 State·초안이면 항상 같다. finalize가 쪽수를 줄일 때도 이 함수를 쓴다.
    """
    return _assemble(state, report_draft, char_level)[0]


def _assemble(
    state: InvestmentState, report_draft: dict, char_level: int
) -> tuple[str, list[dict], dict[str, int]]:
    """rebuild_markdown 본체. (Markdown, REFERENCE에 쓴 출처, 기업 순서)를 돌려준다."""
    level = max(0, min(char_level, len(SECTION_CHAR_LIMITS) - 1))
    limit = SECTION_CHAR_LIMITS[level]
    ctx = _prepare(state)
    # collect_references는 같은 출처를 병합할 때 먼저 나온 항목의 서지정보를 남긴다.
    # Worker 완료 순서와 무관하게 같은 결과가 나오도록 병합 전에 안정 키로 정렬한다.
    references = sorted(
        state.get("references") or [],
        key=lambda r: (reference_sort_key(r, ctx["order"]), str(r.get("page") or "")),
    )
    kind = report_draft.get("kind", ctx["kind"])
    if kind != ctx["kind"]:
        raise ValueError(f"초안 종류({kind})와 평가 이력({ctx['kind']})이 다릅니다.")
    records, ranked, keyword = ctx["records"], ctx["ranked"], ctx["keyword"]
    if kind == "empty":
        md = _build_empty_report(state, keyword)
        refs = [
            {**r, "cited_pages": []}
            for r in state.get("references") or []
            if r.get("agent") == "discovery"
        ]
    elif kind == "pass":
        recommended = ctx["passed"][0]
        draft = DetailDraft.model_validate(_draft_payload(report_draft))
        refs = collect_references(recommended, references)
        md = _build_pass_report(
            records, ranked, recommended, draft, refs, limit, keyword, ctx["order"]
        )
    else:
        top = ranked[0][2]
        draft = NoPassReportDraft.model_validate(_draft_payload(report_draft))
        refs = collect_references(top, references, analyses=False)
        # 3장 상세 검토 기업은 분석 글을 쓴 에이전트의 출처까지 보고서에 남긴다.
        detailed = {normalize_name(d.company) for d in draft.details}
        for record in records:
            if normalize_name(record["name"]) in detailed:
                refs = _merge_refs(refs, collect_references(record, references))
        md = _build_no_pass_report(
            records, ranked, draft, refs, limit, keyword, ctx["order"]
        )
    return _add_excluded(md, state), refs, ctx["order"]


def insert_quality_block(md_text: str, lines: list[str]) -> str:
    """REFERENCE 제목 바로 앞에 "품질 평가 결과" 블록을 넣는다. 이미 있으면 교체한다."""
    if QUALITY_BLOCK_START in md_text:
        before, rest = md_text.split(QUALITY_BLOCK_START, 1)
        after = (
            rest.split(QUALITY_BLOCK_END, 1)[1] if QUALITY_BLOCK_END in rest else rest
        )
        md_text = before.rstrip() + "\n\n" + after.lstrip()
    body = "\n".join(f"- {line}" for line in lines)
    block = (
        f"{QUALITY_BLOCK_START}\n\n### 품질 평가 결과\n\n{body}\n\n{QUALITY_BLOCK_END}"
    )
    if "\n## REFERENCE" not in md_text:
        return f"{md_text.rstrip()}\n\n{block}\n"
    before, after = md_text.split("\n## REFERENCE", 1)
    return f"{before.rstrip()}\n\n{block}\n\n## REFERENCE{after}"


# ============================================================ 점검


def _judge_summary(log: dict) -> str:
    parts = []
    for rnd in log["rounds"]:
        if "grades" not in rnd:
            parts.append(f"{rnd['round']}차 Judge 호출 실패")
            continue
        grades = rnd["grades"].values()
        faith = sum(g["faithfulness"] for g in grades) / len(grades)
        rel = sum(g["relevance"] for g in grades) / len(grades)
        failed = ", ".join(rnd["failed"]) or "없음"
        parts.append(
            f"{rnd['round']}차 충실성 {faith:.1f} · 관련성 {rel:.1f} · 미달 {failed}"
        )
    if log.get("replaced"):
        parts.append("근거 문장으로 대체: " + ", ".join(log["replaced"]))
    return "Judge: " + " / ".join(parts)


def check_report(md_text: str, pages: int | None) -> list[tuple[str, bool]]:
    """교수님 가이드 점검표."""
    headings = re.findall(r"^## (.+)$", md_text, flags=re.MULTILINE)
    summary = md_text.split("## SUMMARY", 1)[-1].split("\n## ", 1)[0]
    return [
        ("첫 챕터가 SUMMARY", bool(headings) and headings[0] == "SUMMARY"),
        ("마지막 챕터가 REFERENCE", bool(headings) and headings[-1] == "REFERENCE"),
        ("SUMMARY에 개요·서론 문구 없음", not INTRO_PATTERNS.search(summary)),
        ("SUMMARY 첫 줄이 결론", summary.strip().startswith("**결론")),
        (f"PDF {MAX_PAGES}쪽 이내", pages is not None and pages <= MAX_PAGES),
    ]


# ============================================================ 노드


def report_writer(state: InvestmentState) -> SynthesizerUpdate:
    """synthesizer 노드. 입력: evaluation_history, references, worker_results, plan, eval_feedback.

    초안 Markdown과 쪽수만 만들고 저장하지 않는다(최종 저장은 finalize).
    반환: final_report, report_pages, report_draft, report_attempts, step_count, node_status.
    """
    feedback = list(state.get("eval_feedback") or [])
    ctx = _prepare(state)
    draft, judge_log = _make_draft(state, ctx, feedback)
    report_draft = {
        "kind": ctx["kind"],
        "payload": draft.model_dump() if draft is not None else {},
        "section_char_limit": SECTION_CHAR_LIMITS[0],
        "reference_map": {},
    }

    # 쪽수 초과 지적을 받았으면 짧은 문단 단계부터 시작한다.
    start = 1 if any("쪽수 초과" in item for item in feedback) else 0
    level, pages, error = start, None, None
    md_text, refs, order = _assemble(state, report_draft, start)
    try:
        from src.tools.report_exporter import render_pdf

        # 내부 목표(MAX_PAGES)에 맞을 때까지 문단 길이·글자 크기를 한 단계씩 줄인다.
        for level in range(start, len(SECTION_CHAR_LIMITS)):
            md_text, refs, order = _assemble(state, report_draft, level)
            _, pages = render_pdf(md_text, level)
            if pages <= MAX_PAGES:
                break
    except Exception as exc:  # noqa: BLE001 — WeasyPrint 미설치·폰트 오류 등. 초안은 계속 넘긴다
        pages = None
        error = f"synthesizer: PDF 렌더링 실패로 쪽수 미확인 ({type(exc).__name__})"
        _log(f"PDF 렌더링 실패, 쪽수 미확인: {type(exc).__name__}: {exc}")
    report_draft["section_char_limit"] = SECTION_CHAR_LIMITS[level]
    # REFERENCE 번호 → 출처. quality_eval이 근거 묶음의 source_ids를 보고서 번호와 맞출 때 쓴다.
    report_draft["reference_map"] = reference_map(refs, order)

    if judge_log and judge_log.get("rounds"):
        _log(_judge_summary(judge_log))
    for item, ok in check_report(md_text, pages):
        _log(f"{'✔' if ok else '✘'} {item}")

    update = {
        "final_report": md_text,
        "report_pages": pages,
        "report_draft": report_draft,
        "report_attempts": (state.get("report_attempts") or 0) + 1,
        "step_count": 1,
        "node_status": {"synthesizer": "done"},
    }
    if error:
        update["last_error"] = error
    return update
