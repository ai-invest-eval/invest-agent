"""Parent control state and company-scoped payloads (v3.2)."""

import operator
from typing import Annotated, Required, TypedDict
from uuid import uuid4

from src.config import DEFAULT_MAX_CANDIDATES
from src.schemas import (
    CandidateStartup,
    EvaluationRecord,
    EvalVerdict,
    InvestmentDecision,
    Reference,
    ReportDraft,
    StartupProfile,
    SubTask,
    WorkerResult,
)


def merge_dict(a: dict, b: dict) -> dict:
    """Workers use distinct task IDs; serial node statuses may replace earlier values."""
    return {**(a or {}), **(b or {})}


class InvestmentState(TypedDict, total=False):
    # Input: user request and finite candidate bound.
    input_keyword: Required[str]
    max_candidates: Required[int]
    # Working: no company-specific singleton payloads in the parallel parent.
    candidate_startups: list[CandidateStartup]
    plan: list[SubTask]
    evaluation_history: Annotated[list[EvaluationRecord], operator.add]
    references: Annotated[list[Reference], operator.add]
    worker_results: Annotated[list[WorkerResult], operator.add]
    final_report: str
    report_draft: ReportDraft | None
    report_pages: int | None
    # Eval: replace each round; do not accumulate old feedback.
    eval_result: EvalVerdict | None
    eval_feedback: list[str]
    # Loop: trace correlation, bounded counters and task completion summaries.
    trace_id: str
    step_count: Annotated[int, operator.add]
    node_status: Annotated[dict[str, str], merge_dict]
    report_attempts: int
    # Serial nodes only. Worker errors belong to worker_results[].error.
    last_error: str | None


class WorkerState(TypedDict, total=False):
    task: SubTask
    trace_id: str
    analysis_focus: list[str]
    selected_startup: CandidateStartup | None
    startup_profile: StartupProfile | None
    tech_analysis: str
    market_analysis: str
    competitor_analysis: str
    investment_decision: InvestmentDecision | None
    evaluation_history: Annotated[list[EvaluationRecord], operator.add]
    references: Annotated[list[Reference], operator.add]


def create_initial_state(
    input_keyword: str, max_candidates: int = DEFAULT_MAX_CANDIDATES
) -> InvestmentState:
    if not input_keyword.strip():
        raise ValueError("검색 키워드를 입력하세요.")
    if max_candidates < 1:
        raise ValueError("최대 후보 수는 1 이상이어야 합니다.")
    return {
        "input_keyword": input_keyword.strip(),
        "max_candidates": max_candidates,
        "candidate_startups": [],
        "plan": [],
        "evaluation_history": [],
        "references": [],
        "worker_results": [],
        "final_report": "",
        "report_draft": None,
        "report_pages": None,
        "eval_result": None,
        "eval_feedback": [],
        "trace_id": uuid4().hex,
        "step_count": 0,
        "node_status": {},
        "report_attempts": 0,
        "last_error": None,
    }
