"""Agent 2 단독 검증 (가짜 검색·LLM, API 키 불필요).

실행: uv run --with pytest python -m pytest -q tests/test_agent2_profile.py
모든 기업·금액·URL은 가상이다.
"""

import json
from datetime import date

import pytest

from src.agents import agent2_utils as u
from src.agents.agent2_models import (
    EligibilityExtraction,
    FundingExtraction,
    OverviewExtraction,
    PartnershipExtraction,
    RiskExtraction,
    TeamExtraction,
)
from src.agents.agent2_profile import CompanyProfileAgent

TODAY = date(2026, 9, 30)


def doc(n: int, title: str = "가상 문서") -> dict:
    return {
        "url": f"https://example.invalid/doc{n}?utm_source=x",
        "title": f"{title} {n}",
        "content": f"가상 본문 {n}",
        "published_date": "2026-06-15",
    }


class FakeSearch:
    """주제별 검색어의 앞부분으로 결과를 돌려준다. 호출 기록을 남긴다."""

    def __init__(self, table: dict[str, list[dict]], fail: bool = False):
        self.table, self.fail, self.calls = table, fail, []

    def __call__(self, query: str) -> dict:
        self.calls.append(query)
        if self.fail:
            raise ConnectionError("Tavily 연결 실패")
        for key, rows in self.table.items():
            if key in query:
                return {"results": rows}
        return {"results": []}


class FakeExtract:
    """모델 클래스별 응답 큐. 비면 빈 모델(not_found)을 돌려준다."""

    def __init__(self, answers: dict[type, list], fail_on: set[type] | None = None):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.fail_on = fail_on or set()

    def __call__(self, model_cls, system, human):
        if model_cls in self.fail_on:
            raise TimeoutError("OpenAI 시간 초과")
        queue = self.answers.get(model_cls, [])
        return queue.pop(0) if queue else model_cls()


def fact(value, *ev):
    return {"value": value, "evidence": list(ev)}


# ── 시나리오 1: 파이프라인형 (국내 기업, 해외 라운드) ────────────
PIPELINE_SEARCH = {
    "파이프라인": [doc(1, "IR")],
    "투자 유치": [doc(2, "투자 기사")],
    "대표 창업자": [doc(3, "인터뷰")],
    "공동연구": [doc(4, "계약 기사")],
    "상장 인수": [doc(5, "기업 정보")],
    "임상 중단": [doc(6, "뉴스"), doc(9, "읽기만 한 문서")],
}
# 문서 번호는 검색 순서대로 1부터 매겨진다: doc1~doc6 → 1~6, doc9 → 7
PIPELINE_ANSWERS = {
    OverviewExtraction: [
        {
            "founded_year": fact(2020, 1),
            "platform": fact("AI 기반 항체 설계", 1),
            "is_platform_business": fact(False, 1),
            "pipeline_status": "found",
            "pipeline": [
                {  # LLM이 1/2상을 2상으로 올린 오류 → 코드가 1/2상으로 되돌림
                    "indication": "비소세포폐암",
                    "stage_original": "Phase 1/2 진행 중",
                    "stage": "임상 2상",
                    "own_rights": True,
                    "evidence": [1],
                },
                {
                    "indication": "유방암",
                    "stage_original": "전임상",
                    "stage": "전임상",
                    "own_rights": True,
                    "evidence": [1],
                },
                {  # 계획을 진입으로 승격 → 코드가 None 처리, 제약사 권리
                    "indication": "간암",
                    "stage_original": "임상 2상 진입 예정",
                    "stage": "임상 2상",
                    "own_rights": False,
                    "evidence": [1],
                },
            ],
            "revenue_model": fact("기술이전", 99),  # 존재하지 않는 근거 번호
        }
    ],
    FundingExtraction: [
        {
            "status": "found",
            "rounds": [
                {
                    "date": "2026-06-15",
                    "stage_original": "Series B",
                    "market_region": "foreign",
                    "amount_text": "$30 million",
                    "investors": [
                        {"name": "가상 VC", "kind": "financial", "follow_on": True}
                    ],
                    "evidence": [2],
                },
                {
                    "date": "2024.3",
                    "stage_original": "시리즈A",
                    "market_region": "domestic",
                    "amount_text": "100억원",
                    "evidence": [2],
                },
            ],
            "valuations": [
                {
                    "kind": "post_money",
                    "amount_text": "$200 million",
                    "date": "2026-06",
                    "evidence": [2],
                },
                {
                    "kind": "pre_money",
                    "amount_text": "$144 million",
                    "date": "2026-06-15",
                    "evidence": [2],
                },
            ],
        }
    ],
    TeamExtraction: [
        {
            "status": "found",
            "members": [
                {
                    "name": "가상 창업자",
                    "role": "CEO",
                    "is_founder": True,
                    "full_time": True,
                    "degree": "생명과학 박사",
                    "career": "제약사 신약개발 10년",
                    "evidence": [3],
                },
                {
                    "name": "가상 공동창업자",
                    "role": "CTO",
                    "is_founder": True,
                    "departed": True,
                    "evidence": [3],
                },
            ],
            "ceo_full_time": fact(True, 3),
            "founder_is_current_ceo": fact(True, 3),
        }
    ],
    PartnershipExtraction: [
        {
            "status": "found",
            "partnerships": [
                {
                    "partner": "가상 제약사 A",
                    "kind": "공동개발",
                    "status": "expanded",
                    "date": "2026-06",
                    "upfront_paid": True,
                    "upfront_amount_text": "$5 million",
                    "evidence": [4],
                },
                {
                    "partner": "가상 제약사 B",
                    "kind": "공동연구",
                    "date": "2025-01",
                    "evidence": [4],
                },
            ],
        }
    ],
    EligibilityExtraction: [
        {"listed": fact(False, 5), "parent_is_large_corp": fact(False, 5)}
    ],
    RiskExtraction: [{}],
}


@pytest.fixture
def pipeline_run():
    search = FakeSearch(PIPELINE_SEARCH)
    agent = CompanyProfileAgent(search, FakeExtract(PIPELINE_ANSWERS), today=TODAY)
    state = {
        "selected_startup": {
            "name": "가상바이오",
            "country": "KR",
            "stage": "시리즈 BF",
            "source_url": None,
        }
    }
    return agent(state), search


def test_update_returns_only_contract_keys(pipeline_run):
    update, _ = pipeline_run
    assert set(update) == {"startup_profile", "references"}
    json.dumps(update, ensure_ascii=False)  # State에 넣을 수 있는 JSON 형태


def test_pipeline_business_model_and_lead(pipeline_run):
    p = pipeline_run[0]["startup_profile"]
    assert p["business_model"] == "pipeline"
    assert p["lead_indication"] == "비소세포폐암" and p["lead_service"] is None
    assert "임상 1/2상" in p["business_model_basis"]["reason"]
    assert p["business_model_basis"]["source"].startswith(
        "https://example.invalid/doc1"
    )


def test_dev_stage_not_promoted(pipeline_run):
    stages = [x["stage"] for x in pipeline_run[0]["startup_profile"]["pipeline"]]
    assert stages == ["임상 1/2상", "전임상", None]


def test_funding_stage_amount_and_order(pipeline_run):
    rounds = pipeline_run[0]["startup_profile"]["funding_history"]
    assert [r["stage"] for r in rounds] == ["시리즈 A", "시리즈 BF"]
    assert rounds[0]["date"] == "2024-03"
    assert rounds[1]["amount"] == {
        "original_amount": 30000000,
        "original_currency": "USD",
        "krw_amount": 42000000000,
        "usd_amount": 30000000,
        "fx_date": None,
        "fx_source": u.FX_SOURCE_USD,
    }
    assert rounds[0]["amount"]["krw_amount"] == 10000000000
    assert rounds[0]["amount"]["usd_amount"] is None  # 원화는 달러 환산값을 만들지 않음


def test_valuation_uses_pre_money_only(pipeline_run):
    p = pipeline_run[0]["startup_profile"]
    assert p["pre_money_valuation"]["usd_amount"] == 144000000
    assert p["valuation_date"] == "2026-06-15"
    assert p["valuation_references"][0]["agent"] == "profile"


def test_upfront_representative_not_sum(pipeline_run):
    p = pipeline_run[0]["startup_profile"]
    assert p["upfront_payment"]["usd_amount"] == 5000000
    assert p["upfront_payment_basis"]["partner"] == "가상 제약사 A"
    assert p["partnerships"][0]["kind"] == "공동개발 (계약 확대)"
    assert p["partnerships"][1]["upfront_payment"] is None


def test_team_and_departed_cofounder(pipeline_run):
    p = pipeline_run[0]["startup_profile"]
    assert p["ceo_full_time"] is True
    assert p["team"][1]["role"] == "CTO (퇴사)"
    assert "가상 공동창업자" not in p["founder_degree_career"]
    assert "생명과학 박사" in p["founder_degree_career"]


def test_gates(pipeline_run):
    g = pipeline_run[0]["startup_profile"]["gates"]
    assert g == {
        "not_eligible": False,
        "subsidiary_of_large_corp": False,
        "clinical_failure": None,  # 근거 없음 → 미확인 유지
        "founder_exit_or_dispute": False,  # 창업자 현 대표 확인
        "patent_loss": None,
        "funding_gap_restructuring": False,  # 최근 투자 3개월 전
    }
    assert all(v in (True, False, None) for v in g.values())


def test_missing_fields_paths(pipeline_run):
    missing = pipeline_run[0]["startup_profile"]["missing_fields"]
    assert "gates.clinical_failure" in missing and "gates.patent_loss" in missing
    assert "funding_history.0.investors" in missing
    assert "partnerships.1.upfront_payment" in missing
    assert "pre_money_valuation" not in missing and "pipeline" not in missing


def test_references_only_used_and_deduplicated(pipeline_run):
    update, _ = pipeline_run
    urls = [r["url"] for r in update["references"]]
    assert len(urls) == len(set(urls))
    assert not any("doc9" in x for x in urls)  # 읽기만 한 문서는 제외
    assert all(
        r["agent"] == "profile" and r["company"] == "가상바이오"
        for r in update["references"]
    )
    assert all(
        r["year"] == 2026 and r["published_date"] == "2026-06-15"
        for r in update["references"]
    )


def test_no_retry_when_complete(pipeline_run):
    _, search = pipeline_run
    assert len(search.calls) == 6


def test_korean_queries_for_domestic(pipeline_run):
    _, search = pipeline_run
    assert all("가상바이오" in q for q in search.calls)
    assert any("투자 유치" in q for q in search.calls)


# ── 시나리오 2: 플랫폼형 (해외 기업, 재검색으로 보완) ──────────────
def test_platform_with_retry():
    search = FakeSearch(
        {
            "pipeline candidate": [doc(1)],  # 첫 검색: 추출 결과 없음
            "company overview": [doc(2, "About")],  # 재검색
            "partnership": [doc(3)],
            "subsidiary": [doc(4)],
        }
    )
    answers = {
        OverviewExtraction: [
            {},
            {
                # 문서 번호: 첫 검색 doc1=1, partnership doc3=2, subsidiary doc4=3, 재검색 doc2=4
                "platform": fact("AI antibody design platform", 4),
                "is_platform_business": fact(True, 4),
                "services": [
                    {"name": "AI 항체 설계", "contract_count": 3, "evidence": [4]},
                    {"name": "구조 예측", "contract_count": 1, "evidence": [4]},
                ],
                "pipeline_status": "confirmed_none",
                "pipeline_status_evidence": [4],
            },
        ],
        PartnershipExtraction: [
            {
                "status": "found",
                "partnerships": [
                    {
                        "partner": "Pharma B",
                        "kind": "유료 서비스",
                        "date": "2026-04",
                        "upfront_paid": False,
                        "evidence": [2],
                    }
                ],
            }
        ],
        EligibilityExtraction: [{"independent_vc_backed": fact(True, 3)}],
    }
    agent = CompanyProfileAgent(search, FakeExtract(answers), today=TODAY)
    update = agent(
        {
            "selected_startup": {
                "name": "Virtual Platform",
                "country": "US",
                "stage": None,
                "source_url": None,
            }
        }
    )
    p = update["startup_profile"]
    assert p["business_model"] == "platform"
    assert p["lead_service"] == "AI 항체 설계" and p["lead_indication"] is None
    assert "자체 파이프라인 없음 확인" in p["business_model_basis"]["reason"]
    assert p["pipeline"] == []
    assert p["gates"]["clinical_failure"] is False  # 파이프라인 없음 확인
    assert p["gates"]["subsidiary_of_large_corp"] is False
    assert p["gates"]["not_eligible"] is None  # 비상장·단계 모두 미확인
    assert p["upfront_payment"]["original_amount"] == 0  # 선급금 없음 확인
    assert p["funding_history"] is None and "funding_history" in p["missing_fields"]
    overview_calls = [
        q
        for q in search.calls
        if "Virtual Platform AI drug" in q or "company overview" in q
    ]
    assert len(overview_calls) == 2  # 첫 검색 + 재검색 1회
    assert all("Virtual Platform" in q for q in search.calls)


# ── 시나리오 3: 미확인·자격 미달·오류 ────────────────────────────
def test_unknown_business_model_and_hallucinated_evidence():
    search = FakeSearch({"상장 인수": [doc(1)], "투자 유치": [doc(2)]})
    answers = {
        OverviewExtraction: [{"platform": fact("가짜 플랫폼", 42)}, {}],
        FundingExtraction: [
            {
                "status": "found",
                "rounds": [
                    {"date": "2025", "stage_original": "Series D", "evidence": [1]}
                ],
            }  # 투자 기사가 1번 문서
        ],
        EligibilityExtraction: [{"listed": fact(None)}],
    }
    agent = CompanyProfileAgent(search, FakeExtract(answers), today=TODAY)
    p = agent(
        {
            "selected_startup": {
                "name": "가상미확인",
                "country": "KR",
                "stage": None,
                "source_url": None,
            }
        }
    )["startup_profile"]
    assert p["platform"] is None  # 근거 번호 42는 없는 문서 → 폐기
    assert p["business_model"] == "unknown" and "business_model" in p["missing_fields"]
    assert p["business_model_basis"]["source"] is None
    assert p["gates"]["not_eligible"] is True  # 시리즈 D
    assert p["funding_history"][0]["stage"] == "시리즈 D"
    assert p["funding_history"][0]["stage_region"] is None


def test_all_search_failures_raise():
    agent = CompanyProfileAgent(FakeSearch({}, fail=True), FakeExtract({}), today=TODAY)
    with pytest.raises(RuntimeError):
        agent(
            {
                "selected_startup": {
                    "name": "가상",
                    "country": "KR",
                    "stage": None,
                    "source_url": None,
                }
            }
        )


def test_partial_llm_failure_keeps_none():
    search = FakeSearch(PIPELINE_SEARCH)
    agent = CompanyProfileAgent(
        search, FakeExtract(PIPELINE_ANSWERS, fail_on={TeamExtraction}), today=TODAY
    )
    p = agent(
        {
            "selected_startup": {
                "name": "가상바이오",
                "country": "KR",
                "stage": None,
                "source_url": None,
            }
        }
    )["startup_profile"]
    assert p["team"] is None and "team" in p["missing_fields"]  # 확인된 없음([]) 아님
    assert p["business_model"] == "pipeline"


def test_requires_selected_startup():
    agent = CompanyProfileAgent(FakeSearch({}), FakeExtract({}), today=TODAY)
    with pytest.raises(ValueError):
        agent({"selected_startup": None})


# ── 순수 함수 ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text, expected",
    [
        ("420억원", (42000000000, "KRW")),
        ("$60 million", (60000000, "USD")),
        ("US$130M", (130000000, "USD")),
        ("1억3000만 달러", (130000000, "USD")),
        ("3천만 달러", (30000000, "USD")),
        ("1조 2000억원", (1200000000000, "KRW")),
        ("EUR 10 million", (10000000, "EUR")),
        (None, (None, None)),
    ],
)
def test_parse_amount(text, expected):
    assert u.parse_amount(text) == expected


def test_money_other_currency_not_converted():
    m = u.money_from_text("EUR 10 million")
    assert (
        m["krw_amount"] is None and m["usd_amount"] is None and m["fx_source"] is None
    )


@pytest.mark.parametrize(
    "original, expected",
    [
        ("Series B", "시리즈 B"),
        ("시리즈A", "시리즈 A"),
        ("Pre-A", "프리 시리즈 A"),
        ("프리A", "프리 시리즈 A"),
        ("Seed", "시드"),
        ("pre-seed", "프리시드"),
        ("Series B extension", "시리즈 B"),
        ("bridge", "브리지"),
        ("angel", None),
    ],
)
def test_round_base(original, expected):
    assert u.round_base(original) == expected


def test_stage_label_suffix():
    assert u.stage_label("시리즈 A", "foreign") == "시리즈 AF"
    assert u.stage_label("시리즈 A", None) == "시리즈 A"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2025", "2025"),
        ("2025.3", "2025-03"),
        ("2025-03-14", "2025-03-14"),
        ("2025년 3월", "2025-03"),
        (None, None),
        ("미상", None),
    ],
)
def test_normalize_date_keeps_precision(text, expected):
    assert u.normalize_date(text) == expected


@pytest.mark.parametrize(
    "stage, original, expected",
    [
        ("임상 2상", "Phase I/II", "임상 1/2상"),
        ("임상 3상", "Phase 2/3", "임상 2/3상"),
        ("IND 승인", "IND 신청 예정", None),
        ("전임상", "전임상", "전임상"),
        ("임상 1상", None, "임상 1상"),
    ],
)
def test_guard_dev_stage(stage, original, expected):
    assert u.guard_dev_stage(stage, original) == expected


def test_sanitize_drops_unsupported_values():
    from src.agents.agent2_profile import _sanitize

    model = OverviewExtraction.model_validate(
        {
            "platform": fact("근거 없는 주장", 42),
            "founded_year": fact(2020, 1, 42),
            "pipeline_status": "confirmed_none",  # 근거 번호 없음 → not_found
            "pipeline": [],
        }
    )
    clean = _sanitize("overview", model, allowed={1})
    assert clean.platform.value is None
    assert clean.founded_year.value == 2020 and clean.founded_year.evidence == [1]
    assert clean.pipeline_status == "not_found"


# ── 실제 실행(갤럭스) 결과에서 발견한 문제 재현 ────────────────
def test_recent_private_round_supports_eligibility_and_team_fixes():
    search = FakeSearch({"투자 유치": [doc(1)], "대표 창업자": [doc(2)]})
    answers = {
        FundingExtraction: [
            {
                "status": "found",
                "rounds": [
                    {
                        "date": "2026-02-10",
                        "stage_original": "시리즈B",
                        "market_region": "domestic",
                        "amount_text": "420억원",
                        "investors": [{"name": "가상 VC", "kind": "financial"}],
                        "evidence": [1],
                    }
                ],
            }
        ],
        TeamExtraction: [
            {
                "status": "found",
                "members": [
                    {  # LLM이 현직 교수를 전업으로 표시한 모순
                        "name": "가상 교수",
                        "role": "대표이사",
                        "is_founder": True,
                        "full_time": True,
                        "career": "서울대 화학부 교수 (현직)",
                        "evidence": [2],
                    },
                    {
                        "name": "가상 각자대표",
                        "role": "대표이사",
                        "is_founder": True,
                        "full_time": True,
                        "evidence": [2],
                    },
                ],
            }
        ],
    }
    agent = CompanyProfileAgent(search, FakeExtract(answers), today=TODAY)
    p = agent(
        {
            "selected_startup": {
                "name": "가상갤",
                "country": "KR",
                "stage": None,
                "source_url": None,
            }
        }
    )["startup_profile"]
    assert p["gates"]["not_eligible"] is False  # 7개월 전 시리즈 B 사모 투자
    assert p["gates"]["subsidiary_of_large_corp"] is False  # 재무적 투자자 주도
    assert p["team"][0]["full_time"] is False  # 현직 교수 → 겸임
    assert p["ceo_full_time"] is True  # 각자대표 중 전업 대표 존재
    # 설립 연도 미확인 → 개요 재검색 1회
    assert sum("회사 소개" in q for q in search.calls) == 1


def test_old_round_does_not_support_eligibility():
    search = FakeSearch({"투자 유치": [doc(1)]})
    answers = {
        FundingExtraction: [
            {
                "status": "found",
                "rounds": [
                    {"date": "2023", "stage_original": "Series A", "evidence": [1]}
                ],
            }
        ]
    }
    agent = CompanyProfileAgent(search, FakeExtract(answers), today=TODAY)
    p = agent(
        {
            "selected_startup": {
                "name": "가상오래",
                "country": "KR",
                "stage": None,
                "source_url": None,
            }
        }
    )["startup_profile"]
    assert p["gates"]["not_eligible"] is None  # 오래된 라운드는 보조 근거가 아님


def test_llm_nulls_use_defaults():
    """실제 실행에서 LLM이 선택 항목에 null을 넣어 검증 오류가 난 경우."""
    risk = RiskExtraction.model_validate(
        {"clinical_failure": None, "founder_exit_or_dispute": None, "patent_loss": None}
    )
    assert risk.clinical_failure.value is None and risk.clinical_failure.evidence == []
    elig = EligibilityExtraction.model_validate(
        {"listed": {"value": False, "evidence": None}, "acquired_or_exited": None}
    )
    assert elig.listed.value is False and elig.listed.evidence == []
    team = TeamExtraction.model_validate({"status": None, "members": None})
    assert team.status == "not_found" and team.members == []


def test_professor_without_status_is_not_full_time_confirmed():
    search = FakeSearch({"대표 창업자": [doc(1)], "파이프라인": [doc(2)]})
    answers = {
        TeamExtraction: [
            {
                "status": "found",
                "members": [
                    {
                        "name": "가상 교수",
                        "role": "대표이사",
                        "full_time": True,
                        "career": "2004년 서울대 화학부 교수",
                        "evidence": [2],  # 검색 순서상 팀 문서가 2번
                    }
                ],
            }
        ],
        OverviewExtraction: [
            {
                "pipeline_status": "found",
                "pipeline": [
                    {
                        "indication": "면역항암제",
                        "stage_original": "전임상",
                        "stage": "전임상",
                        "own_rights": True,
                        "evidence": [1],
                    }
                ],
            }
        ],
    }
    agent = CompanyProfileAgent(search, FakeExtract(answers), today=TODAY)
    p = agent(
        {
            "selected_startup": {
                "name": "가상교수",
                "country": "KR",
                "stage": None,
                "source_url": None,
            }
        }
    )["startup_profile"]
    assert p["team"][0]["full_time"] is None  # 교수직 유지 여부 불명
    assert p["lead_indication"] == "암 (치료 영역 기준, 세부 적응증 미확인)"
    assert p["pipeline"][0]["indication"] == p["lead_indication"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("비소세포폐암", "비소세포폐암"),
        ("PD-1 이중항체", None),
        ("면역항암제", "암 (치료 영역 기준, 세부 적응증 미확인)"),
        ("자가면역질환", "자가면역질환"),
        (None, None),
    ],
)
def test_indication_guard(text, expected):
    from src.agents.agent2_profile import _indication

    assert _indication(text) == expected


def _subsidiary_case(eligibility: dict) -> dict:
    search = FakeSearch(
        {"투자 유치": [doc(1)], "공동연구": [doc(2)], "상장 인수": [doc(3)]}
    )
    answers = {
        FundingExtraction: [
            {
                "status": "found",
                "rounds": [
                    {
                        "date": "2026-02-10",
                        "stage_original": "시리즈B",
                        "investors": [{"name": "가상 VC", "kind": "financial"}],
                        "evidence": [1],
                    }
                ],
            }
        ],
        PartnershipExtraction: [
            {
                "status": "found",
                "partnerships": [
                    {"partner": "가상화학", "kind": "공동개발", "evidence": [2]}
                ],
            }
        ],
        EligibilityExtraction: [eligibility],
    }
    agent = CompanyProfileAgent(search, FakeExtract(answers), today=TODAY)
    state = {
        "selected_startup": {
            "name": "가상자회사",
            "country": "KR",
            "stage": None,
            "source_url": None,
        }
    }
    return agent(state)["startup_profile"]["gates"]


def test_partner_is_not_parent():
    """실제 실행에서 제휴사를 모회사로 오인해 subsidiary=true가 나온 경우."""
    gates = _subsidiary_case(
        {
            "parent_is_large_corp": fact(True, 3),
            "parent_company": fact("(주)가상화학", 3),
        }
    )
    assert (
        gates["subsidiary_of_large_corp"] is False
    )  # 제휴사 → 모회사 아님, VC 투자로 독립


def test_parent_without_name_is_not_confirmed():
    gates = _subsidiary_case({"parent_is_large_corp": fact(True, 3)})
    assert gates["subsidiary_of_large_corp"] is False


def test_real_parent_is_confirmed():
    gates = _subsidiary_case(
        {
            "parent_is_large_corp": fact(True, 3),
            "parent_company": fact("가상 빅테크", 3),
        }
    )
    assert gates["subsidiary_of_large_corp"] is True


def test_bare_value_instead_of_fact_does_not_crash():
    """실제 실행에서 LLM이 "parent_is_large_corp": false 처럼 값만 보낸 경우."""
    elig = EligibilityExtraction.model_validate({"parent_is_large_corp": False})
    assert elig.parent_is_large_corp.value is False
    assert elig.parent_is_large_corp.evidence == []  # 근거 없음 → _sanitize에서 무효
