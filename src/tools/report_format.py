"""Agent 6 보고서용 코드 처리: 정렬, 점수·금액 표시, REFERENCE 조립.

LLM을 쓰지 않는 부분만 모았다. 같은 입력이면 항상 같은 결과가 나온다.
"""

import re
import unicodedata
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from src.schemas import EvaluationRecord, MonetaryAmount, Reference

# 투자평가기준 v4 영역 순서와 보고서 표시명
AREA_LABELS = {
    "founder": "창업자",
    "market": "시장성",
    "product": "제품·기술력",
    "moat": "경쟁우위",
    "traction": "실적",
    "deal": "투자조건",
}
AREA_QUESTIONS = {
    "founder": ["QA", "QB", "QC"],
    "market": ["QD", "QE", "QF"],
    "product": ["QG", "QH"],
    "moat": ["QI", "QJ"],
    "traction": ["QK", "QL", "QM"],
    "deal": ["QN", "QO"],
}
QUESTION_LABELS = {
    "QA": "팀 신뢰도",
    "QB": "장기 헌신",
    "QC": "실행력",
    "QD": "시장 크기",
    "QE": "미충족 수요 해결",
    "QF": "큰 기회",
    "QG": "독창성·AI 진위",
    "QH": "구현·검증",
    "QI": "차별성",
    "QJ": "진입장벽",
    "QK": "비용 지불 이유",
    "QL": "초기 반응",
    "QM": "수익 모델",
    "QN": "밸류에이션",
    "QO": "투자 구조",
}
GATE_LABELS = {
    "not_eligible": "상장 완료 또는 시리즈 D 이상",
    "subsidiary_of_large_corp": "대기업 자회사",
    "clinical_failure": "주력 파이프라인 임상 중단·실패",
    "founder_exit_or_dispute": "창업자·CEO 이탈 또는 경영권 분쟁",
    "patent_loss": "핵심 특허 분쟁 패소",
    "funding_gap_restructuring": "24개월 이상 투자 공백 + 구조조정",
}
PASS_SCORE = 75
FOUNDER_MIN = 60
MAX_MISSING_WEIGHT = 0.30
UNKNOWN = "미확인"


# ---------------------------------------------------------------- 이름·정렬


def normalize_name(name: str | None) -> str:
    """공백·대소문자·유니코드 표기 차이를 없앤 비교용 이름."""
    if not name:
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", name)).casefold()


def sort_key(record: EvaluationRecord) -> tuple[float, float, float]:
    """총점 → 창업자 → 시장성 (반올림 전 원값, 내림차순)."""
    areas = record["area_scores"]
    return (-record["total"], -areas["founder"], -areas["market"])


def rank_records(
    records: Iterable[EvaluationRecord],
) -> list[tuple[int, bool, EvaluationRecord]]:
    """(순위, 동점 여부, 기록) 목록. 세 기준이 모두 같으면 같은 순위로 둔다.

    v4에 없는 추가 동점 기준은 만들지 않는다. 동점 기업끼리의 표시 순서는
    입력 순서를 유지할 뿐 우열을 뜻하지 않는다.
    """
    ordered = sorted(records, key=sort_key)
    keys = [sort_key(r) for r in ordered]
    ranked = []
    for i, record in enumerate(ordered):
        rank = i + 1
        if i > 0 and keys[i] == keys[i - 1]:
            rank = ranked[-1][0]
        tie = keys.count(keys[i]) > 1
        ranked.append((rank, tie, record))
    return ranked


def is_pass(record: EvaluationRecord) -> bool:
    return record.get("verdict") == "통과"


# ---------------------------------------------------------------- 숫자 표시


def fmt_score(value: float | None) -> str:
    """표시 전용 반올림. 원본 점수는 바꾸지 않는다."""
    return "–" if value is None else f"{value:.1f}"


def fmt_percent(ratio: float | None) -> str:
    return "–" if ratio is None else f"{ratio * 100:.0f}%"


def _fmt_number(value: float) -> str:
    return f"{value:,.0f}"


def fmt_money(amount: MonetaryAmount | None) -> str:
    """공통 계약: 국내 N원 / 해외 N원/M달러 / 환산 근거 없으면 미확인 표시."""
    if not amount or amount.get("original_amount") is None:
        return "정보 부족"
    currency = (amount.get("original_currency") or "").upper()
    krw, usd = amount.get("krw_amount"), amount.get("usd_amount")
    if currency == "KRW":
        return f"{_fmt_number(krw if krw is not None else amount['original_amount'])}원"
    if krw is not None and usd is not None:
        return f"{_fmt_number(krw)}원/{_fmt_number(usd)}달러"
    original = f"{_fmt_number(amount['original_amount'])} {currency or '통화 미확인'}"
    krw_text = f"{_fmt_number(krw)}원" if krw is not None else "원화 환산 미확인"
    usd_text = f"{_fmt_number(usd)}달러" if usd is not None else "달러 환산 미확인"
    return f"{krw_text}/{usd_text} (원문: {original})"


def uses_fixed_fx(amounts: Iterable[MonetaryAmount | None]) -> bool:
    return any(a and "고정 가정" in (a.get("fx_source") or "") for a in amounts)


# ---------------------------------------------------------------- 판정 사유


def hold_line(record: EvaluationRecord) -> str:
    """보류 기업 1줄 사유. v4의 보류 사유 문구에 확인 가능한 수치를 덧붙인다."""
    reason = record.get("hold_reason") or "보류"
    areas = record["area_scores"]
    if reason == "근거 부족":
        return f"근거 부족 (결측 비중 {fmt_percent(record['missing_weight'])}, 기준 30% 이상)"
    if reason == "총점 미달":
        return f"총점 미달 ({fmt_score(record['total'])}점, 기준 75점)"
    if reason == "창업자 미달":
        return f"창업자 미달 (창업자 영역 {fmt_score(areas['founder'])}점, 기준 60점)"
    return reason  # 관문(항목) / 자격 미확인


def strong_areas(record: EvaluationRecord, n: int = 2) -> list[str]:
    areas = record["area_scores"]
    top = sorted(AREA_LABELS, key=lambda k: -areas[k])[:n]
    return [f"{AREA_LABELS[k]} {fmt_score(areas[k])}점" for k in top]


def missing_questions(record: EvaluationRecord) -> list[str]:
    evidence = record.get("question_evidence") or {}
    return [q for q in QUESTION_LABELS if evidence.get(q, {}).get("missing")]


def gate_status(record: EvaluationRecord) -> list[tuple[str, str]]:
    """관문별 (항목, 상태). None은 '미확인'으로 보존한다."""
    gates = (record.get("startup_profile") or {}).get("gates") or {}
    status = []
    for key, label in GATE_LABELS.items():
        value = gates.get(key)
        text = "해당" if value is True else "해당 없음" if value is False else UNKNOWN
        status.append((label, text))
    return status


# ---------------------------------------------------------------- REFERENCE


def _normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")
    )


def _ref_key(ref: Reference) -> tuple:
    if ref.get("url"):
        return ("url", _normalize_url(ref["url"]))
    who = ref.get("authors") or ref.get("issuer")
    who = tuple(who) if isinstance(who, list) else who
    return (ref.get("doc_type"), normalize_name(ref.get("title")), who, ref.get("year"))


def collect_references(
    record: EvaluationRecord | None, state_references: Iterable[Reference]
) -> list[dict]:
    """보고서에 실제 사용한 출처만 모은다.

    - 상세 분석 대상 기업(record)의 출처: company 일치 + 분석 에이전트(profile/tech/market/competitor)
    - 질문별 근거(question_evidence)와 프로필 항목에 연결된 출처
    같은 자료는 한 항목으로 합치고 원문 인용 쪽수(page)는 모아서 보존한다.
    """
    if record is None:
        return []
    name = normalize_name(record["name"])
    pool: list[Reference] = [
        r
        for r in state_references
        if normalize_name(r.get("company")) == name
        and r.get("agent") in {"profile", "tech", "market", "competitor"}
    ]
    for evidence in (record.get("question_evidence") or {}).values():
        pool.extend(evidence.get("references") or [])

    merged: dict[tuple, dict] = {}
    for ref in pool:
        key = _ref_key(ref)
        item = merged.setdefault(key, {**ref, "cited_pages": []})
        page = ref.get("page")
        if page not in (None, "") and str(page) not in item["cited_pages"]:
            item["cited_pages"].append(str(page))
    return list(merged.values())


def _v(value) -> str:
    return UNKNOWN if value in (None, "", []) else str(value)


def _pages_suffix(ref: dict) -> str:
    pages = ref.get("cited_pages") or []
    return f" (인용 p. {', '.join(pages)})" if pages else ""


def format_reference(ref: dict) -> str:
    """공통 계약 7장 형식. 없는 서지정보는 만들지 않고 '미확인'으로 표시한다."""
    doc_type = ref.get("doc_type")
    title = _v(ref.get("title"))
    url = ref.get("url")
    if doc_type == "paper":
        authors = ", ".join(ref.get("authors") or []) or UNKNOWN
        vol = _v(ref.get("volume"))
        issue = f"({ref['issue']})" if ref.get("issue") else ""
        text = (
            f"{authors}({_v(ref.get('year'))}). {title}. "
            f"*{_v(ref.get('journal'))}*, {vol}{issue}, {_v(ref.get('pages'))}."
        )
    elif doc_type == "web":
        who = ", ".join(ref.get("authors") or []) or _v(ref.get("issuer"))
        date = ref.get("published_date") or (
            str(ref["year"]) if ref.get("year") else UNKNOWN
        )
        text = f"{who}({date}). *{title}*. {_v(ref.get('site_name'))}, {_v(url)}"
    else:  # report
        text = f"{_v(ref.get('issuer'))}({_v(ref.get('year'))}). *{title}*."
        text += f" {url}" if url else f" URL {UNKNOWN}"
    return text + _pages_suffix(ref)


REFERENCE_GROUPS = [
    ("report", "기관 보고서"),
    ("paper", "학술 논문"),
    ("web", "웹페이지"),
]


def reference_section(refs: list[dict]) -> str:
    if not refs:
        return "보고서 작성에 사용한 출처가 State에 기록되지 않았다."
    lines = []
    for doc_type, label in REFERENCE_GROUPS:
        group = [r for r in refs if r.get("doc_type") == doc_type]
        if not group:
            continue
        group.sort(
            key=lambda r: (_v(r.get("issuer") or r.get("authors")), _v(r.get("year")))
        )
        lines.append(f"**{label}**\n")
        lines.extend(f"{i}. {format_reference(r)}" for i, r in enumerate(group, 1))
        lines.append("")
    return "\n".join(lines).strip()
