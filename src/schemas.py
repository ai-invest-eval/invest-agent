"""Shared data shapes exchanged between agents."""

from typing import Any, Literal, NotRequired, TypedDict


class CandidateStartup(TypedDict):
    name: str
    country: str
    stage: str
    source_url: str


class PipelineItem(TypedDict):
    indication: str
    stage: str


class GateChecks(TypedDict):
    not_eligible: bool | None
    subsidiary_of_large_corp: bool | None
    clinical_failure: bool | None
    founder_exit_or_dispute: bool | None
    patent_loss: bool | None
    funding_gap_restructuring: bool | None


class StartupProfile(TypedDict):
    # TODO(2번): 결측값 표현 방식 합의 필요 (키 생략 / None / "정보 없음")
    # TODO(2번): 투자 이력·파트너십·팀·선급금·기업가치의 세부 구조 확정 필요
    name: str
    gates: GateChecks
    missing_fields: list[str]
    founded_year: NotRequired[int | None]
    platform: NotRequired[str | None]
    pipeline: NotRequired[list[PipelineItem]]
    funding_history: NotRequired[list[dict[str, Any]]]
    partnerships: NotRequired[list[dict[str, Any]]]
    team: NotRequired[list[dict[str, Any]]]
    founder_degree_career: NotRequired[str | None]
    ceo_full_time: NotRequired[bool | None]
    upfront_payment: NotRequired[dict[str, Any] | None]
    pre_money_valuation: NotRequired[dict[str, Any] | None]
    lead_indication: NotRequired[str | None]


class InvestmentDecision(TypedDict):
    # TODO(5번): 영역별 점수 단위와 QA~QO 질문 키·점수 범위 확정 필요
    total: float
    area_scores: dict[str, float]
    question_scores: dict[str, int]
    verdict: Literal["통과", "보류"]
    hold_reason: str | None
    missing_weight: float
    rationale: str


class EvaluationRecord(InvestmentDecision):
    # TODO(5·6번): investment_decision 저장 구조 합의 필요 (펼침 / 중첩)
    name: str
    startup_profile: StartupProfile
    tech_analysis: str
    market_analysis: str
    competitor_analysis: str


class Reference(TypedDict):
    # TODO(3-A·3-B·4번): 출처별 page/url 필수 조건과 누락 메타데이터 표현 확정 필요
    company: str
    agent: Literal["discovery", "profile", "tech", "market", "competitor"]
    title: str
    source: Literal["RAG", "web"]
    issuer: str | None
    year: int | None
    doc_type: Literal["report", "paper", "web"]
    page: NotRequired[int | str]
    url: NotRequired[str]


class StartupSearchUpdate(TypedDict):
    candidate_startups: list[CandidateStartup]
    selected_startup: CandidateStartup | None
    references: list[Reference]


class CompanyProfileUpdate(TypedDict):
    startup_profile: StartupProfile
    references: list[Reference]


class TechAnalysisUpdate(TypedDict):
    tech_analysis: str
    references: list[Reference]


class MarketAnalysisUpdate(TypedDict):
    market_analysis: str
    references: list[Reference]


class CompetitorAnalysisUpdate(TypedDict):
    competitor_analysis: str
    references: list[Reference]


class InvestmentDecisionUpdate(TypedDict):
    investment_decision: InvestmentDecision
    evaluation_history: list[EvaluationRecord]


class ReportUpdate(TypedDict):
    final_report: str
