"""전체 워크플로우 연결 골격. 통합 담당자가 TODO를 구현한다."""

from langgraph.graph import END, START, StateGraph  # noqa: F401

# TODO(통합 담당): 연결 시 에이전트 import를 build_graph 내부에 추가
# 개별 에이전트 개발 시 다른 에이전트를 import하지 않아도 된다.
# from src.agents.agent1_search import startup_search
# from src.agents.agent2_profile import company_profile
# from src.agents.agent3a_tech import tech_analysis
# from src.agents.agent3b_market import market_analysis
# from src.agents.agent4_competitor import competitor_analysis
# from src.agents.agent5_decision import investment_decision
# from src.agents.agent6_report import report_writer
from src.state import InvestmentState  # noqa: F401


def build_graph():
    """탐색 → 기업 요약 → 기술/시장 병렬 → 경쟁사 → 판단 → 보고서."""

    # TODO(통합 담당): graph = StateGraph(InvestmentState)
    # TODO(통합 담당): 각 함수로 graph.add_node(...) 등록
    # graph.add_edge(START, "startup_search")
    # TODO(통합 담당): 최초 탐색 결과가 없으면 보고서/종료로 분기
    # graph.add_conditional_edges(
    #     "startup_search", route_after_search,
    #     {"selected": "company_profile", "empty": "report_writer"},
    # )
    # graph.add_edge("company_profile", "tech_analysis")
    # graph.add_edge("company_profile", "market_analysis")
    # graph.add_edge(["tech_analysis", "market_analysis"], "competitor_analysis")
    # graph.add_edge("competitor_analysis", "investment_decision")

    # TODO(통합 담당): 평가 이력에 없는 후보가 남으면 5 → 1, 없으면 5 → 6
    # 통과/보류 판정과 관계없이 모든 후보를 평가한다.
    # graph.add_conditional_edges(
    #     "investment_decision", route_after_decision,
    #     {"remaining": "startup_search", "done": "report_writer"},
    # )
    # TODO(1번 담당): 재진입 시 다음 후보 선택과 현재 분석값 초기화
    # TODO(통합 담당): 후보 전환 시 references/evaluation_history 누적값 보존
    # graph.add_edge("report_writer", END)
    # return graph.compile()
    raise NotImplementedError("통합 담당자: 에이전트 연결 및 후보 분기 구현 예정")
