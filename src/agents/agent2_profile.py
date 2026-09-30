"""Agent 2 node contract; implementation belongs to its assigned developer."""

from src.schemas import CompanyProfileUpdate
from src.state import InvestmentState


def company_profile(state: InvestmentState) -> CompanyProfileUpdate:
    """입력: selected_startup.

    출력: startup_profile, references (State 변경분만 반환).
    """
    raise NotImplementedError("Agent 2 구현 예정")
