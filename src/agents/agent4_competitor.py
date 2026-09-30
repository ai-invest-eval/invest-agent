"""Agent 4 node contract; implementation belongs to its assigned developer."""

from src.schemas import CompetitorAnalysisUpdate
from src.state import InvestmentState


def competitor_analysis(state: InvestmentState) -> CompetitorAnalysisUpdate:
    """입력: selected_startup, startup_profile, tech_analysis, market_analysis.

    출력: competitor_analysis, references (State 변경분만 반환).
    """
    raise NotImplementedError("Agent 4 구현 예정")
