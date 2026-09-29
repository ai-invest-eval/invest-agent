"""LangGraph state shared by the investment evaluation agents."""

import operator
from typing import Annotated, Required, TypedDict

from src.schemas import (
    CandidateStartup,
    EvaluationRecord,
    InvestmentDecision,
    Reference,
    StartupProfile,
)


class InvestmentState(TypedDict, total=False):
    # 사용자 입력: 스타트업 탐색 키워드
    input_keyword: Required[str]

    # 1번: 자격 검증 완료 후보 목록
    candidate_startups: list[CandidateStartup]
    # 1번: 현재 평가 대상 기업
    selected_startup: CandidateStartup | None

    # 2번: 기업 프로필 및 결측 정보
    startup_profile: StartupProfile | None
    # 3-A번: 기술 분석 결과
    tech_analysis: str
    # 3-B번: 시장성 분석 결과
    market_analysis: str
    # 4번: 경쟁사 분석 결과
    competitor_analysis: str
    # 5번: 현재 기업의 점수 및 투자 판정
    investment_decision: InvestmentDecision | None

    # 5번: 기업별 평가 이력 (누적)
    evaluation_history: Annotated[list[EvaluationRecord], operator.add]
    # 3-A·3-B·4번: 참고 출처 (누적)
    references: Annotated[list[Reference], operator.add]

    # 6번: 최종 투자 보고서 (마크다운)
    final_report: str
