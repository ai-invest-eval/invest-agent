"""B 계약: 계획 생성, 빈 후보, 안전한 fallback, 동적 Send."""

import copy

import pytest

from src.orchestration.orchestrator import PlanOutput, dispatch, orchestrator


class Planner:
    def __init__(self, items):
        self.items = items
        self.payload = None

    def generate(self, schema, system, payload):
        self.payload = payload
        return PlanOutput(items=self.items)


def execute(names, planner):
    state = {"trace_id": "run", "input_keyword": "AI", "max_candidates": 5}
    before = copy.deepcopy(state)
    events = []
    refs = [
        {
            "company": " a ",
            "agent": "discovery",
            "title": "임상 검증",
            "issuer": "기관",
        },
        {"company": "A", "agent": "profile", "title": "제외"},
    ]
    result = orchestrator(
        state,
        discover=lambda _: {
            "candidate_startups": [{"name": n} for n in names],
            "references": refs,
        },
        generator=planner,
        prepare=lambda: events.append("prepare"),
        log=lambda *args, **kwargs: events.append("log"),
    )
    assert state == before
    return state, result, events


@pytest.mark.parametrize("count", [0, 2, 3])
def test_dynamic_plan_and_dispatch(count):
    names = [chr(65 + n) for n in range(count)]
    planner = Planner(
        [
            {"company": n, "focus": ["임상 검증"], "reason": "출처 제목"}
            for n in reversed(names)
        ]
    )
    state, result, events = execute(names, planner)
    assert [task["task_index"] for task in result["plan"]] == list(range(count))
    assert [task["company"]["name"] for task in result["plan"]] == names
    assert events == (["prepare", "log"] if count else ["log"])
    sends = dispatch({**state, **result})
    if not count:
        assert sends == "synthesizer"
        assert planner.payload is None
    else:
        assert len(sends) == count
        assert all(packet.node == "worker" for packet in sends)
        assert sends[0].arg["analysis_focus"] == ["임상 검증"]
        assert len(sends[0].arg["references"]) == 1
        assert (
            planner.payload["candidates"][0]["discovery_sources"][0]["title"]
            == "임상 검증"
        )
    assert "selected_startup" not in result


@pytest.mark.parametrize(
    "items",
    [
        [],
        [{"company": "wrong", "focus": [], "reason": "unknown"}],
        [{"company": "A", "focus": [], "reason": "x"}] * 2,
        [{"company": "A", "focus": ["x" * 26], "reason": "x"}],
    ],
)
def test_invalid_planner_uses_empty_focus(items):
    _, result, _ = execute(["A"], Planner(items))
    assert result["plan"][0]["focus"] == []
    assert "Planner fallback" in result["last_error"]


def test_planner_failure_does_not_leak_error_body():
    class Broken:
        def generate(self, *args):
            raise RuntimeError("secret-api-key")

    _, result, _ = execute(["A"], Broken())
    assert result["plan"][0]["focus"] == []
    assert "secret" not in result["last_error"]


def test_prepare_failure_is_not_swallowed():
    def broken():
        raise OSError("index unavailable")

    with pytest.raises(OSError):
        orchestrator(
            {"trace_id": "run"},
            discover=lambda _: {
                "candidate_startups": [{"name": "A"}],
                "references": [],
            },
            prepare=broken,
        )


@pytest.mark.parametrize(
    "fixture,count",
    [
        ("empty", 0),
        ("two", 2),
        ("three", 3),
        ("partial_fail", 2),
        ("all_fail", 2),
        ("quality_loop", 2),
    ],
)
@pytest.mark.parametrize("planner_fails", [False, True])
def test_real_b_node_with_a_graph_and_worker_state(fixture, count, planner_fails):
    from src.graph import build_graph
    from src.orchestration.fixtures import fixture_nodes, sample_candidates
    from src.state import create_initial_state

    candidates = sample_candidates(fixture)
    refs = [
        {
            "company": c["name"],
            "agent": "discovery",
            "title": "탐색 출처",
            "source": "web",
            "issuer": "fixture",
            "year": 2026,
            "doc_type": "web",
        }
        for c in candidates
    ]
    planner = Planner(
        []
        if planner_fails
        else [
            {"company": c["name"], "focus": ["임상 검증"], "reason": "출처 제목"}
            for c in candidates
        ]
    )
    events = []
    nodes = fixture_nodes(fixture)
    child_worker = nodes["worker"]

    def real_plan(state):
        return orchestrator(
            state,
            discover=lambda _: {"candidate_startups": candidates, "references": refs},
            generator=planner,
            prepare=lambda: events.append("prepare"),
            log=lambda *a, **kw: None,
        )

    def observe_worker(state, config):
        assert events == ["prepare"]
        assert state["analysis_focus"] == ([] if planner_fails else ["임상 검증"])
        assert len(state["references"]) == 1
        assert state["references"][0]["company"] == state["selected_startup"]["name"]
        return child_worker(state, config)

    nodes.update(orchestrator=real_plan, worker=observe_worker)
    state = create_initial_state("test", 3)
    result = build_graph(nodes=nodes).invoke(
        state,
        {
            "configurable": {"thread_id": state["trace_id"]},
            "max_concurrency": 3,
            "recursion_limit": 24,
        },
    )
    assert len(result["plan"]) == count
    assert len(result["worker_results"]) == count
    assert result["node_status"]["finalize"] == "done"
    assert result["report_attempts"] == (2 if fixture == "quality_loop" else 1)
    assert len([r for r in result["references"] if r["agent"] == "discovery"]) == count
    assert events == (["prepare"] if count else [])


def test_dispatch_without_plan_is_safe():
    assert dispatch({"trace_id": "run"}) == "synthesizer"
