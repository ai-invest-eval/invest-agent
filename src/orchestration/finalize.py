"""E handoff stub. Real finalizer imports routing, not graph."""

from src.schemas import FinalizeUpdate
from src.state import InvestmentState


def finalize(state: InvestmentState) -> FinalizeUpdate:
    """Final MD/PDF/JSON consistency and real page counting belong to E."""
    raise NotImplementedError(
        "E파트 finalize 미연결. --fixture 결과는 가상 시연입니다."
    )
