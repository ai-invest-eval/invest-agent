"""D handoff stub. Verdict only; A-owned routing selects next node."""

from src.schemas import QualityEvalUpdate
from src.state import InvestmentState


def quality_eval(state: InvestmentState) -> QualityEvalUpdate:
    """Expected: eval_result, fresh eval_feedback, step_count=1, node_status."""
    raise NotImplementedError(
        "D파트 quality_eval 미연결. --fixture로 품질 루프를 검증하세요."
    )
