"""전체 워크플로우 연결: 탐색 → 프로필 → 기술/시장 병렬 → 경쟁사 → 판단 → (반복) → 보고서."""

from langgraph.graph import END, START, StateGraph

from src.state import InvestmentState


def route_after_search(state: InvestmentState) -> str:
    """1번이 평가할 후보를 골랐으면 2번으로, 후보가 없으면 보고서로 간다."""
    return "selected" if state.get("selected_startup") else "empty"


def route_after_decision(state: InvestmentState) -> str:
    """평가 이력에 없는 후보가 남으면 1번으로 돌아가고, 없으면 보고서로 간다."""
    from src.agents.agent1_search import select_next_candidate

    remaining = select_next_candidate(
        state.get("candidate_startups") or [], state.get("evaluation_history") or []
    )
    return "remaining" if remaining else "done"


def build_graph():
    """설계서 7장 그래프. 통과·보류와 관계없이 후보 전원을 평가한다."""
    from src.agents.agent1_search import startup_search
    from src.agents.agent2_profile import company_profile
    from src.agents.agent3a_tech import tech_analysis
    from src.agents.agent3b_market import market_analysis
    from src.agents.agent4_competitor import competitor_analysis
    from src.agents.agent5_decision import investment_decision
    from src.agents.agent6_report import report_writer

    graph = StateGraph(InvestmentState)
    graph.add_node("startup_search", startup_search)
    graph.add_node("company_profile", company_profile)
    graph.add_node("tech_analysis", tech_analysis)
    graph.add_node("market_analysis", market_analysis)
    graph.add_node("competitor_analysis", competitor_analysis)
    graph.add_node("investment_decision", investment_decision)
    graph.add_node("report_writer", report_writer)

    graph.add_edge(START, "startup_search")
    graph.add_conditional_edges(
        "startup_search",
        route_after_search,
        {"selected": "company_profile", "empty": "report_writer"},
    )
    # 3-A와 3-B는 병렬 실행 후 4번에서 합류한다.
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
