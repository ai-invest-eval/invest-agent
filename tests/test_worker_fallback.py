"""C 담당 Worker 계약·실패 처리 검증. 외부 API는 호출하지 않는다."""

import copy
from collections import Counter
from threading import Barrier, Lock
from unittest.mock import Mock

import pytest

from src.orchestration import worker


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
def clear_failure_injection(monkeypatch):
    monkeypatch.delenv("FORCE_FAIL_COMPANY", raising=False)


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
