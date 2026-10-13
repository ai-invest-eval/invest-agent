"""기업별 평가 서브그래프와 재시도/제외 처리.

후보별 중간 상태는 WorkerState에만 두고 부모에는 reducer가 있는 결과만
반환한다. API 호출 timeout은 기존 에이전트 설정을 사용한다.
"""

import copy
import os
import sys
import time

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.orchestration.observability import log_decision
from src.schemas import WorkerUpdate
from src.state import WorkerState


def build_worker_graph():
    """2 → (3A·3B 병렬) → 4 → 5. 부모 체크포인트를 상속하지 않는다."""
    from src.agents.agent2_profile import company_profile
    from src.agents.agent3a_tech import tech_analysis
    from src.agents.agent3b_market import market_analysis
    from src.agents.agent4_competitor import competitor_analysis
    from src.agents.agent5_decision import investment_decision

    def with_progress(name, node):
        def run(state):
            company = state["selected_startup"]["name"]
            print(f"[worker] {name} {company}", file=sys.stderr, flush=True)
            return node(state)

        return run

    graph = StateGraph(WorkerState)
    for name, node in (
        ("company_profile", company_profile),
        ("tech_analysis", tech_analysis),
        ("market_analysis", market_analysis),
        ("competitor_analysis", competitor_analysis),
        ("investment_decision", investment_decision),
    ):
        graph.add_node(name, with_progress(name, node))
    graph.add_edge(START, "company_profile")
    graph.add_edge("company_profile", "tech_analysis")
    graph.add_edge("company_profile", "market_analysis")
    graph.add_edge(["tech_analysis", "market_analysis"], "competitor_analysis")
    graph.add_edge("competitor_analysis", "investment_decision")
    graph.add_edge("investment_decision", END)
    return graph.compile(checkpointer=False)


def _fresh_input(state: WorkerState) -> WorkerState:
    """실패한 시도의 누적값 대신 기업과 탐색 입력만 복사한다."""
    task = state["task"]
    return copy.deepcopy(
        {
            "task": task,
            "trace_id": state["trace_id"],
            "selected_startup": task["company"],
            "analysis_focus": state.get("analysis_focus", task["focus"]),
            "references": state.get("references", task["discovery_refs"]),
            "startup_profile": None,
            "tech_analysis": "",
            "market_analysis": "",
            "competitor_analysis": "",
            "investment_decision": None,
            "evaluation_history": [],
        }
    )


def _successful_payload(result, initial, company):
    records = result.get("evaluation_history") or []
    if len(records) != 1 or records[0].get("name") != company:
        raise ValueError("Worker는 현재 기업의 평가 이력 1건을 반환해야 합니다.")
    references = result.get("references") or []
    initial_refs = initial["references"]
    if references[: len(initial_refs)] != initial_refs:
        raise ValueError("Worker의 누적 출처가 탐색 출처를 보존하지 않았습니다.")
    # operator.add로 붙인 신규 출처만 반환. 같은 문서의 다른 페이지도 보존한다.
    return copy.deepcopy(
        {
            "evaluation_history": records,
            "references": references[len(initial_refs) :],
        }
    )


def run_worker(state: WorkerState, config: RunnableConfig) -> WorkerUpdate:
    """실패는 task.max_attempts까지 재시도하고 최종 실패는 excluded로 반환."""
    task = state["task"]
    task_id = task["task_id"]
    company = task["company"]["name"]
    started = time.monotonic()
    worker_graph = None

    for attempt in range(1, task["max_attempts"] + 1):
        try:
            if os.getenv("FORCE_FAIL_COMPANY", "") == company:
                raise RuntimeError("forced failure for demo")
            initial = _fresh_input(state)
            # 검증용 입력을 따로 보존해 호출 중 변경도 시도 간에 전달하지 않는다.
            invoke_input = copy.deepcopy(initial)
            if worker_graph is None:
                worker_graph = build_worker_graph()
            result = worker_graph.invoke(invoke_input, config=config)
            payload = _successful_payload(result, initial, company)
        except Exception as exc:  # noqa: BLE001 -- 기업 단위 실패로 부모 실행을 중단하지 않는다
            error = f"{type(exc).__name__}: {exc}"
            duration_ms = int((time.monotonic() - started) * 1000)
            status = "retry" if attempt < task["max_attempts"] else "excluded"
            log_decision(
                state["trace_id"],
                "worker",
                status,
                error,
                task_id=task_id,
                company=company,
                attempts=attempt,
                duration_ms=duration_ms,
            )
            if status == "retry":
                continue
            payload = {}
        else:
            status = "done"
            error = None
            duration_ms = int((time.monotonic() - started) * 1000)
            log_decision(
                state["trace_id"],
                "worker",
                status,
                "평가 완료",
                task_id=task_id,
                company=company,
                attempts=attempt,
                duration_ms=duration_ms,
            )

        return {
            **payload,
            "worker_results": [
                {
                    "task_id": task_id,
                    "task_index": task["task_index"],
                    "company": company,
                    "status": status,
                    "attempts": attempt,
                    "duration_ms": duration_ms,
                    "error": error,
                }
            ],
            "node_status": {task_id: status},
            "step_count": 1,
        }

    raise ValueError("Worker max_attempts는 1 이상이어야 합니다.")
