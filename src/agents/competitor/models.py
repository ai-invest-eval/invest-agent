"""4번의 LLM 구조화 출력 모델. 공용 State와 스키마는 src에서 가져온다."""

from typing import Literal

from pydantic import BaseModel, Field


class Citation(BaseModel):
    # source_id는 호출 내부에서만 사용하는 식별자. 공개 references의 필수 필드가 아니다.
    source_id: str
    quote: str = ""


class Claim(BaseModel):
    text: str
    status: Literal["supported", "inference", "unknown"] = "unknown"
    citations: list[Citation] = Field(default_factory=list)


class Competitor(BaseModel):
    name: str
    category: Literal["peer", "bigtech", "substitute"]
    product: str
    relevance: Claim
    comparison: list[Claim] = Field(default_factory=list)


class SWOT(BaseModel):
    strengths: list[Claim] = Field(default_factory=list)
    weaknesses: list[Claim] = Field(default_factory=list)
    opportunities: list[Claim] = Field(default_factory=list)
    threats: list[Claim] = Field(default_factory=list)


class CriterionEvidence(BaseModel):
    # 점수를 출력하지 않는다. 모름과 확인된 없음을 분리해서 5번에 전달한다.
    availability: Literal["found", "confirmed_absent", "unknown"] = "unknown"
    claims: list[Claim] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class Criteria(BaseModel):
    QI: CriterionEvidence = Field(default_factory=CriterionEvidence)
    QJ: CriterionEvidence = Field(default_factory=CriterionEvidence)
    QK: CriterionEvidence = Field(default_factory=CriterionEvidence)
    QL: CriterionEvidence = Field(default_factory=CriterionEvidence)
    QM: CriterionEvidence = Field(default_factory=CriterionEvidence)


class ComparisonDraft(BaseModel):
    competitors: list[Competitor] = Field(default_factory=list)
    swot: SWOT = Field(default_factory=SWOT)
    criterion_evidence: Criteria = Field(default_factory=Criteria)
    missing_information: list[str] = Field(default_factory=list)
