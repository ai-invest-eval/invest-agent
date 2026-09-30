"""app 실행과 LangGraph reducer에서 Agent 1 후보 반복 계약을 확인한다."""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from langgraph.graph import END, START, StateGraph

import app
from src.agents.agent1_search import Agent1SearchError, startup_search
from src.state import InvestmentState, create_initial_state


class Agent1ExecutionTests(unittest.TestCase):
    def test_cli_existing_candidates_needs_no_clients(self):
        output = io.StringIO()
        with (
            patch(
                "sys.argv",
                [
                    "app.py",
                    "--agent",
                    "1",
                    "--state",
                    "samples/agent1_existing_candidates.json",
                ],
            ),
            patch(
                "src.agents.agent1_search.GPTStructuredGenerator",
                side_effect=AssertionError("API 생성 금지"),
            ),
            patch(
                "src.agents.agent1_search.TavilySearch",
                side_effect=AssertionError("API 생성 금지"),
            ),
            redirect_stdout(output),
        ):
            app.main()
        result = json.loads(output.getvalue())
        self.assertEqual(result["selected_startup"]["name"], "샘플기업 A")
        self.assertEqual(result["references"], [])

    def test_cli_api_failure_is_nonzero_exit(self):
        with (
            patch("sys.argv", ["app.py", "--agent", "1"]),
            patch(
                "app.import_module",
                return_value=Mock(
                    startup_search=Mock(side_effect=Agent1SearchError("검색 장애"))
                ),
            ),
            self.assertRaises(SystemExit) as caught,
        ):
            app.main()
        self.assertEqual(caught.exception.code, 1)

    def test_graph_reentry_preserves_reducers_and_ends(self):
        state = create_initial_state("독립 반복 검증")
        state["candidate_startups"] = [
            {"name": name, "country": None, "stage": "시드", "source_url": None}
            for name in ("Alpha", "Beta")
        ]
        state["references"] = [
            {
                "company": "Alpha",
                "agent": "discovery",
                "title": "샘플",
                "source": "web",
                "issuer": None,
                "year": None,
                "doc_type": "web",
                "url": "https://example.com",
            }
        ]

        # 분석 에이전트는 구현하지 않는다. 테스트용 노드가 이름을 평가 이력에
        # 추가해 5 → 1 조건을 재현하고, 실제 보고서 단계는 호출하지 않는다.
        def evaluated(current):
            return {
                "evaluation_history": [{"name": current["selected_startup"]["name"]}]
            }

        graph = StateGraph(InvestmentState)
        graph.add_node("search", startup_search)
        graph.add_node("evaluated", evaluated)
        graph.add_edge(START, "search")
        graph.add_conditional_edges(
            "search",
            lambda current: "evaluated" if current["selected_startup"] else END,
        )
        graph.add_edge("evaluated", "search")
        with (
            patch(
                "src.agents.agent1_search.GPTStructuredGenerator",
                side_effect=AssertionError("재탐색 금지"),
            ),
            patch(
                "src.agents.agent1_search.TavilySearch",
                side_effect=AssertionError("재탐색 금지"),
            ),
        ):
            result = graph.compile().invoke(state, {"recursion_limit": 10})
        self.assertEqual(
            [record["name"] for record in result["evaluation_history"]],
            ["Alpha", "Beta"],
        )
        self.assertEqual(result["references"], state["references"])
        self.assertIsNone(result["selected_startup"])
