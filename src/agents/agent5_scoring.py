"""Agent 5 계산·판정 (LLM 없음). 같은 입력이면 항상 같은 결과를 낸다.

흐름: 근거 검증 → 결측 점수 교체 → 영역 점수·총점·결측 비중 → 관문 → 판정
판정 전 반올림하지 않는다 (docs/data_contracts.md 6장).
"""

import json
import re
import unicodedata
from typing import Any

from src.agents import agent5_config as cfg

MISSING_TEXT = "정보 없음"


# ── 1. 출처 목록 ──────────────────────────────────────────────
def _ref_key(ref: dict) -> tuple:
    url = (ref.get("url") or "").strip().rstrip("/").lower()
    if url:
        return ("url", url, str(ref.get("page")))
    return (
        "meta",
        ref.get("title"),
        ref.get("issuer"),
        ref.get("year"),
        str(ref.get("page")),
    )


def collect_references(state: dict) -> list[dict]:
    """현재 기업의 출처를 모은다: State references + 프로필 항목별 references.

    다른 기업 출처(company 불일치)는 제외하고, 같은 출처는 한 번만 넣는다.
    """
    company = (state.get("selected_startup") or {}).get("name")
    profile = state.get("startup_profile") or {}
    found: list[dict] = list(state.get("references") or [])
    for key in ("funding_history", "partnerships", "team"):
        for item in profile.get(key) or []:
            found.extend(item.get("references") or [])
    found.extend((profile.get("upfront_payment_basis") or {}).get("references") or [])
    found.extend(profile.get("valuation_references") or [])

    out, seen = [], set()
    for ref in found:
        if not isinstance(ref, dict) or ref.get("company") != company:
            continue
        key = _ref_key(ref)
        if key not in seen:
            seen.add(key)
            out.append(ref)
    return out


# ── 2. 근거 문장 대조 ─────────────────────────────────────────
def _squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text)).lower()


def build_corpus(state: dict) -> str:
    """quote 대조용 원문: 프로필(JSON)과 분석 글 전체."""
    parts = [json.dumps(state.get("startup_profile") or {}, ensure_ascii=False)]
    parts += [
        state.get(k) or ""
        for k in ("tech_analysis", "market_analysis", "competitor_analysis")
    ]
    return "\n".join(_squash(p) for p in parts)


QUOTE_NGRAM = 5  # 근거 문장 대조 단위(공백 제거 후 글자 5개)
QUOTE_MIN_OVERLAP = 0.6  # 근거 문장 조각의 60% 이상이 원문에 있으면 인정


def quote_is_real(quote: Any, corpus: str) -> bool:
    """근거 문장이 원문에 있는지 확인한다.

    LLM은 원문을 조금씩 바꿔 인용하므로(조사·기호·말줄임), 글자 그대로 일치하지
    않아도 5글자 조각의 60% 이상이 원문에 있으면 인정한다. 원문에 없는 문장은
    대부분의 조각이 원문에 없어 여전히 걸러진다.
    """
    if not isinstance(quote, str) or len(_squash(quote)) < 4:
        return False
    if _squash(quote) in corpus:  # 기존 규칙: 글자 그대로 일치
        return True
    q = _squash(re.sub(r"[\"'“”‘’「」『』…·.,!?()\[\]]", "", quote))
    if len(q) < 4:
        return False
    if q in corpus:
        return True
    if len(q) < QUOTE_NGRAM * 2:
        return False
    grams = [q[i : i + QUOTE_NGRAM] for i in range(len(q) - QUOTE_NGRAM + 1)]
    hit = sum(g in corpus for g in grams)
    return hit / len(grams) >= QUOTE_MIN_OVERLAP


# ── 3. 질문별 근거 확정 ───────────────────────────────────────
def default_score(question: str) -> int:
    return (
        cfg.MISSING_SCORE_DEAL if question in cfg.DEAL_QUESTIONS else cfg.MISSING_SCORE
    )


def _missing(question: str, note: str | None = None) -> dict:
    return {
        "score": default_score(question),
        "rationale": f"{MISSING_TEXT} ({note})" if note else MISSING_TEXT,
        "references": [],
        "missing": True,
    }


def finalize_evidence(
    raw: dict, ref_catalog: dict[str, dict], corpus: str, business_model: str | None
) -> dict:
    """LLM 출력(raw: 질문 → dict)을 QuestionEvidence 15개로 확정한다.

    결측 처리: LLM이 missing, 점수 없음, 출처 번호 없음·불일치, 근거 문장 불일치.
    """
    evidence = {}
    for q in cfg.ALL_QUESTIONS:
        if q == "QD" and business_model not in ("pipeline", "platform"):
            evidence[q] = {**_missing(q), "rationale": "사업 모델 미확인으로 정보 부족"}
            continue
        item = raw.get(q)
        if item is None:
            evidence[q] = _missing(q, "채점 결과 누락")
            continue
        if item.get("missing"):
            evidence[q] = _missing(q)
            continue
        score = item.get("score")
        refs = [ref_catalog[i] for i in item.get("ref_ids") or [] if i in ref_catalog]
        if score not in (1, 2, 3, 4, 5):
            evidence[q] = _missing(q, "점수 없음")
        elif not refs:
            evidence[q] = _missing(q, "출처 없음")
        elif not quote_is_real(item.get("quote"), corpus):
            evidence[q] = _missing(q, "근거 문장 불일치")
        else:
            reason = (item.get("reason") or "").strip()
            evidence[q] = {
                "score": score,
                "rationale": f"{reason} (근거: “{item['quote'].strip()}”)",
                "references": refs,
                "missing": False,
            }
    return evidence


# ── 4. 점수 계산 (반올림 없음) ───────────────────────────────────
def compute_scores(evidence: dict) -> tuple[dict, float, float]:
    area_scores, total, missing_weight = {}, 0.0, 0.0
    for area, qs in cfg.QUESTIONS.items():
        avg = sum(evidence[q]["score"] for q in qs) / len(qs)
        area_scores[area] = avg / 5 * 100
        total += area_scores[area] * cfg.WEIGHTS[area]
        n_missing = sum(evidence[q]["missing"] for q in qs)  # QN·QO 포함
        missing_weight += cfg.WEIGHTS[area] * n_missing / len(qs)
    return area_scores, total, missing_weight


# ── 5. 관문과 판정 ────────────────────────────────────────────
def check_gates(profile: dict) -> tuple[list[str], bool, list[str]]:
    """(해당 관문 이름, 자격 미확인 여부, 미확인 리스크 관문 키)"""
    gates = profile.get("gates") or {}
    hit = [
        cfg.GATE_LABELS[k]
        for k in cfg.ELIGIBILITY_GATES + cfg.RISK_GATES
        if gates.get(k) is True
    ]
    eligibility_unknown = any(gates.get(k) is None for k in cfg.ELIGIBILITY_GATES)
    unconfirmed = [k for k in cfg.RISK_GATES if gates.get(k) is None]
    return hit, eligibility_unknown, unconfirmed


# 부동소수점 오차 보정용 (반올림이 아님). 예: 0.25/3 + 0.10/2 + ... 가 0.2999999… 로 계산되는 경우
EPS = 1e-9


def _at_least(value: float, threshold: float) -> bool:
    return value >= threshold - EPS


def decide(total, area_scores, missing_weight, gate_hits, eligibility_unknown):
    """판정 규칙 1~5 (위에서부터 먼저 걸리는 규칙)."""
    if gate_hits:
        return "보류", f"관문 ({', '.join(gate_hits)})"
    if eligibility_unknown:
        return "보류", "자격 미확인"
    if _at_least(missing_weight, cfg.MAX_MISSING_WEIGHT):
        return "보류", "근거 부족"
    passed_total = _at_least(total, cfg.PASS_SCORE)
    if passed_total and _at_least(area_scores["founder"], cfg.FOUNDER_MIN):
        return "통과", None
    if not passed_total:
        return "보류", "총점 미달"
    return "보류", "창업자 미달"


def make_rationale(
    verdict, hold_reason, total, area_scores, evidence, unconfirmed
) -> str:
    """판정 요약 (표시용 문장이라 여기서만 소수 1자리로 표시)."""
    names = cfg.AREA_NAMES
    best = max(area_scores, key=area_scores.get)
    worst = min(area_scores, key=area_scores.get)
    head = "통과" if verdict == "통과" else f"보류({hold_reason})"
    text = (
        f"{head}: 총점 {total:.1f}점, 강점 {names[best]}({area_scores[best]:.1f}), "
        f"약점 {names[worst]}({area_scores[worst]:.1f})"
    )
    missing_qs = [q for q, e in evidence.items() if e["missing"]]
    if missing_qs:
        text += f", 정보 부족 {len(missing_qs)}문항({', '.join(missing_qs)})"
    if unconfirmed:
        text += f", 미확인 리스크 관문 {len(unconfirmed)}개"
    return text


# ── 6. 런타임 검증 (schemas.py TODO) ────────────────────────────
def validate_decision(decision: dict) -> None:
    qs, ev = decision["question_scores"], decision["question_evidence"]
    if set(qs) != set(cfg.ALL_QUESTIONS) or set(ev) != set(cfg.ALL_QUESTIONS):
        raise ValueError("QA~QO 15개 질문이 모두 있어야 합니다.")
    for q in cfg.ALL_QUESTIONS:
        if qs[q] not in (1, 2, 3, 4, 5):
            raise ValueError(f"{q} 점수는 1~5 정수여야 합니다: {qs[q]}")
        if ev[q]["score"] != qs[q]:
            raise ValueError(
                f"{q}: question_scores와 question_evidence.score가 다릅니다."
            )
    if set(decision["area_scores"]) != set(cfg.WEIGHTS):
        raise ValueError(
            "area_scores 키는 founder/market/product/moat/traction/deal이어야 합니다."
        )
    if not 0 <= decision["missing_weight"] <= 1:
        raise ValueError("missing_weight는 0~1이어야 합니다.")
