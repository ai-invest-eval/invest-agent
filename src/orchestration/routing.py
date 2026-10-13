"""A-owned pure gates. Graph and finalizer import here, never each other."""

from typing import Literal

from src.config import MAX_REPORT_ATTEMPTS, max_steps
from src.schemas import TerminationReason
from src.state import InvestmentState


def decide_termination(state: InvestmentState) -> TerminationReason | None:
    """None requests another draft; a reason always routes through finalization."""
    verdict = state.get("eval_result")
    if not isinstance(verdict, dict):
        raise TypeError("quality_eval이 eval_result를 반환해야 합니다.")
    if state["step_count"] >= max_steps(state["max_candidates"]):
        return "max_steps"
    if verdict["passed"]:
        return "passed"
    if verdict["can_rewrite"]:
        return (
            "max_attempts" if state["report_attempts"] >= MAX_REPORT_ATTEMPTS else None
        )
    if verdict["judge_status"] == "unavailable" or state.get("report_pages") is None:
        return "evaluation_unavailable"
    return "unfixable"


def route_after_eval(state: InvestmentState) -> Literal["synthesizer", "finalize"]:
    return "synthesizer" if decide_termination(state) is None else "finalize"
