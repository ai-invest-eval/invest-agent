"""Agent 3-A node contract; implementation belongs to its assigned developer."""

from src.schemas import TechAnalysisUpdate
from src.state import InvestmentState


def tech_analysis(state: InvestmentState) -> TechAnalysisUpdate:
    """입력: selected_startup, startup_profile.

    출력: tech_analysis, references (State 변경분만 반환).
    """
    raise NotImplementedError("Agent 3-A 구현 예정")
