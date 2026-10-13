"""A gate ordering, all termination reasons, and no mutation."""

import copy

import pytest

from src.config import MAX_REPORT_ATTEMPTS, max_steps
from src.orchestration.routing import decide_termination, route_after_eval
from src.state import create_initial_state


def ready(**changes):
    state = create_initial_state("test", 3)
    state.update(
        report_attempts=1,
        report_pages=1,
        eval_result={
            "passed": False,
            "can_rewrite": False,
            "judge_status": "completed",
        },
    )
    state.update(changes)
    return state


@pytest.mark.parametrize(
    "passed,rewrite,judge,pages,attempts,reason",
    [
        (True, False, "completed", 1, 1, "passed"),
        (False, False, "completed", 1, 1, "unfixable"),
        (False, False, "unavailable", 1, 1, "evaluation_unavailable"),
        (False, False, "completed", None, 1, "evaluation_unavailable"),
        (False, True, "unavailable", None, 1, None),
        (False, True, "completed", 1, MAX_REPORT_ATTEMPTS, "max_attempts"),
    ],
)
def test_termination_order(passed, rewrite, judge, pages, attempts, reason):
    state = ready(
        report_pages=pages,
        report_attempts=attempts,
        eval_result={"passed": passed, "can_rewrite": rewrite, "judge_status": judge},
    )
    original = copy.deepcopy(state)
    assert decide_termination(state) == reason
    assert route_after_eval(state) == ("synthesizer" if reason is None else "finalize")
    assert state == original


def test_step_bound_has_priority():
    state = ready(
        step_count=max_steps(3),
        eval_result={"passed": True, "can_rewrite": False, "judge_status": "completed"},
    )
    assert decide_termination(state) == "max_steps"


def test_missing_verdict_is_contract_error():
    with pytest.raises(TypeError, match="eval_result"):
        decide_termination(create_initial_state("test"))
