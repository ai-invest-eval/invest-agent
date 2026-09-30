"""Agent 5 node contract; implementation belongs to its assigned developer."""

from src.schemas import InvestmentDecisionUpdate
from src.state import InvestmentState


def investment_decision(state: InvestmentState) -> InvestmentDecisionUpdate:
    """입력: selected_startup, startup_profile, tech_analysis, market_analysis, competitor_analysis, references.

    출력: investment_decision, evaluation_history (State 변경분만 반환).
    """
    raise NotImplementedError("Agent 5 구현 예정")
