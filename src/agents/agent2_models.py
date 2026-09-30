"""Agent 2 LLM 추출 형식 (Pydantic 검증).

LLM은 검색 문서에 적힌 '사실'만 추출하고, 근거 문서 번호(evidence)를 단다.
사업 모델 분류·대표 시장 선정·관문 판정·금액 환산·단계 표기는 코드(agent2_profile.py)가 한다.

값 규칙: null = 문서에서 확인 못 함 / false = 문서가 명시적으로 부정.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.schemas import DevelopmentStage

_FACT_NAMES = {"BoolFact", "IntFact", "StrFact"}


class _Lenient(BaseModel):
    """LLM이 선택 항목에 null을 넣으면 기본값을 쓴다 (예: "clinical_failure": null)."""

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data):
        if not isinstance(data, dict):
            return data
        out = {}
        for k, v in data.items():
            field = cls.model_fields.get(k)
            if v is None and field is not None and not field.is_required():
                continue  # null → 기본값
            if (
                field is not None
                and getattr(field.annotation, "__name__", "") in _FACT_NAMES
                and not isinstance(v, (dict, BaseModel))
            ):
                v = {
                    "value": v
                }  # "listed": false 처럼 값만 온 경우. 근거 번호가 없어 이후 무효 처리
            out[k] = v
        return out


FindStatus = Literal["found", "confirmed_none", "not_found"]
Evidence = list[int]
EVIDENCE_DESC = "근거 문서 번호 목록. 예: [1, 3]"


class BoolFact(_Lenient):
    value: bool | None = Field(None, description="문서에 명시된 경우만 true/false")
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class IntFact(_Lenient):
    value: int | None = None
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class StrFact(_Lenient):
    value: str | None = None
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


# ── overview: 개요·파이프라인·사업 ─────────────────────────────
class PipelineFact(_Lenient):
    indication: str | None = Field(None, description="적응증")
    stage_original: str | None = Field(None, description="문서의 개발 단계 원문 표기")
    stage: DevelopmentStage | None = Field(
        None,
        description="원문 근거에 맞는 팀 공통 단계. 계획·신청을 진입·승인으로 올리지 않음",
    )
    own_rights: bool | None = Field(
        None,
        description="회사가 권리를 가진 자체 물질이면 true, 권리가 제약사에 있으면 false",
    )
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class ServiceFact(_Lenient):
    name: str = Field(description="제약사 대상 서비스·플랫폼 사업명 (예: AI 항체 설계)")
    contract_count: int | None = Field(None, description="문서에 나온 공개 계약 건수")
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class MilestoneFact(_Lenient):
    plan: str = Field(description="회사가 공개한 계획 (예: 2026년 임상 1상 진입)")
    target_date: str | None = Field(None, description="YYYY 또는 YYYY-MM")
    status: Literal["achieved", "on_track", "delayed", "withdrawn"] | None = None
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class OverviewExtraction(_Lenient):
    founded_year: IntFact = Field(default_factory=IntFact)
    platform: StrFact = Field(
        default_factory=StrFact,
        description="핵심 AI 플랫폼 기술 1~2문장 (문서 표현 기반)",
    )
    is_platform_business: BoolFact = Field(
        default_factory=BoolFact,
        description="제약사 대상 설계·서비스·소프트웨어 사업을 하면 true",
    )
    services: list[ServiceFact] = Field(default_factory=list)
    pipeline_status: FindStatus = Field(
        "not_found",
        description="confirmed_none은 자체 파이프라인이 없다고 문서에 명시된 경우만",
    )
    pipeline_status_evidence: Evidence = Field(
        default_factory=list, description="confirmed_none일 때 근거 문서 번호"
    )
    pipeline: list[PipelineFact] = Field(
        default_factory=list, description="회사 공식 자료에 소개된 순서대로"
    )
    revenue_model: StrFact = Field(
        default_factory=StrFact, description="수익 모델 설명"
    )
    has_revenue: BoolFact = Field(
        default_factory=BoolFact, description="실제 매출 발생 여부"
    )
    milestones: list[MilestoneFact] = Field(default_factory=list)


# ── funding: 투자 이력·기업가치 ────────────────────────────────
class InvestorFact(_Lenient):
    name: str | None = None
    kind: Literal["financial", "strategic"] | None = Field(
        None, description="VC 등 재무적 투자자 financial, 제약사·기업 CVC strategic"
    )
    follow_on: bool | None = Field(
        None,
        description="이 라운드 기사에 기존 투자자의 후속 참여라고 명시된 경우만 true",
    )


class FundingFact(_Lenient):
    date: str | None = Field(
        None, description="확인된 정밀도까지 YYYY-MM-DD / YYYY-MM / YYYY"
    )
    stage_original: str | None = Field(
        None, description="라운드 원문 표기 (예: Series B, 시리즈B)"
    )
    market_region: Literal["domestic", "foreign"] | None = Field(
        None,
        description="투자 시장. 국내 투자사·국내 라운드 보도면 domestic, 해외면 foreign. "
        "기업 국적만으로 추정 금지",
    )
    amount_text: str | None = Field(
        None, description="원문 금액 표기 그대로 (예: 420억원, $60 million)"
    )
    investors: list[InvestorFact] | None = None
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class ValuationFact(_Lenient):
    kind: Literal["pre_money", "post_money", "unknown"] = "unknown"
    amount_text: str | None = None
    date: str | None = Field(None, description="기업가치 기준일")
    undisclosed: bool = Field(False, description="기업가치 비공개라고 명시된 경우 true")
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class FundingExtraction(_Lenient):
    status: FindStatus = "not_found"
    status_evidence: Evidence = Field(
        default_factory=list, description="confirmed_none일 때 근거 문서 번호"
    )
    rounds: list[FundingFact] = Field(default_factory=list)
    valuations: list[ValuationFact] = Field(default_factory=list)


# ── team: 경영진 ──────────────────────────────────────────────
class TeamFact(_Lenient):
    name: str | None = None
    role: str | None = Field(None, description="CEO, CTO, CSO 등")
    is_founder: bool | None = None
    full_time: bool | None = Field(None, description="전업 true, 교수 겸직 등은 false")
    degree: str | None = Field(None, description="학위와 전공 (예: 화학 박사)")
    career: str | None = Field(
        None, description="제약사 개발 경력·교수 재직·주요 논문 등 문서에 나온 경력"
    )
    departed: bool | None = Field(None, description="회사를 떠났다고 명시되면 true")
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class TeamExtraction(_Lenient):
    status: FindStatus = "not_found"
    status_evidence: Evidence = Field(
        default_factory=list, description="confirmed_none일 때 근거 문서 번호"
    )
    members: list[TeamFact] = Field(default_factory=list)
    ceo_full_time: BoolFact = Field(default_factory=BoolFact)
    founder_is_current_ceo: BoolFact = Field(default_factory=BoolFact)


# ── partnerships: 제휴·계약·선급금 ─────────────────────────────
class PartnershipFact(_Lenient):
    partner: str | None = None
    kind: Literal[
        "기술이전",
        "공동개발",
        "유료 서비스",
        "공동연구",
        "MOU",
        "정부·학계 협력",
        "기타",
    ] = "기타"
    status: Literal["active", "expanded", "renewed", "terminated"] | None = Field(
        None, description="계약 확대 expanded, 재계약 renewed, 해지 terminated"
    )
    date: str | None = None
    upfront_paid: bool | None = Field(
        None,
        description="선급금 지급 명시 true, 선급금 없음 명시 false, 언급 없으면 null",
    )
    upfront_amount_text: str | None = Field(
        None, description="선급금 원문 금액. 총액 아님"
    )
    evidence: Evidence = Field(default_factory=list, description=EVIDENCE_DESC)


class PartnershipExtraction(_Lenient):
    status: FindStatus = "not_found"
    status_evidence: Evidence = Field(
        default_factory=list, description="confirmed_none일 때 근거 문서 번호"
    )
    partnerships: list[PartnershipFact] = Field(default_factory=list)


# ── 관문 ─────────────────────────────────────────────────────
class EligibilityExtraction(_Lenient):
    listed: BoolFact = Field(
        default_factory=BoolFact, description="상장 true, 비상장 명시 false"
    )
    acquired_or_exited: BoolFact = Field(
        default_factory=BoolFact, description="M&A 등 Exit 완료 true"
    )
    parent_company: StrFact = Field(
        default_factory=StrFact,
        description="모회사 이름 (지분 과반 보유·계열사 편입이 명시된 경우만)",
    )
    parent_is_large_corp: BoolFact = Field(
        default_factory=BoolFact,
        description="대기업·빅테크의 자회사·계열사로 명시되면 true, 독립 기업으로 명시되면 false. "
        "투자·제휴·공동개발 관계는 자회사가 아님",
    )
    independent_vc_backed: BoolFact = Field(
        default_factory=BoolFact, description="외부 VC 투자로 운영되는 독립 기업 true"
    )


class RiskExtraction(_Lenient):
    clinical_failure: BoolFact = Field(
        default_factory=BoolFact,
        description="주력 파이프라인 임상 중단·실패 보도 true. "
        "최근 정상 진행 근거가 있으면 false, 판단 불가 null",
    )
    founder_exit_or_dispute: BoolFact = Field(
        default_factory=BoolFact,
        description="창업자·CEO 이탈 또는 경영권 분쟁 보도 true. 판단 불가 null",
    )
    patent_loss: BoolFact = Field(
        default_factory=BoolFact, description="핵심 특허 분쟁 패소 true. 판단 불가 null"
    )
    restructuring: BoolFact = Field(
        default_factory=BoolFact,
        description="구조조정·대규모 감원 보도 true. 판단 불가 null",
    )


GROUP_MODELS: dict[str, type[BaseModel]] = {
    "overview": OverviewExtraction,
    "funding": FundingExtraction,
    "team": TeamExtraction,
    "partnerships": PartnershipExtraction,
    "eligibility": EligibilityExtraction,
    "risk": RiskExtraction,
}


# (상태 필드, 목록 필드, 상태 근거 필드). 코드가 found/confirmed_none/not_found를 검증한다.
STATUS_FIELDS = {
    "overview": ("pipeline_status", "pipeline", "pipeline_status_evidence"),
    "funding": ("status", "rounds", "status_evidence"),
    "team": ("status", "members", "status_evidence"),
    "partnerships": ("status", "partnerships", "status_evidence"),
}
