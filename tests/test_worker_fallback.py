"""C 담당 Worker 계약·실패 처리 검증. 외부 API는 호출하지 않는다."""

from collections import Counter
from threading import Barrier, Lock

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
