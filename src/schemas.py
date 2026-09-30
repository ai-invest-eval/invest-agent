"""Shared data shapes exchanged between agents."""

from typing import Any, Literal, NotRequired, TypedDict

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


class CandidateStartup(TypedDict):
    name: str
    country: str
    stage: str
    source_url: str


class PipelineItem(TypedDict):
    indication: str
    stage: str


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


class StartupProfile(TypedDict):
    # TODO(2·5번): 키 생략/None/빈 목록의 의미를 통일. 숫자·bool에 문자열 사용 금지
    # TODO(2·5번): 확인된 없음과 미확인 구분, missing_fields의 필드 경로 규칙 합의
    # TODO(2·5번): 투자·파트너십·팀·선급금·기업가치의 세부 구조 합의
    # TODO(2·5번): 금액의 통화·단위·기준일과 투자/파이프라인 단계 표기 통일
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
    # QD 시장 기준 선택: 자체 신약형 pipeline / 플랫폼형 platform
    # TODO(2·3-B·5번): 복합 사업/정보 부족의 분류 근거와 미확인 처리 합의
    business_model: NotRequired[Literal["pipeline", "platform"] | None]


class Reference(TypedDict):
    # TODO(1·2·3-A·3-B·4·6번): RAG 원문 쪽수와 웹 URL 필수 조건 합의
    # TODO(3-A·3-B·6번): 발행기관/연도 미확인 표현과 중복 출처 식별 규칙 합의
    company: str
    agent: Literal["discovery", "profile", "tech", "market", "competitor"]
    title: str
    source: Literal["RAG", "web"]
    issuer: str | None
    year: int | None
    doc_type: Literal["report", "paper", "web"]
    page: NotRequired[int | str]
    url: NotRequired[str]


class QuestionEvidence(TypedDict):
    """질문 한 개의 채점 근거. missing=True도 결측 기본점을 score에 기록."""

    score: QuestionScore
    rationale: str
    references: list[Reference]
    missing: bool


class InvestmentDecision(TypedDict):
    # area_scores와 total은 0~100, missing_weight는 가중치 합산 비율(0~1)
    # TODO(5·6번): 6개 영역의 고정 키, 반올림과 완전 동점 정렬 규칙 합의
    # TODO(5·6번): hold_reason의 사유 코드와 관문별 상세 설명 형식 합의
    # TODO(5번): QA~QO 15개 존재와 1~5점 범위를 런타임 검증
    # TODO(5번): question_scores와 question_evidence.score 일치 검증
    total: float
    area_scores: dict[str, float]
    question_scores: dict[QuestionKey, QuestionScore]
    question_evidence: dict[QuestionKey, QuestionEvidence]
    verdict: Literal["통과", "보류"]
    hold_reason: str | None
    missing_weight: float
    rationale: str


class EvaluationRecord(InvestmentDecision):
    # 점수 필드는 펼쳐 저장. TODO(5·6번): 보고서에 필요한 추가 필드 합의
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
