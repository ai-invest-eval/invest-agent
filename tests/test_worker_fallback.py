"""C 담당 Worker 계약·실패 처리 검증. 외부 API는 호출하지 않는다."""

import copy
from collections import Counter
from threading import Barrier, Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.orchestration import observability, worker


def reference(company, agent, page=None):
    return {
        "company": company,
        "agent": agent,
        "title": "테스트 문서",
        "source": "RAG" if page else "web",
        "issuer": "fixture",
        "year": 2026,
        "doc_type": "report" if page else "web",
        "page": page,
    }


def payload(company="Alpha", index=0, max_attempts=2):
    candidate = {"name": company, "country": None, "stage": "Seed", "source_url": None}
    refs = [reference(company, "discovery")]
    return {
        "task": {
            "task_id": f"trace:{index}",
            "task_index": index,
            "company": candidate,
            "focus": ["특허 검증"],
            "discovery_refs": refs,
            "max_attempts": max_attempts,
        },
        "trace_id": "trace",
        "selected_startup": candidate,
        "analysis_focus": ["특허 검증"],
        "references": refs,
    }


@pytest.fixture(autouse=True)
def clear_failure_injection(monkeypatch, tmp_path):
    monkeypatch.delenv("FORCE_FAIL_COMPANY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(observability, "TRACE_DIR", tmp_path / "trace", raising=False)


@pytest.fixture
def fake_nodes(monkeypatch):
    def install(failures=None, *, parallel=False, parallel_failures=False):
        calls = []
        attempts = Counter()
        guard = Lock()
        barrier = Barrier(2) if parallel else None
        failures = failures or {}
        failure_barrier = Barrier(2) if parallel_failures else None

        def profile(state):
            name = state["selected_startup"]["name"]
            with guard:
                calls.append((name, "profile"))
                attempts[name] += 1
                attempt = attempts[name]
            assert state.get("startup_profile") is None
            assert not state.get("evaluation_history")
            if attempt <= failures.get(name, 0):
                if failure_barrier:
                    failure_barrier.wait(timeout=5)
                raise TimeoutError("profile timeout")
            return {"startup_profile": {"name": name}}

        def analysis(kind):
            def node(state):
                name = state["selected_startup"]["name"]
                assert state["startup_profile"]["name"] == name
                if barrier:
                    barrier.wait(timeout=5)
                calls.append((name, kind))
                return {
                    f"{kind}_analysis": f"{kind}:{name}",
                    "references": [reference(name, kind, 1 if kind == "tech" else 2)],
                }

            return node

        def competitor(state):
            name = state["selected_startup"]["name"]
            assert state["tech_analysis"] == f"tech:{name}"
            assert state["market_analysis"] == f"market:{name}"
            assert all(ref["company"] == name for ref in state["references"])
            calls.append((name, "competitor"))
            return {"competitor_analysis": f"competitor:{name}"}

        def decision(state):
            name = state["selected_startup"]["name"]
            assert state["competitor_analysis"] == f"competitor:{name}"
            calls.append((name, "decision"))
            return {
                "investment_decision": {"verdict": "보류"},
                "evaluation_history": [{"name": name, "verdict": "보류"}],
            }

        for module, function, replacement in (
            ("agent2_profile", "company_profile", profile),
            ("agent3a_tech", "tech_analysis", analysis("tech")),
            ("agent3b_market", "market_analysis", analysis("market")),
            ("agent4_competitor", "competitor_analysis", competitor),
            ("agent5_decision", "investment_decision", decision),
        ):
            monkeypatch.setattr(f"src.agents.{module}.{function}", replacement)
        return calls, attempts

    return install


def test_worker_graph_parallel_join_runs_comparison_once(fake_nodes):
    calls, _ = fake_nodes(parallel=True)
    graph = worker.build_worker_graph()
    result = graph.invoke(payload(), config={"max_concurrency": 2})
    assert graph.checkpointer is False
    assert Counter(kind for _, kind in calls) == Counter(
        {"profile": 1, "tech": 1, "market": 1, "competitor": 1, "decision": 1}
    )
    assert calls[0] == ("Alpha", "profile")
    assert calls[-2:] == [("Alpha", "competitor"), ("Alpha", "decision")]
    assert result["evaluation_history"] == [{"name": "Alpha", "verdict": "보류"}]


def test_worker_graph_keeps_company_payload_local(fake_nodes):
    fake_nodes()
    graph = worker.build_worker_graph()
    for name in ("Alpha", "Beta"):
        result = graph.invoke(payload(name))
        assert result["startup_profile"] == {"name": name}
        assert all(ref["company"] == name for ref in result["references"])


DONE_KEYS = {
    "evaluation_history",
    "references",
    "worker_results",
    "node_status",
    "step_count",
}


def test_run_worker_returns_only_parent_contract(fake_nodes):
    fake_nodes()
    out = worker.run_worker(payload(), {})
    assert set(out) == DONE_KEYS
    assert out["evaluation_history"] == [{"name": "Alpha", "verdict": "보류"}]
    assert out["node_status"] == {"trace:0": "done"}
    assert out["step_count"] == 1
    assert out["worker_results"][0] == {
        "task_id": "trace:0",
        "task_index": 0,
        "company": "Alpha",
        "status": "done",
        "attempts": 1,
        "duration_ms": out["worker_results"][0]["duration_ms"],
        "error": None,
    }
    assert out["worker_results"][0]["duration_ms"] >= 0


def test_run_worker_passes_config_unchanged(monkeypatch):
    state = payload()
    graph = Mock()
    graph.invoke.return_value = {
        **state,
        "evaluation_history": [{"name": "Alpha"}],
        "last_error": "must not leak",
        "final_report": "must not leak",
    }
    monkeypatch.setattr(worker, "build_worker_graph", lambda: graph)
    config = {"metadata": {"trace_id": "trace"}, "tags": ["worker-test"]}
    result = worker.run_worker(state, config)
    assert graph.invoke.call_args.kwargs["config"] is config
    assert set(result) == DONE_KEYS


@pytest.mark.parametrize(
    "records", [[], [{"name": "Beta"}], [{"name": "Alpha"}, {"name": "Alpha"}]]
)
def test_bad_evaluation_history_is_not_success(monkeypatch, records):
    graph = Mock()
    graph.invoke.return_value = {
        "evaluation_history": records,
        "references": payload()["references"],
    }
    monkeypatch.setattr(worker, "build_worker_graph", lambda: graph)
    result = worker.run_worker(payload(), {})
    assert result["worker_results"][0]["status"] == "excluded"
    assert result["worker_results"][0]["attempts"] == 2
    assert "평가 이력 1건" in result["worker_results"][0]["error"]


def test_run_worker_resets_internal_fields_and_preserves_input(monkeypatch):
    state = payload()
    state.update(
        startup_profile={"name": "stale"},
        tech_analysis="stale",
        market_analysis="stale",
        competitor_analysis="stale",
        investment_decision={"verdict": "통과"},
        evaluation_history=[{"name": "stale"}],
    )
    before = copy.deepcopy(state)

    def invoke(current, config):
        assert current["startup_profile"] is None
        assert all(
            current[k] == ""
            for k in ("tech_analysis", "market_analysis", "competitor_analysis")
        )
        assert current["investment_decision"] is None
        assert current["evaluation_history"] == []
        assert current["analysis_focus"] == state["analysis_focus"]
        current["task"]["focus"].append("mutated")
        return {**current, "evaluation_history": [{"name": "Alpha"}]}

    graph = Mock(invoke=Mock(side_effect=invoke))
    monkeypatch.setattr(worker, "build_worker_graph", lambda: graph)
    worker.run_worker(state, {})
    assert state == before


def test_new_references_keep_distinct_pages_without_discovery(fake_nodes):
    fake_nodes()
    out = worker.run_worker(payload(), {})
    assert len(out["references"]) == 2
    assert {r["page"] for r in out["references"]} == {1, 2}
    assert all(r["agent"] != "discovery" for r in out["references"])


def test_worker_uses_task_defaults_for_optional_send_values(fake_nodes):
    fake_nodes()
    state = payload()
    del state["references"]
    del state["analysis_focus"]
    out = worker.run_worker(state, {})
    assert len(out["references"]) == 2


def test_reference_prefix_must_be_preserved(monkeypatch):
    graph = Mock()
    graph.invoke.return_value = {
        "evaluation_history": [{"name": "Alpha"}],
        "references": [],
    }
    monkeypatch.setattr(worker, "build_worker_graph", lambda: graph)
    result = worker.run_worker(payload(), {})
    assert result["worker_results"][0]["status"] == "excluded"
    assert "탐색 출처" in result["worker_results"][0]["error"]


def test_failed_first_attempt_then_success(fake_nodes):
    calls, attempts = fake_nodes({"Alpha": 1})
    result = worker.run_worker(payload(), {})
    assert attempts["Alpha"] == 2
    assert result["worker_results"][0]["status"] == "done"
    assert result["worker_results"][0]["attempts"] == 2
    assert result["worker_results"][0]["error"] is None
    assert len(result["evaluation_history"]) == 1
    assert len(result["references"]) == 2
    assert calls[-1] == ("Alpha", "decision")


@pytest.mark.parametrize("max_attempts", [1, 2, 3])
def test_attempt_limit_returns_excluded(fake_nodes, max_attempts):
    _, attempts = fake_nodes({"Alpha": 99})
    result = worker.run_worker(payload(max_attempts=max_attempts), {})
    assert attempts["Alpha"] == max_attempts
    assert set(result) == {"worker_results", "node_status", "step_count"}
    summary = result["worker_results"][0]
    assert summary["status"] == "excluded"
    assert summary["attempts"] == max_attempts
    assert summary["error"] == "TimeoutError: profile timeout"
    assert result["node_status"] == {"trace:0": "excluded"}
    assert result["step_count"] == 1


def test_retry_discards_failed_attempt_mutations(monkeypatch):
    state = payload()
    before = copy.deepcopy(state)
    attempts = []

    def invoke(current, config):
        attempts.append(copy.deepcopy(current))
        if len(attempts) == 1:
            current["references"].append(reference("Alpha", "profile"))
            current["evaluation_history"].append({"name": "bad"})
            current["task"]["focus"].append("bad")
            current["tech_analysis"] = "bad"
            raise RuntimeError("late failure")
        assert current == attempts[0]
        return {
            **current,
            "evaluation_history": [{"name": "Alpha"}],
            "references": current["references"] + [reference("Alpha", "tech", 2)],
        }

    graph = Mock(invoke=Mock(side_effect=invoke))
    builder = Mock(return_value=graph)
    monkeypatch.setattr(worker, "build_worker_graph", builder)
    result = worker.run_worker(state, {})
    assert state == before
    assert result["references"] == [reference("Alpha", "tech", 2)]
    assert result["evaluation_history"] == [{"name": "Alpha"}]
    builder.assert_called_once()


@pytest.mark.parametrize("exc", [TimeoutError("timeout"), RuntimeError("API error")])
def test_escaped_api_errors_follow_same_retry_policy(monkeypatch, exc):
    graph = Mock()
    graph.invoke.side_effect = exc
    monkeypatch.setattr(worker, "build_worker_graph", lambda: graph)
    result = worker.run_worker(payload(), {})
    assert graph.invoke.call_count == 2
    assert result["worker_results"][0]["error"] == f"{type(exc).__name__}: {exc}"


@pytest.mark.parametrize("both_fail", [False, True])
def test_parent_send_graph_survives_partial_or_simultaneous_failure(
    fake_nodes, both_fail
):
    from src.graph import build_graph
    from src.orchestration.fixtures import fixture_nodes
    from src.state import create_initial_state

    failures = {"가상 기업 1": 2}
    if both_fail:
        failures["가상 기업 2"] = 2
    _, attempts = fake_nodes(failures, parallel_failures=both_fail)
    nodes = fixture_nodes("two")
    nodes["worker"] = worker.run_worker
    result = build_graph(nodes=nodes).invoke(
        create_initial_state("test", 2),
        {
            "max_concurrency": 2,
            "recursion_limit": 30,
            "configurable": {"thread_id": "parent-test"},
        },
    )
    summaries = {r["company"]: r for r in result["worker_results"]}
    assert len(summaries) == 2
    assert summaries["가상 기업 1"]["status"] == "excluded"
    assert summaries["가상 기업 1"]["attempts"] == 2
    assert summaries["가상 기업 2"]["status"] == ("excluded" if both_fail else "done")
    assert len(result["evaluation_history"]) == (0 if both_fail else 1)
    if not both_fail:
        assert result["evaluation_history"][0]["name"] == "가상 기업 2"
        assert all(r["company"] == "가상 기업 2" for r in result["references"])
    assert result["node_status"]["finalize"] == "done"
    assert result["last_error"] is None
    assert result["step_count"] == 6
    assert attempts["가상 기업 1"] == 2


def test_parent_workers_do_not_share_success_payloads(fake_nodes):
    from src.graph import build_graph
    from src.orchestration.fixtures import fixture_nodes
    from src.state import create_initial_state

    fake_nodes()
    nodes = fixture_nodes("two")
    nodes["worker"] = worker.run_worker
    result = build_graph(nodes=nodes).invoke(
        create_initial_state("test", 2), {"configurable": {"thread_id": "parent-test"}}
    )
    assert {r["name"] for r in result["evaluation_history"]} == {
        "가상 기업 1",
        "가상 기업 2",
    }
    assert len(result["references"]) == 4
    assert all(r["status"] == "done" for r in result["worker_results"])


def test_forced_failure_retries_without_invoking_subgraph(monkeypatch):
    builder = Mock()
    monkeypatch.setattr(worker, "build_worker_graph", builder)
    monkeypatch.setenv("FORCE_FAIL_COMPANY", "Alpha")
    result = worker.run_worker(payload(), {})
    builder.assert_not_called()
    assert result["worker_results"][0]["status"] == "excluded"
    assert result["worker_results"][0]["attempts"] == 2
    assert (
        result["worker_results"][0]["error"] == "RuntimeError: forced failure for demo"
    )


@pytest.mark.parametrize("forced", ["", "Beta", " Alpha "])
def test_forced_failure_requires_exact_company_match(monkeypatch, fake_nodes, forced):
    _, attempts = fake_nodes()
    monkeypatch.setenv("FORCE_FAIL_COMPANY", forced)
    result = worker.run_worker(payload(), {})
    assert result["worker_results"][0]["status"] == "done"
    assert attempts["Alpha"] == 1


def test_forced_failure_excludes_only_selected_company_in_parent(
    monkeypatch, fake_nodes
):
    from src.graph import build_graph
    from src.orchestration.fixtures import fixture_nodes
    from src.state import create_initial_state

    fake_nodes()
    monkeypatch.setenv("FORCE_FAIL_COMPANY", "가상 기업 1")
    nodes = fixture_nodes("two")
    nodes["worker"] = worker.run_worker
    result = build_graph(nodes=nodes).invoke(
        create_initial_state("test", 2), {"configurable": {"thread_id": "forced-test"}}
    )
    summaries = {r["company"]: r for r in result["worker_results"]}
    assert summaries["가상 기업 1"]["status"] == "excluded"
    assert summaries["가상 기업 2"]["status"] == "done"
    assert "평가 제외" in result["final_report"]


@pytest.fixture
def decisions(monkeypatch):
    logger = Mock()
    monkeypatch.setattr(worker, "log_decision", logger)
    return logger


def test_retry_and_success_logs_include_total_duration(
    monkeypatch, fake_nodes, decisions
):
    fake_nodes({"Alpha": 1})
    ticks = iter([10.0, 11.0, 13.0])
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    config = {"metadata": {"trace_id": "trace"}}
    result = worker.run_worker(payload(), config)
    assert result["worker_results"][0]["duration_ms"] == 3000
    first, last = decisions.call_args_list
    assert first.args == ("trace", "worker", "retry", "TimeoutError: profile timeout")
    assert first.kwargs == {
        "task_id": "trace:0",
        "company": "Alpha",
        "attempts": 1,
        "duration_ms": 1000,
    }
    assert last.args == ("trace", "worker", "done", "평가 완료")
    assert last.kwargs == {
        "task_id": "trace:0",
        "company": "Alpha",
        "attempts": 2,
        "duration_ms": 3000,
    }


def test_final_failure_logs_exclusion(monkeypatch, decisions):
    monkeypatch.setenv("FORCE_FAIL_COMPANY", "Alpha")
    ticks = iter([10.0, 11.0, 12.0])
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    result = worker.run_worker(payload(), {})
    assert [c.args[2] for c in decisions.call_args_list] == ["retry", "excluded"]
    assert decisions.call_args_list[-1].args[3] == result["worker_results"][0]["error"]
    assert decisions.call_args_list[-1].kwargs["duration_ms"] == 2000


def test_worker_child_callbacks_remain_nested_in_parent(fake_nodes):
    from langchain_core.callbacks import BaseCallbackHandler

    from src.graph import build_graph
    from src.orchestration.fixtures import fixture_nodes
    from src.state import create_initial_state

    starts = []

    class Recorder(BaseCallbackHandler):
        def on_chain_start(
            self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs
        ):
            starts.append((kwargs.get("name"), run_id, parent_run_id))

    fake_nodes()
    nodes = fixture_nodes("two")
    nodes["worker"] = worker.run_worker
    build_graph(nodes=nodes).invoke(
        create_initial_state("test", 2),
        {
            "configurable": {"thread_id": "callback-test"},
            "callbacks": [Recorder()],
            "metadata": {"trace_id": "trace"},
            "tags": ["worker-test"],
        },
    )
    workers = {run_id for name, run_id, _ in starts if name == "worker"}
    children = {
        run_id
        for name, run_id, parent in starts
        if name == "LangGraph" and parent in workers
    }
    assert len(workers) == len(children) == 2
    for name in (
        "company_profile",
        "tech_analysis",
        "market_analysis",
        "competitor_analysis",
        "investment_decision",
    ):
        assert sum(n == name and parent in children for n, _, parent in starts) == 2


def test_agent5_llm_has_bounded_api_calls():
    from src.agents.agent5_decision import JudgeResult, _get_llm
    from src.config import LLM_MODEL, LLM_TEMPERATURE

    model = Mock()
    with patch("langchain_openai.ChatOpenAI", return_value=model) as constructor:
        result = _get_llm()
    constructor.assert_called_once_with(
        model=LLM_MODEL, temperature=LLM_TEMPERATURE, timeout=60, max_retries=1
    )
    model.with_structured_output.assert_called_once_with(JudgeResult)
    assert result is model.with_structured_output.return_value
