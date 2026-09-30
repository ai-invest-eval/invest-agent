"""후보 전원을 평가한 뒤 한 번 보고서를 작성하는 LangGraph 워크플로우."""

from collections.abc import Callable, Mapping
from importlib import import_module

from langgraph.graph import END, START, StateGraph

from src.agents.agent1_search import select_next_candidate
from src.state import InvestmentState

NODE_IMPORTS = {
    "startup_search": ("src.agents.agent1_search", "startup_search"),
    "company_profile": ("src.agents.agent2_profile", "company_profile"),
    "tech_analysis": ("src.agents.agent3a_tech", "tech_analysis"),
    "market_analysis": ("src.agents.agent3b_market", "market_analysis"),
    "competitor_analysis": ("src.agents.agent4_competitor", "competitor_analysis"),
    "investment_decision": ("src.agents.agent5_decision", "investment_decision"),
    "report_writer": ("src.agents.agent6_report", "report_writer"),
}


def route_after_search(state: InvestmentState) -> str:
    """후보가 없거나 모두 평가됐으면 빈 결과까지 보고서에 남긴다."""
    return "selected" if state.get("selected_startup") else "empty"


def route_after_decision(state: InvestmentState) -> str:
    """점수·통과 여부와 무관하게 남은 후보를 모두 평가한다."""
    remaining = select_next_candidate(
        state.get("candidate_startups") or [], state.get("evaluation_history") or []
    )
    return "remaining" if remaining else "done"


def build_graph(
    nodes: Mapping[str, Callable[[InvestmentState], dict]] | None = None,
):
    """1 → 2 → (3-A, 3-B) → 4 → 5 → 다음 후보/6을 연결한다.

    nodes 주입은 외부 API 없이 전체 그래프의 제어·State 계약을 검증할 때 쓴다.
    실제 실행은 기본값을 사용하며 각 에이전트의 모듈을 여기에서만 가져온다.
    """
    if nodes is None:
        nodes = {
            name: getattr(import_module(module), function)
            for name, (module, function) in NODE_IMPORTS.items()
        }
    missing = NODE_IMPORTS.keys() - nodes.keys()
    if missing:
        raise ValueError(f"그래프 노드 누락: {', '.join(sorted(missing))}")

    graph = StateGraph(InvestmentState)
    for name in NODE_IMPORTS:
        graph.add_node(name, nodes[name])
    graph.add_edge(START, "startup_search")
    graph.add_conditional_edges(
        "startup_search",
        route_after_search,
        {"selected": "company_profile", "empty": "report_writer"},
    )
    graph.add_edge("company_profile", "tech_analysis")
    graph.add_edge("company_profile", "market_analysis")
    graph.add_edge(["tech_analysis", "market_analysis"], "competitor_analysis")
    graph.add_edge("competitor_analysis", "investment_decision")
    graph.add_conditional_edges(
        "investment_decision",
        route_after_decision,
        {"remaining": "startup_search", "done": "report_writer"},
    )
    graph.add_edge("report_writer", END)
    return graph.compile()
