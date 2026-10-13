"""A-owned graph assembly. Company payloads stay in dynamic Send workers."""

from collections.abc import Mapping

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from src.orchestration.orchestrator import dispatch
from src.orchestration.routing import route_after_eval
from src.state import InvestmentState

NODE_NAMES = ("orchestrator", "worker", "synthesizer", "quality_eval", "finalize")


def build_graph(
    *, nodes: Mapping | None = None, fixture: str | None = None, checkpointer=None
):
    """Injected nodes use exactly the same graph as live mode; fixtures are explicit."""
    if nodes is not None and fixture is not None:
        raise ValueError("nodes와 fixture를 동시에 지정할 수 없습니다.")
    if fixture:
        from src.orchestration.fixtures import fixture_nodes

        nodes = fixture_nodes(fixture)
    elif nodes is None:
        from src.agents.agent6_report import report_writer
        from src.orchestration.finalize import finalize
        from src.orchestration.orchestrator import orchestrator
        from src.orchestration.quality_eval import quality_eval
        from src.orchestration.worker import run_worker

        nodes = {
            "orchestrator": orchestrator,
            "worker": run_worker,
            "synthesizer": report_writer,
            "quality_eval": quality_eval,
            "finalize": finalize,
        }
    if set(nodes) != set(NODE_NAMES):
        raise ValueError(f"Expected exactly these node names: {NODE_NAMES}")
    graph = StateGraph(InvestmentState)
    for name in NODE_NAMES:
        graph.add_node(name, nodes[name])
    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges("orchestrator", dispatch, ["worker", "synthesizer"])
    # Dynamic Send tasks in the same superstep join before this successor runs once.
    graph.add_edge("worker", "synthesizer")
    graph.add_edge("synthesizer", "quality_eval")
    graph.add_conditional_edges(
        "quality_eval", route_after_eval, ["synthesizer", "finalize"]
    )
    graph.add_edge("finalize", END)
    return graph.compile(
        checkpointer=InMemorySaver() if checkpointer is None else checkpointer
    )
