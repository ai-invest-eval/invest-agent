"""기업별 평가 서브그래프와 재시도/제외 처리.

후보별 중간 상태는 WorkerState에만 두고 부모에는 reducer가 있는 결과만
반환한다. API 호출 timeout은 기존 에이전트 설정을 사용한다.
"""

import sys

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


def run_worker(state: WorkerState, config: RunnableConfig) -> WorkerUpdate:
    """공용 뼈대의 시그니처를 유지한다. 실행 래퍼는 다음 단위에서 연결한다."""
    raise NotImplementedError("Worker 실행 래퍼 구현 예정")
