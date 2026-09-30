"""Agent 1 node contract; implementation belongs to its assigned developer."""

from src.schemas import StartupSearchUpdate
from src.state import InvestmentState


def startup_search(state: InvestmentState) -> StartupSearchUpdate:
    """입력: input_keyword.

    출력: candidate_startups, selected_startup, references (State 변경분만 반환).
    """
    raise NotImplementedError("Agent 1 구현 예정")
