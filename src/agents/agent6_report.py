"""Agent 6 ReportWriter: 누적 평가 이력으로 투자 심사 보고서(Markdown·PDF)를 만든다.

역할 분담
- 코드: 정렬·순위표·점수·금액 표시·관문 상태·REFERENCE·목차 순서·쪽수 검사
- LLM: SUMMARY 투자 이유 3줄·핵심 리스크, 2장 소항목 설명 문장, 통과 0곳일 때 미달 원인 설명
- LLM 사용 불가(키 없음·API 오류) 시: 평가 이력의 근거 문장으로 같은 구조를 채운다.

목차는 설계서 8장을 따른다: SUMMARY → 1. 평가 결과 순위표 → 2. 상세 분석 → REFERENCE
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from src.config import LLM_MODEL, LLM_TEMPERATURE, PROJECT_ROOT
from src.schemas import EvaluationRecord, ReportUpdate
from src.state import InvestmentState
from src.tools.report_format import (
    AREA_LABELS,
    AREA_QUESTIONS,
    QUESTION_LABELS,
    collect_references,
    fmt_money,
    fmt_percent,
    fmt_score,
    gate_status,
    hold_line,
    is_pass,
    missing_questions,
    rank_records,
    reference_section,
    strong_areas,
    uses_fixed_fx,
)

MAX_PAGES = 5
# 쪽수가 넘칠 때 단계별로 줄이는 LLM 문단 최대 글자 수
SECTION_CHAR_LIMITS = [650, 480, 340, 230]
SECTION_KEYS = ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6", "2.7"]
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
    text: str = Field(description="투자 이유 한 문장 (수치 포함, 40~80자)")
    section: Literal["2.1", "2.2", "2.3", "2.4", "2.5", "2.6"] = Field(
        description="근거가 설명된 본문 소항목 번호"
    )


class DetailDraft(BaseModel):
    reasons: list[Reason] = Field(description="투자 이유 정확히 3개")
    key_risk: str = Field(description="가장 중요한 리스크 한 문장")
    s2_1: str = Field(description="2.1 기업 개요와 사업 아이디어")
    s2_2: str = Field(description="2.2 기술력과 AI 검증 (QG, QH)")
    s2_3: str = Field(description="2.3 시장 규모와 성장성 (QD, QE, QF)")
    s2_4: str = Field(description="2.4 경쟁 구도와 차별성 (QI, QJ)")
    s2_5: str = Field(description="2.5 팀 구성 (QA, QB, QC)")
    s2_6: str = Field(description="2.6 실적과 투자 조건 (QK~QO)")
    s2_7: str = Field(description="2.7 사업 리스크와 한계점")


class NoPassDraft(BaseModel):
    summary_reasons: list[str] = Field(description="투자 추천이 없는 핵심 이유 2~3문장")
    top_gap: str = Field(description="최고점 후보가 기준에 못 미친 영역과 근거")
    recheck: str = Field(description="어떤 정보가 확보되면 다시 평가할지")


SYSTEM_PROMPT = """너는 벤처캐피털 투자 심사역이다. 주어진 평가 데이터만 근거로 투자 심사 보고서 문장을 한국어로 쓴다.
규칙:
1. 주어진 데이터에 없는 사실·수치·기업·출처를 만들지 않는다. 데이터가 없으면 "정보 부족"이라고 쓴다.
2. "본 보고서는", "이 문서는", 개요·배경·서론 문장을 쓰지 않는다. 결론과 근거부터 쓴다.
3. 점수는 주어진 값을 그대로 인용한다. 점수를 다시 매기거나 판정을 바꾸지 않는다.
4. missing=true인 질문은 "정보 부족"으로 표현하고 추정하지 않는다.
5. 문장은 "~다"체로 짧게 쓴다. 각 소항목은 {limit}자 이내로 쓴다.
6. 관문 값이 null이면 "미확인"이라고 쓴다. 미확인을 "문제 없음"으로 해석하지 않는다."""


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


def _call_llm(schema: type[BaseModel], payload: dict, task: str, limit: int):
    """구조화 출력으로 LLM 호출. 실패하면 None을 돌려주고 호출부가 대체 문장을 쓴다."""
    if not _llm_available():
        return None
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=LLM_MODEL, temperature=LLM_TEMPERATURE)
        messages = [
            ("system", SYSTEM_PROMPT.format(limit=limit)),
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
    section_of = {
        "founder": "2.5",
        "market": "2.3",
        "product": "2.2",
        "moat": "2.4",
        "traction": "2.6",
    }
    reasons = []
    for key in top:
        first = _evidence_text(record, AREA_QUESTIONS[key]).split(". ")[0].rstrip(".")
        reasons.append(
            Reason(
                text=f"{AREA_LABELS[key]} {fmt_score(areas[key])}점: {first}.",
                section=section_of[key],
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
    return f'# AI 신약개발 스타트업 투자 심사 보고서\n\n<p class="meta">작성일 {datetime.now(ZoneInfo("Asia/Seoul")):%Y-%m-%d} · 탐색 키워드 "{keyword}" · 평가 후보 {len(records)}곳</p>'


def _build_pass_report(
    records, ranked, recommended, draft: DetailDraft, refs, limit: int, keyword: str
) -> str:
    name = recommended["name"]
    reasons = "\n".join(
        f"{i}. {_remove_intro(r.text)} (→ {r.section})"
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
            reference_section(refs),
        ]
    )


def _build_no_pass_report(
    records, ranked, draft: NoPassDraft, refs, limit: int, keyword: str
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
            + "\n\n".join([_score_line(top, a) for a in AREA_LABELS])
            + "\n\n"
            + _trim(_remove_intro(draft.top_gap), limit),
            "### 2.3 재검토 조건\n\n" + _trim(_remove_intro(draft.recheck), limit),
            "## REFERENCE",
            reference_section(refs),
        ]
    )


def _build_empty_report(state: InvestmentState, keyword: str) -> str:
    discovery = [
        r for r in state.get("references") or [] if r.get("agent") == "discovery"
    ]
    refs = [{**r, "cited_pages": []} for r in discovery]
    return "\n\n".join(
        [
            _header([], keyword),
            "## SUMMARY",
            "**결론: 투자 추천 없음 — 평가 대상 후보 0곳**",
            (
                "자격 검증(비상장, Seed~Series C, Exit 전, 대기업 자회사 제외)을 통과한 후보가 없어 "
                f"채점과 순위표를 만들지 않았다. 탐색 과정에서 확인한 출처는 {len(discovery)}건이다."
            ),
            "## 1. 평가 결과 순위표\n\n평가 대상 없음.",
            "## REFERENCE",
            reference_section(refs),
        ]
    )


# ============================================================ 점검


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


def report_writer(state: InvestmentState) -> ReportUpdate:
    """입력: evaluation_history, references. 출력: final_report (State 변경분만 반환).

    부수 효과: outputs/ 에 Markdown과 PDF를 저장한다 (REPORT_OUTPUT_DIR로 변경 가능).
    """
    records: list[EvaluationRecord] = list(state.get("evaluation_history") or [])
    keyword = state.get("input_keyword") or "AI 신약개발 스타트업"
    ranked = rank_records(records)
    passed = [r for _, _, r in ranked if is_pass(r)]

    # 1) LLM 문장 초안은 한 번만 만들고, 쪽수 조정은 코드로 자른다.
    if not records:
        build = lambda limit: _build_empty_report(state, keyword)
    elif passed:
        recommended = passed[0]
        refs = collect_references(recommended, state.get("references") or [])
        draft = _call_llm(
            DetailDraft,
            _llm_payload(recommended),
            "투자 추천 기업의 SUMMARY 투자 이유 3개(각각 근거 소항목 번호 포함), 핵심 리스크 1문장, "
            "2.1~2.7 소항목 설명을 작성하라. 2.7은 관문 미확인·정보 부족 항목을 포함한 리스크를 쓴다.",
            SECTION_CHAR_LIMITS[0],
        ) or _fallback_detail(recommended)
        build = lambda limit: _build_pass_report(
            records, ranked, recommended, draft, refs, limit, keyword
        )
    else:
        top = ranked[0][2]
        refs = collect_references(top, state.get("references") or [])
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
            "top_candidate": _llm_payload(top, analysis_chars=1200),
        }
        draft = _call_llm(
            NoPassDraft,
            payload,
            "통과 기업이 0곳이다. 투자 기업을 추천하지 말고, 보류 사유를 근거로 핵심 이유 2~3문장, "
            "최고점 후보의 미달 원인, 재검토 조건을 작성하라.",
            SECTION_CHAR_LIMITS[0],
        ) or NoPassDraft(
            summary_reasons=[
                hold_line(r) + f" — {r['name']}" for _, _, r in ranked[:3]
            ],
            top_gap=_evidence_text(top, [q for q in QUESTION_LABELS]),
            recheck="정보 부족으로 결측 처리된 질문("
            + (", ".join(missing_questions(top)) or "없음")
            + ")과 미확인 관문의 근거가 확보되면 다시 평가한다.",
        )
        build = lambda limit: _build_no_pass_report(
            records, ranked, draft, refs, limit, keyword
        )

    # 2) PDF로 바꿔 쪽수를 확인하고, 넘치면 문단 길이와 글자 크기를 한 단계씩 줄인다.
    md_text, pdf_bytes, pages = build(SECTION_CHAR_LIMITS[0]), None, None
    try:
        from src.tools.report_exporter import render_pdf, save_outputs

        for level, limit in enumerate(SECTION_CHAR_LIMITS):
            md_text = build(limit)
            pdf_bytes, pages = render_pdf(md_text, level)
            if pages <= MAX_PAGES:
                break
        out_dir = Path(os.getenv("REPORT_OUTPUT_DIR", PROJECT_ROOT / "outputs"))
        stem = os.getenv("REPORT_FILE_STEM", "investment_report")
        paths = save_outputs(md_text, pdf_bytes, out_dir, stem)
        _log(f"저장: {paths['pdf']} ({pages}쪽)")
    except (ImportError, OSError) as exc:  # WeasyPrint 시스템 라이브러리 미설치 등
        _log(f"PDF 생성 실패, Markdown만 반환: {type(exc).__name__}: {exc}")

    for item, ok in check_report(md_text, pages):
        _log(f"{'✔' if ok else '✘'} {item}")
    return {"final_report": md_text}
