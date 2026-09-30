"""실제 전체 그래프의 병렬 합류·후보 반복·빈 결과를 API 없이 확인한다."""

import io
import json
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import app
from src.graph import build_graph
from src.state import create_initial_state


class PipelineTests(unittest.TestCase):
    def run_graph(self, names, *, missing_history=False, prepare_indexes=None):
        state = create_initial_state("AI", max_candidates=max(1, len(names)))
        state["candidate_startups"] = [{"name": name} for name in names]
        calls = []

        def profile(current):
            name = current["selected_startup"]["name"]
            calls.append(("profile", name))
            self.assertIsNone(current["startup_profile"])
            self.assertEqual(current["tech_analysis"], "")
            return {"startup_profile": {"name": name}}

        def analyze(field):
            def node(current):
                name = current["selected_startup"]["name"]
                return {
                    field: field + name,
                    "references": [{"company": name, "agent": field}],
                }

            return node

        def competitor(current):
            name = current["selected_startup"]["name"]
            self.assertEqual(current["tech_analysis"], "tech_analysis" + name)
            self.assertEqual(current["market_analysis"], "market_analysis" + name)
            calls.append(("competitor", name))
            return {"competitor_analysis": name}

        def decision(current):
            name = current["selected_startup"]["name"]
            calls.append(("decision", name))
            return {
                "investment_decision": {"status": "hold"},
                "evaluation_history": []
                if missing_history
                else [{"name": name, "status": "hold"}],
            }

        def report(current):
            calls.append(("report", None))
            return {"final_report": "보고서"}

        replacements = {
            "src.agents.agent2_profile.company_profile": profile,
            "src.agents.agent3a_tech.tech_analysis": analyze("tech_analysis"),
            "src.agents.agent3b_market.market_analysis": analyze("market_analysis"),
            "src.agents.agent4_competitor.competitor_analysis": competitor,
            "src.agents.agent5_decision.investment_decision": decision,
            "src.agents.agent6_report.report_writer": report,
        }
        with ExitStack() as stack:
            for target, node in replacements.items():
                stack.enter_context(patch(target, node))
            if not names:
                stack.enter_context(
                    patch(
                        "src.agents.agent1_search.startup_search",
                        return_value={
                            "candidate_startups": [],
                            "selected_startup": None,
                        },
                    )
                )
            result = build_graph(prepare_indexes=prepare_indexes).invoke(
                state, {"recursion_limit": 30}
            )
        return result, calls

    def test_two_hold_candidates_both_evaluated_parallel_join_once(self):
        indexes = Mock()
        result, calls = self.run_graph(["Alpha", "Beta"], prepare_indexes=indexes)
        indexes.assert_called_once()
        self.assertEqual(
            [item["name"] for item in result["evaluation_history"]], ["Alpha", "Beta"]
        )
        self.assertEqual(
            calls,
            [
                ("profile", "Alpha"),
                ("competitor", "Alpha"),
                ("decision", "Alpha"),
                ("profile", "Beta"),
                ("competitor", "Beta"),
                ("decision", "Beta"),
                ("report", None),
            ],
        )
        self.assertEqual(len(result["references"]), 4)
        self.assertEqual(result["final_report"], "보고서")

    def test_empty_candidates_skip_analysis_and_report(self):
        indexes = Mock()
        result, calls = self.run_graph([], prepare_indexes=indexes)
        indexes.assert_not_called()
        self.assertEqual(calls, [("report", None)])
        self.assertEqual(result["evaluation_history"], [])

    def test_missing_history_fails_instead_of_repeating(self):
        with self.assertRaisesRegex(ValueError, "평가 이력"):
            self.run_graph(["Alpha"], missing_history=True)

    def test_full_cli_prepares_index_runs_graph_and_saves_state(self):
        result = create_initial_state("AI", max_candidates=1)
        result["final_report"] = "보고서"
        runner = Mock()
        runner.invoke.return_value = result
        output = io.StringIO()
        with (
            TemporaryDirectory() as directory,
            patch("sys.argv", ["app.py", "--max-candidates", "1"]),
            patch("app.PROJECT_ROOT", Path(directory)),
            patch("app.prepare_indexes") as index,
            patch("src.graph.build_graph", return_value=runner) as builder,
            redirect_stdout(output),
        ):
            app.main()
            saved = json.loads(
                (Path(directory) / "outputs/pipeline_state.json").read_text(
                    encoding="utf-8"
                )
            )
        index.assert_not_called()
        builder.assert_called_once_with(prepare_indexes=index)
        self.assertEqual(
            runner.invoke.call_args.kwargs["config"]["recursion_limit"], 18
        )
        self.assertEqual(saved["final_report"], "보고서")
        self.assertIn("전체 평가 완료", output.getvalue())

    def test_missing_rag_dependency_gives_install_command(self):
        with (
            patch("sys.argv", ["app.py"]),
            patch(
                "src.agents.agent1_search.startup_search",
                return_value={
                    "candidate_startups": [{"name": "Alpha"}],
                    "selected_startup": {"name": "Alpha"},
                },
            ),
            patch(
                "src.agents.agent2_profile.company_profile",
                return_value={"startup_profile": {"name": "Alpha"}},
            ),
            patch("app.prepare_indexes", side_effect=ImportError("faiss")),
            self.assertRaises(SystemExit) as caught,
        ):
            app.main()
        self.assertEqual(caught.exception.code, 1)
