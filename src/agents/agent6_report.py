"""Agent 6 node contract; implementation belongs to its assigned developer."""

from src.schemas import ReportUpdate
from src.state import InvestmentState


def report_writer(state: InvestmentState) -> ReportUpdate:
    """입력: evaluation_history, references.

    출력: final_report (State 변경분만 반환).
    """
    raise NotImplementedError("Agent 6 구현 예정")
