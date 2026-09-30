"""Agent 4 node contract; implementation belongs to its assigned developer."""

from src.schemas import CompetitorAnalysisUpdate
from src.state import InvestmentState


def competitor_analysis(state: InvestmentState) -> CompetitorAnalysisUpdate:
    """입력: selected_startup, startup_profile, tech_analysis, market_analysis.

    출력: competitor_analysis, references (State 변경분만 반환).
    """
    # TODO(4번): 기술/시장 두 결과가 준비된 입력으로 경쟁사와 대체 방식 비교
    # TODO(4번): AI 신약 스타트업·빅테크·자체 연구소/CRO 비교 및 SWOT 작성
    # TODO(4번): 차별성·특허·데이터 진입장벽을 출처와 함께 제시
    raise NotImplementedError("Agent 4 구현 예정")
