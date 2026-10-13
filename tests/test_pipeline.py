"""A contracts: dynamic parent fan-out, child join, failures, quality loop and CLI."""

import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest

import app
from src.graph import build_graph
from src.orchestration.fixtures import _child_graph, fixture_nodes
from src.orchestration.orchestrator import dispatch
from src.state import create_initial_state


def config(state):
    return {
        "configurable": {"thread_id": state["trace_id"]},
        "recursion_limit": 24,
        "max_concurrency": 3,
    }


@pytest.mark.parametrize(
    "name,count,excluded,attempts",
    [
        ("empty", 0, 0, 1),
        ("two", 2, 0, 1),
        ("three", 3, 0, 1),
        ("partial_fail", 2, 1, 1),
        ("all_fail", 2, 2, 1),
        ("quality_loop", 2, 0, 2),
    ],
)
def test_fixture_graph_and_fan_in(name, count, excluded, attempts):
    state = create_initial_state("test", 3)
    graph = build_graph(fixture=name)
    result = graph.invoke(state, config(state))
    assert len(result["plan"]) == count
    assert len(result["worker_results"]) == count
    assert len(result["evaluation_history"]) == count - excluded
    assert sum(w["status"] == "excluded" for w in result["worker_results"]) == excluded
    assert result["report_attempts"] == attempts
    assert result["node_status"]["finalize"] == "done"
    assert (
        result["eval_result"]["termination_reason"] == "passed"
    )  # synthetic fixture Judge
    assert result["report_pages"] is None  # no real PDF page count claim
    assert graph.get_state(config(state)).next == ()
    for w in result["worker_results"]:
        assert w["attempts"] == (2 if w["status"] == "excluded" else 1)
    assert (
        result["last_error"] is None
    )  # simultaneous failures never write this parent key


def test_dynamic_dispatch_scopes_payload():
    state = create_initial_state("test", 3)
    state.update(fixture_nodes("three")["orchestrator"](state))
    sent = dispatch(state)
    assert len(sent) == 3
    for i, send in enumerate(sent):
        assert send.node == "worker"
        assert set(send.arg) == {
            "task",
            "trace_id",
            "selected_startup",
            "analysis_focus",
            "references",
        }
        assert send.arg["task"]["task_index"] == i
        assert send.arg["selected_startup"]["name"] == f"가상 기업 {i + 1}"
    assert dispatch(create_initial_state("test")) == "synthesizer"


def test_successor_runs_once_after_every_worker():
    nodes = fixture_nodes("three")
    calls = []
    writer = nodes["synthesizer"]

    def observe(state):
        calls.append(len(state["worker_results"]))
        return writer(state)

    nodes["synthesizer"] = observe
    state = create_initial_state("test", 3)
    build_graph(nodes=nodes).invoke(state, config(state))
    assert calls == [3]


def test_child_parallel_join_and_missing_profile_error():
    graph = _child_graph()
    result = graph.invoke(
        {
            "selected_startup": {"name": "가상"},
            "references": [],
            "evaluation_history": [],
        }
    )
    assert len(result["references"]) == 2
    assert len(result["evaluation_history"]) == 1
    assert result["tech_analysis"] and result["market_analysis"]
    with pytest.raises(KeyError):
        graph.invoke({"references": [], "evaluation_history": []})


@pytest.mark.parametrize(
    "mode,reason,attempts",
    [
        ("structural", "unfixable", 1),
        ("unavailable", "evaluation_unavailable", 1),
        ("always_rewrite", "max_attempts", 3),
        ("rewrite_unavailable", "max_attempts", 3),
    ],
)
def test_graph_termination_paths(mode, reason, attempts):
    nodes = fixture_nodes("two")
    original = nodes["quality_eval"]

    def assessment(state):
        update = original(state)
        v = update["eval_result"]
        v.update(
            passed=False,
            can_rewrite=mode in ("always_rewrite", "rewrite_unavailable"),
            judge_status="unavailable"
            if mode in ("unavailable", "rewrite_unavailable")
            else "completed",
        )
        update["eval_feedback"] = ["synthetic rewrite"] if v["can_rewrite"] else []
        return update

    nodes["quality_eval"] = assessment
    state = create_initial_state("test", 3)
    result = build_graph(nodes=nodes).invoke(state, config(state))
    assert result["eval_result"]["termination_reason"] == reason
    assert result["report_attempts"] == attempts
    assert result["node_status"]["finalize"] == "done"


def test_api_free_fixture_cli(tmp_path):
    with (
        patch("sys.argv", ["app.py", "--fixture", "quality_loop"]),
        patch("app.PROJECT_ROOT", tmp_path),
        redirect_stdout(io.StringIO()) as output,
    ):
        app.main()
    saved = list((tmp_path / "outputs").glob("*_state.json"))
    assert len(saved) == 1
    state = json.loads(saved[0].read_text())
    assert state["report_attempts"] == 2
    assert state["node_status"]["finalize"] == "done"
    assert saved[0].with_suffix(".md").exists()
    assert "실제 API·Judge·PDF 미실행" in output.getvalue()


def test_live_unavailable_node_fails_loudly(tmp_path):
    # 실제 B 구현 연결 후에도 외부 API 없이 미구현 노드 오류 처리를 검증한다.
    def unavailable(state):
        raise NotImplementedError("test-only unavailable node")

    with (
        patch("sys.argv", ["app.py"]),
        patch("app.PROJECT_ROOT", tmp_path),
        patch("src.orchestration.orchestrator.orchestrator", unavailable),
        pytest.raises(SystemExit) as caught,
    ):
        app.main()
    assert caught.value.code == 1
    assert not (tmp_path / "outputs").exists()


def test_cli_config_correlation(tmp_path):
    from unittest.mock import Mock

    state = create_initial_state("test")
    runner = Mock()
    runner.invoke.return_value = state
    with (
        patch("sys.argv", ["app.py"]),
        patch("app.PROJECT_ROOT", tmp_path),
        patch("src.graph.build_graph", return_value=runner),
        redirect_stdout(io.StringIO()),
    ):
        app.main()
    actual = runner.invoke.call_args.kwargs["config"]
    assert actual["configurable"]["thread_id"] == actual["metadata"]["trace_id"]
    assert actual["max_concurrency"] == 3
    assert actual["metadata"]["execution_mode"] == "live"


def test_fixture_and_injected_nodes_are_exclusive():
    with pytest.raises(ValueError):
        build_graph(fixture="two", nodes=fixture_nodes("two"))
