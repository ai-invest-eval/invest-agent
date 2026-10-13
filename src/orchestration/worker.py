"""기업별 평가 서브그래프와 재시도/제외 처리.

후보별 중간 상태는 WorkerState에만 두고 부모에는 reducer가 있는 결과만
반환한다. API 호출 timeout은 기존 에이전트 설정을 사용한다.
"""

import copy
import sys
import time

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

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
    """현재 기업의 결과만 reducer가 있는 부모 키로 반환한다."""
    task = state["task"]
    company = task["company"]["name"]
    started = time.monotonic()
    initial = copy.deepcopy(state)
    result = build_worker_graph().invoke(copy.deepcopy(initial), config=config)
    payload = _successful_payload(result, initial, company)
    return {
        **payload,
        "worker_results": [
            {
                "task_id": task["task_id"],
                "task_index": task["task_index"],
                "company": company,
                "status": "done",
                "attempts": 1,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "error": None,
            }
        ],
        "node_status": {task["task_id"]: "done"},
        "step_count": 1,
    }
