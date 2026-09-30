"""Agent 3-B node contract; implementation belongs to its assigned developer."""

from src.schemas import MarketAnalysisUpdate
from src.state import InvestmentState


def market_analysis(state: InvestmentState) -> MarketAnalysisUpdate:
    """입력: selected_startup, startup_profile.

    출력: market_analysis, references (State 변경분만 반환).
    """
    raise NotImplementedError("Agent 3-B 구현 예정")
