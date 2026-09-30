"""전체 투자 평가 그래프. 노드 계약과 후보 반복을 연결한다."""

import sys

from langgraph.graph import END, START, StateGraph

from src.agents.agent1_search import select_next_candidate
from src.state import InvestmentState


def route_after_search(state: InvestmentState) -> str:
    """후보가 없으면 2~5번을 건너뛰고 빈 결과 보고서를 작성한다."""
    return "company_profile" if state.get("selected_startup") else "report_writer"


def route_after_decision(state: InvestmentState) -> str:
    """통과/보류에 관계없이 미평가 후보를 계속 처리한다."""
    candidates = state.get("candidate_startups") or []
    history = state.get("evaluation_history") or []
    selected = state.get("selected_startup")
    # 5번이 현재 기업을 기록하지 않으면 같은 기업을 반복하게 된다.
    # 잘못된 반환을 무한 반복 대신 계약 오류로 바로 알린다.
    if selected and select_next_candidate([selected], history) is not None:
        raise ValueError("Agent 5가 현재 기업의 평가 이력을 반환하지 않았습니다.")
    return (
        "startup_search"
        if select_next_candidate(candidates, history)
        else "report_writer"
    )


def build_graph(prepare_indexes=None):
    """1 → 2 → (3a·3b 병렬) → 4 → 5 → 다음 후보 또는 6."""
    # 개별 실행에서는 선택한 에이전트만 import되도록 전체 노드는 여기서 로딩한다.
    from src.agents.agent1_search import startup_search
    from src.agents.agent2_profile import company_profile
    from src.agents.agent3a_tech import tech_analysis
    from src.agents.agent3b_market import market_analysis
    from src.agents.agent4_competitor import competitor_analysis
    from src.agents.agent5_decision import investment_decision
    from src.agents.agent6_report import report_writer

    indexes_prepared = False

    def with_progress(name, node):
        def run(state):
            nonlocal indexes_prepared
            if (
                name == "company_profile"
                and prepare_indexes
                and not indexes_prepared
                and state.get("selected_startup")
            ):
                prepare_indexes()
                indexes_prepared = True
            company = (state.get("selected_startup") or {}).get("name", "")
            print(f"[pipeline] {name} {company}".rstrip(), file=sys.stderr, flush=True)
            return node(state)

        return run

    graph = StateGraph(InvestmentState)
    for name, node in (
        ("startup_search", startup_search),
        ("company_profile", company_profile),
        ("tech_analysis", tech_analysis),
        ("market_analysis", market_analysis),
        ("competitor_analysis", competitor_analysis),
        ("investment_decision", investment_decision),
        ("report_writer", report_writer),
    ):
        graph.add_node(name, with_progress(name, node))
    graph.add_edge(START, "startup_search")
    graph.add_conditional_edges("startup_search", route_after_search)
    graph.add_edge("company_profile", "tech_analysis")
    graph.add_edge("company_profile", "market_analysis")
    # 리스트 시작점은 두 병렬 노드가 모두 끝난 뒤 4번을 한 번만 실행한다.
    graph.add_edge(["tech_analysis", "market_analysis"], "competitor_analysis")
    graph.add_edge("competitor_analysis", "investment_decision")
    graph.add_conditional_edges("investment_decision", route_after_decision)
    graph.add_edge("report_writer", END)
    return graph.compile()
