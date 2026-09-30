"""Shared data shapes exchanged between agents."""

from typing import Literal, NotRequired, TypedDict

QuestionKey = Literal[
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
QuestionScore = Literal[1, 2, 3, 4, 5]
AreaKey = Literal["founder", "market", "product", "moat", "traction", "deal"]
RiskGateKey = Literal[
    "clinical_failure",
    "founder_exit_or_dispute",
    "patent_loss",
    "funding_gap_restructuring",
]
StageRegion = Literal["domestic", "foreign"]
DevelopmentStage = Literal[
    # 복합 임상 표기를 보존한다. 임상 1/2상을 임상 2상으로 승격하지 않는다.
    "개념",
    "컴퓨터 예측",
    "실험 검증",
    "전임상",
    "IND 신청",
    "IND 승인",
    "임상 1상",
    "임상 1/2상",
    "임상 2상",
    "임상 2/3상",
    "임상 3상",
    "허가 신청",
    "허가 승인",
]


class MonetaryAmount(TypedDict):
    """기본 통화 단위의 숫자. 보고서 표시는 docs/data_contracts.md 참조."""

    original_amount: float | None
    original_currency: str | None
    krw_amount: float | None
    usd_amount: float | None
    fx_date: str | None
    fx_source: str | None


class CandidateStartup(TypedDict):
    name: str
    country: str | None
    # 국내 시리즈 A / 해외 시리즈 AF. F는 팀 표식이며 단계 순위가 아니다.
    stage: str | None
    stage_region: NotRequired[StageRegion | None]
    stage_original: NotRequired[str | None]
    source_url: str | None


class PipelineItem(TypedDict):
    indication: str | None
    stage: DevelopmentStage | None
    stage_original: NotRequired[str | None]


class GateChecks(TypedDict):
    # True: 치명 리스크 확인, False: 해당 없음 확인, None: 미확인
    # 자격 관문(not_eligible, subsidiary_of_large_corp)이 None이면 보류(자격 미확인)
    # 다른 리스크 관문의 None은 평가를 진행하되 보고서에 미확인으로 표시한다.
    # None을 False로 덮어쓰지 않아 보고서가 미확인 상태를 보존하도록 한다.
    not_eligible: bool | None
    subsidiary_of_large_corp: bool | None
    clinical_failure: bool | None
    founder_exit_or_dispute: bool | None
    patent_loss: bool | None
    funding_gap_restructuring: bool | None


class BusinessModelBasis(TypedDict):
    reason: str
    source: str | None


class Investor(TypedDict):
    name: str | None
    kind: Literal["financial", "strategic"] | None
    follow_on: bool | None


class FundingRound(TypedDict):
    date: str | None
    stage: str | None
    stage_region: StageRegion | None
    stage_original: str | None
    amount: MonetaryAmount | None
    investors: list[Investor] | None
    references: list["Reference"]


class Partnership(TypedDict):
    partner: str | None
    kind: str | None
    date: str | None
    upfront_payment: MonetaryAmount | None
    references: list["Reference"]


class TeamMember(TypedDict):
    name: str | None
    role: str | None
    is_founder: bool | None
    full_time: bool | None
    degree: str | None
    career: str | None
    references: list["Reference"]


class UpfrontPaymentBasis(TypedDict):
    partner: str | None
    date: str | None
    references: list["Reference"]


class StartupProfile(TypedDict):
    # 미확인 None / 확인된 없음 []·False·0. 날짜·단계는 docs/data_contracts.md 참조
    # missing_fields는 프로필 기준 점 경로. 수집 결과는 선택 필드도 키를 유지한다.
    # 투자·파트너십·팀의 내부 구조는 아래 타입 고정. 상세 규칙은 공통 계약 참조
    name: str
    gates: GateChecks
    missing_fields: list[str]
    founded_year: NotRequired[int | None]
    platform: NotRequired[str | None]
    pipeline: NotRequired[list[PipelineItem] | None]
    funding_history: NotRequired[list[FundingRound] | None]
    partnerships: NotRequired[list[Partnership] | None]
    team: NotRequired[list[TeamMember] | None]
    founder_degree_career: NotRequired[str | None]
    ceo_full_time: NotRequired[bool | None]
    upfront_payment: NotRequired[MonetaryAmount | None]
    upfront_payment_basis: NotRequired[UpfrontPaymentBasis | None]
    pre_money_valuation: NotRequired[MonetaryAmount | None]
    valuation_date: NotRequired[str | None]
    valuation_references: NotRequired[list["Reference"]]
    lead_indication: NotRequired[str | None]
    lead_service: NotRequired[str | None]
    # 2번만 분류. 자체 후보물질 권리 보유면 pipeline, 미확인은 unknown (QD 결측).
    # 일반 결측 None 규칙의 명시적 예외. 3-B·5번은 재분류하지 않는다.
    business_model: NotRequired[Literal["pipeline", "platform", "unknown"]]
    business_model_basis: NotRequired[BusinessModelBasis | None]


class Reference(TypedDict):
    # 실제 활용 출처만 저장. 유형별 REFERENCE 표기는 docs/data_contracts.md 참조
    # page는 RAG 원문 인용 쪽수, pages는 논문 전체 수록 페이지다.
    company: str
    agent: Literal["discovery", "profile", "tech", "market", "competitor"]
    title: str
    source: Literal["RAG", "web"]
    issuer: str | None
    year: int | None
    doc_type: Literal["report", "paper", "web"]
    page: NotRequired[int | str | None]
    url: NotRequired[str | None]
    authors: NotRequired[list[str] | None]
    published_date: NotRequired[str | None]
    site_name: NotRequired[str | None]
    journal: NotRequired[str | None]
    volume: NotRequired[str | None]
    issue: NotRequired[str | None]
    pages: NotRequired[str | None]


class QuestionEvidence(TypedDict):
    """질문 한 개의 채점 근거. missing=True도 결측 기본점을 score에 기록."""

    score: QuestionScore
    rationale: str
    references: list[Reference]
    missing: bool


class InvestmentDecision(TypedDict):
    # area_scores와 total은 0~100, missing_weight는 가중치 합산 비율(0~1)
    # 영역 키·보류 사유·정렬 기준은 투자평가기준 v4를 따른다.
    # 판정·정렬 전 반올림 금지. 기준 문서에 없는 추가 채점·동점 기준을 만들지 않는다.
    # TODO(5번): QA~QO 15개 존재와 1~5점 범위를 런타임 검증
    # TODO(5번): question_scores와 question_evidence.score 일치 검증
    total: float
    area_scores: dict[AreaKey, float]
    question_scores: dict[QuestionKey, QuestionScore]
    question_evidence: dict[QuestionKey, QuestionEvidence]
    verdict: Literal["통과", "보류"]
    hold_reason: str | None
    unconfirmed_gates: list[RiskGateKey]
    missing_weight: float
    rationale: str


class EvaluationRecord(InvestmentDecision):
    # 점수 필드는 펼쳐 저장하고 해당 기업의 프로필·분석을 함께 보존한다.
    name: str
    startup_profile: StartupProfile
    tech_analysis: str
    market_analysis: str
    competitor_analysis: str


class StartupSearchUpdate(TypedDict):
    candidate_startups: list[CandidateStartup]
    selected_startup: CandidateStartup | None
    references: list[Reference]
    # 최초 선택/다음 후보 선택 시 현재 기업 분석값만 초기화한다.
    startup_profile: None
    tech_analysis: str
    market_analysis: str
    competitor_analysis: str
    investment_decision: None


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
