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
    def install(failures=None, *, parallel=False):
        calls = []
        attempts = Counter()
        guard = Lock()
        barrier = Barrier(2) if parallel else None
        failures = failures or {}

        def profile(state):
            name = state["selected_startup"]["name"]
            with guard:
                calls.append((name, "profile"))
                attempts[name] += 1
                attempt = attempts[name]
            assert state.get("startup_profile") is None
            assert not state.get("evaluation_history")
            if attempt <= failures.get(name, 0):
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
    with pytest.raises(ValueError, match="평가 이력 1건"):
        worker.run_worker(payload(), {})


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
    with pytest.raises(ValueError, match="탐색 출처"):
        worker.run_worker(payload(), {})
