"""Agent 2 순수 함수. LLM·네트워크 없이 단위 테스트한다.

금액·날짜·단계 형식은 docs/data_contracts.md 2~5장을 따른다.
"""

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from src.schemas import MonetaryAmount, Reference

USD_TO_KRW = 1400  # 투자평가기준 v4 7장 고정 가정
FX_SOURCE_USD = "투자평가기준 v4 고정 가정: 1 USD = 1,400 KRW"


# ── 금액 ─────────────────────────────────────────────────────
_CURRENCIES = [
    ("USD", r"\$|usd|달러|dollar"),
    ("EUR", r"€|eur\b|유로"),
    ("GBP", r"£|gbp|파운드"),
    ("JPY", r"¥|jpy|엔화|\d\s*엔"),
    ("CNY", r"cny|rmb|위안"),
    ("KRW", r"₩|krw|원"),
]
_KO_UNITS = {"조": 1e12, "억": 1e8, "만": 1e4}
_EN_UNITS = {
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "million": 1e6,
    "mn": 1e6,
    "m": 1e6,
    "thousand": 1e3,
    "k": 1e3,
}


def parse_amount(text: str | None) -> tuple[float | None, str | None]:
    """원문 금액 → (기본 통화 단위 금액, 통화 코드). 해석 불가면 (None, None).

    '420억원' → (42000000000, 'KRW'), '$60 million' → (60000000, 'USD'),
    '1억3000만 달러' → (130000000, 'USD'), '3천만 달러' → (30000000, 'USD')
    """
    if not text:
        return None, None
    raw = str(text).replace(",", "").strip()
    low = raw.lower()
    currency = next((c for c, p in _CURRENCIES if re.search(p, low)), None)

    value = 0.0
    for num in re.findall(r"(\d+(?:\.\d+)?)\s*천\s*만", raw):
        value += float(num) * 1e7
    rest = re.sub(r"\d+(?:\.\d+)?\s*천\s*만", " ", raw)
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(조|억|만)", rest):
        value += float(num) * _KO_UNITS[unit]
    if value > 0:
        return value, currency

    en = re.search(r"(\d+(?:\.\d+)?)\s*(billion|bn|million|mn|thousand|b|m|k)\b", low)
    if en:
        return float(en.group(1)) * _EN_UNITS[en.group(2)], currency

    plain = re.search(r"\d+(?:\.\d+)?", raw)
    if plain:
        return float(plain.group(0)), currency
    return None, None


def money(amount: float | None, currency: str | None) -> MonetaryAmount | None:
    """MonetaryAmount 생성. 금액 미확인이면 객체 전체가 None. 환산값을 임의로 만들지 않는다."""
    if amount is None:
        return None
    amount = int(amount) if float(amount).is_integer() else amount
    krw = usd = fx_source = None
    if currency == "KRW":
        krw = amount
    elif currency == "USD":
        usd = amount
        krw = amount * USD_TO_KRW
        fx_source = FX_SOURCE_USD
    elif amount == 0:
        krw = usd = 0
    return {
        "original_amount": amount,
        "original_currency": currency,
        "krw_amount": krw,
        "usd_amount": usd,
        "fx_date": None,
        "fx_source": fx_source,
    }


def money_from_text(text: str | None) -> MonetaryAmount | None:
    return money(*parse_amount(text))


# ── 날짜 ─────────────────────────────────────────────────────
def normalize_date(text: str | None) -> str | None:
    """확인된 정밀도까지만 ISO 형식으로. 알 수 없는 월·일을 채우지 않는다."""
    if not text:
        return None
    m = re.match(
        r"\s*(\d{4})(?:\s*[-./년]\s*(\d{1,2}))?(?:\s*[-./월]\s*(\d{1,2}))?", str(text)
    )
    if not m:
        return None
    year, month, day = m.group(1), m.group(2), m.group(3)
    if month and not 1 <= int(month) <= 12:
        return year
    if day and not 1 <= int(day) <= 31:
        day = None
    if month and day:
        return f"{year}-{int(month):02d}-{int(day):02d}"
    if month:
        return f"{year}-{int(month):02d}"
    return year


def date_bounds(iso: str | None) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """부분 날짜의 (가장 이른 연월, 가장 늦은 연월). 연도만 있으면 1월~12월."""
    if not iso:
        return None
    parts = iso.split("-")
    year = int(parts[0])
    if len(parts) >= 2:
        month = int(parts[1])
        return (year, month), (year, month)
    return (year, 1), (year, 12)


def months_between(earlier: tuple[int, int], later: tuple[int, int]) -> int:
    return (later[0] - earlier[0]) * 12 + (later[1] - earlier[1])


def date_sort_key(iso: str | None) -> tuple[int, int, int] | None:
    """최신 비교용. 같은 연도라도 정밀도가 다르면 앞에서부터 비교한다."""
    if not iso:
        return None
    parts = [int(p) for p in iso.split("-")] + [0, 0]
    return parts[0], parts[1], parts[2]


# ── 개발 단계 ─────────────────────────────────────────────────
# 복합 임상은 앞 단계와 같은 순위로 둔다 (이전 단계 완료로 간주하지 않음).
_DEV_RANK = {
    "개념": 0,
    "컴퓨터 예측": 1,
    "실험 검증": 2,
    "전임상": 3,
    "IND 신청": 4,
    "IND 승인": 5,
    "임상 1상": 6,
    "임상 1/2상": 6,
    "임상 2상": 7,
    "임상 2/3상": 7,
    "임상 3상": 8,
    "허가 신청": 9,
    "허가 승인": 10,
}
_CLINICAL_OR_APPROVED = {k for k, v in _DEV_RANK.items() if v >= 5}
_PLAN_WORDS = re.compile(
    r"계획|예정|목표|추진|준비|planned|plan to|expected|aim|intend", re.IGNORECASE
)
_P12 = re.compile(
    r"(phase|임상)\s*(1|i)\s*[/\-~]\s*(2|ii)(?!\d)|1\s*[/\-]\s*2\s*상", re.IGNORECASE
)
_P23 = re.compile(
    r"(phase|임상)\s*(2|ii)\s*[/\-~]\s*(3|iii)(?!\d)|2\s*[/\-]\s*3\s*상", re.IGNORECASE
)


def dev_rank(stage: str | None) -> int:
    return _DEV_RANK.get(stage, -1)


def guard_dev_stage(stage: str | None, original: str | None) -> str | None:
    """LLM 단계값을 원문과 대조해 승격을 막는다.

    - 원문이 1/2상·2/3상인데 뒤 단계로 올린 값은 복합 임상 표기로 되돌린다.
    - 원문이 계획·예정이면 IND 승인·임상·허가 단계를 기록하지 않는다(None).
    """
    if stage is None:
        return None
    text = original or ""
    if _P12.search(text) and stage in {"임상 2상", "임상 2/3상", "임상 3상"}:
        return "임상 1/2상"
    if _P23.search(text) and stage == "임상 3상":
        return "임상 2/3상"
    if _PLAN_WORDS.search(text) and stage in _CLINICAL_OR_APPROVED:
        return None
    return stage


# ── 투자 단계 (국내 시리즈 A / 해외 시리즈 AF) ──────────────────
def round_base(original: str | None) -> str | None:
    """원문 라운드명 → 팀 공통 기본 단계명(접미사 없음). 비표준이면 None."""
    if not original:
        return None
    t = re.sub(r"[\s\-_]", "", original).lower()
    series = re.search(r"(?:series|시리즈)([a-z])", t)
    if re.search(r"pre(?:series)?([a-z])$|프리(?:시리즈)?([a-z])$", t) and not series:
        letter = re.search(r"([a-z])$", t).group(1).upper()
        return f"프리 시리즈 {letter}"
    if series:
        letter = series.group(1).upper()
        if t.startswith(("pre", "프리")):
            return f"프리 시리즈 {letter}"
        return f"시리즈 {letter}"
    if "preseed" in t or "프리시드" in t:
        return "프리시드"
    if "seed" in t or "시드" in t:
        return "시드"
    if "bridge" in t or "브리지" in t or "브릿지" in t:
        return "브리지"
    return None


def stage_label(base: str | None, region: str | None) -> str | None:
    if base is None:
        return None
    return f"{base}F" if region == "foreign" else base


def series_letter(base: str | None) -> str | None:
    m = re.match(r"^시리즈 ([A-Z])$", base or "")
    return m.group(1) if m else None


# ── 출처 ─────────────────────────────────────────────────────
def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    query = urlencode(
        [
            (k, v)
            for k, v in parse_qsl(p.query)
            if not k.lower().startswith(("utm_", "fbclid", "gclid"))
        ]
    )
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", query, ""))


def web_reference(company: str, doc: dict) -> Reference:
    """Tavily 결과 → Reference. 원문에 없는 저자·날짜를 만들지 않는다."""
    netloc = urlparse(doc["url"]).netloc.lower()
    site = netloc.removeprefix("www.")
    published = normalize_date(doc.get("published_date"))
    return {
        "company": company,
        "agent": "profile",
        "title": doc.get("title") or doc["url"],
        "source": "web",
        "issuer": doc.get("author") or site,
        "year": int(published[:4]) if published else None,
        "doc_type": "web",
        "page": None,
        "url": doc["url"],
        "authors": None,
        "published_date": published,
        "site_name": site,
        "journal": None,
        "volume": None,
        "issue": None,
        "pages": None,
    }
