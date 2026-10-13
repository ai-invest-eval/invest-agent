"""C handoff stub; never use synthetic company evaluation in live mode."""

from langchain_core.runnables import RunnableConfig

from src.schemas import WorkerUpdate
from src.state import WorkerState


def run_worker(state: WorkerState, config: RunnableConfig) -> WorkerUpdate:
    """Return only worker_results/history/new refs/status/count; no last_error."""
    raise NotImplementedError("C파트 run_worker 미연결. --fixture로 계약을 검증하세요.")
