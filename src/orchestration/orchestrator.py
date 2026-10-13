"""B handoff stub. Replace orchestrator internals, retain dispatch/state contract."""

from langgraph.types import Send

from src.schemas import OrchestratorUpdate
from src.state import InvestmentState


def orchestrator(state: InvestmentState) -> OrchestratorUpdate:
    """Expected: candidate_startups, plan, new references, step_count=1, node_status."""
    raise NotImplementedError(
        "B파트 orchestrator 미연결. 뼈대 시연은 --fixture two로 실행하세요."
    )


def dispatch(state: InvestmentState):
    """Only plan determines fan-out. No task means no worker or RAG preparation."""
    tasks = state.get("plan") or []
    if not tasks:
        return "synthesizer"
    return [
        Send(
            "worker",
            {
                "task": task,
                "trace_id": state["trace_id"],
                "selected_startup": task["company"],
                "analysis_focus": task["focus"],
                "references": task["discovery_refs"],
            },
        )
        for task in tasks
    ]
