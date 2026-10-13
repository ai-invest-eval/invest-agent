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
