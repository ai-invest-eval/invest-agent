"""A-owned deterministic fake nodes. No web/LLM/RAG or production quality claims.

Fixtures exercise real StateGraph Send, child parallel join and reducers. Page count,
Judge scores and evidence are synthetic. No PDF is produced by fake finalization.
"""

import copy
import hashlib

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from src.config import MAX_WORKER_ATTEMPTS
from src.orchestration.routing import decide_termination
from src.schemas import (
    FinalizeUpdate,
    OrchestratorUpdate,
    QualityEvalUpdate,
    SynthesizerUpdate,
    WorkerUpdate,
)
from src.state import WorkerState

FIXTURE_NAMES = ("empty", "two", "three", "partial_fail", "all_fail", "quality_loop")
QUESTIONS = (
    "QA",
    "QB",
    "QC",
    "QD",
    "QE",
    "QF",
    "QG",
    "QH",
    "QI",
    "QJ",
    "QK",
    "QL",
    "QM",
    "QN",
    "QO",
)


def sample_candidates(name):
    count = 0 if name == "empty" else 3 if name == "three" else 2
    return [
        {
            "name": f"가상 기업 {i + 1}",
            "country": "가상",
            "stage": "Seed",
            "source_url": "https://example.invalid",
        }
        for i in range(count)
    ]


def sample_record(name):
    return {
        "name": name,
        "total": 40.0,
        "area_scores": {
            k: 40.0
            for k in ("founder", "market", "product", "moat", "traction", "deal")
        },
        "question_scores": {q: 2 for q in QUESTIONS},
        "question_evidence": {
            q: {
                "score": 2,
                "rationale": "fixture 가상 근거",
                "references": [],
                "missing": True,
            }
            for q in QUESTIONS
        },
        "verdict": "보류",
        "hold_reason": "fixture 근거 부족",
        "unconfirmed_gates": [],
        "missing_weight": 1.0,
        "rationale": "실제 기업에 대한 판단이 아닌 fixture 결과",
        "startup_profile": {"name": name},
        "tech_analysis": "가상 기술 분석",
        "market_analysis": "가상 시장 분석",
        "competitor_analysis": "가상 경쟁 분석",
    }


def _child_graph():
    def profile(state):
        return {"startup_profile": {"name": state["selected_startup"]["name"]}}

    def tech(state):
        return {
            "tech_analysis": "가상 기술 분석",
            "references": [
                {
                    "company": state["selected_startup"]["name"],
                    "title": "가상 기술 출처",
                    "agent": "tech",
                    "source": "RAG",
                    "doc_type": "report",
                    "issuer": "fixture",
                    "year": 2026,
                }
            ],
        }

    def market(state):
        return {
            "market_analysis": "가상 시장 분석",
            "references": [
                {
                    "company": state["selected_startup"]["name"],
                    "title": "가상 시장 출처",
                    "agent": "market",
                    "source": "RAG",
                    "doc_type": "report",
                    "issuer": "fixture",
                    "year": 2026,
                }
            ],
        }

    def competitor(state):
        if not state.get("tech_analysis") or not state.get("market_analysis"):
            raise ValueError("Both child analyses must arrive before comparison")
        return {"competitor_analysis": "가상 경쟁 분석"}

    def decision(state):
        record = sample_record(state["selected_startup"]["name"])
        return {
            "investment_decision": {
                k: v
                for k, v in record.items()
                if k
                not in (
                    "name",
                    "startup_profile",
                    "tech_analysis",
                    "market_analysis",
                    "competitor_analysis",
                )
            },
            "evaluation_history": [record],
        }

    graph = StateGraph(WorkerState)
    for name, node in {
        "company_profile": profile,
        "tech_analysis": tech,
        "market_analysis": market,
        "competitor_analysis": competitor,
        "investment_decision": decision,
    }.items():
        graph.add_node(name, node)
    graph.add_edge(START, "company_profile")
    graph.add_edge("company_profile", "tech_analysis")
    graph.add_edge("company_profile", "market_analysis")
    graph.add_edge(["tech_analysis", "market_analysis"], "competitor_analysis")
    graph.add_edge("competitor_analysis", "investment_decision")
    graph.add_edge("investment_decision", END)
    return graph.compile(checkpointer=False)


def fixture_nodes(name):
    if name not in FIXTURE_NAMES:
        raise ValueError(f"Unknown fixture: {name}")
    child = _child_graph()

    def orchestrator(state) -> OrchestratorUpdate:
        candidates = sample_candidates(name)[: state["max_candidates"]]
        plan = [
            {
                "task_id": f"{state['trace_id']}:{i}",
                "task_index": i,
                "company": c,
                "focus": ["가상 기술 검증"],
                "discovery_refs": [],
                "max_attempts": MAX_WORKER_ATTEMPTS,
            }
            for i, c in enumerate(candidates)
        ]
        return {
            "candidate_startups": candidates,
            "plan": plan,
            "references": [],
            "step_count": 1,
            "node_status": {"orchestrator": "done"},
        }

    def worker(state: WorkerState, config: RunnableConfig) -> WorkerUpdate:
        task = state["task"]
        fail = name == "all_fail" or (
            name == "partial_fail" and task["task_index"] == 1
        )
        output = None
        for attempt in range(1, task["max_attempts"] + 1):
            # Deliberately fresh reducers every attempt, same scoped discovery references.
            clean = copy.deepcopy(state)
            clean.update(
                startup_profile=None,
                tech_analysis="",
                market_analysis="",
                competitor_analysis="",
                investment_decision=None,
                evaluation_history=[],
            )
            if fail:
                continue
            output = child.invoke(clean, config=config)
            break
        status = "excluded" if fail else "done"
        summary = {
            "task_id": task["task_id"],
            "task_index": task["task_index"],
            "company": task["company"]["name"],
            "status": status,
            "attempts": attempt,
            "duration_ms": 0,
            "error": "fixture injected failure" if fail else None,
        }
        update = {
            "worker_results": [summary],
            "step_count": 1,
            "node_status": {task["task_id"]: status},
        }
        if output is not None:
            update.update(
                evaluation_history=output["evaluation_history"],
                references=output["references"][len(state["references"]) :],
            )
        return update

    def synthesizer(state) -> SynthesizerUpdate:
        expected = len(state["plan"])
        if len(state["worker_results"]) != expected:
            raise ValueError("Fan-in ran before every worker completed")
        results = sorted(state["worker_results"], key=lambda w: w["task_index"])
        lines = [
            "# Fixture 시연 보고서",
            "",
            "## SUMMARY",
            "",
            "실제 투자 평가가 아닌 가상 데이터·가짜 Judge 시연입니다.",
            "",
            "## 평가 결과",
            "",
        ]
        if not results:
            lines.append("후보 0개: 투자 추천 없음.")
        for result in results:
            lines.append(
                f"- {result['company']}: {'보류 — 가상 근거 부족' if result['status'] == 'done' else '평가 제외 — 실패 주입'}"
            )
        lines.extend(
            [
                "",
                "## REFERENCE",
                "",
                "fixture용 가상 출처. 원문 검증·PDF 쪽수 측정 미실행.",
            ]
        )
        md = "\n".join(lines) + "\n"
        return {
            "final_report": md,
            "report_draft": {
                "kind": "empty" if not results else "no_pass",
                "payload": {"fixture": name, "worker_results": results},
                "section_char_limit": 650,
                "reference_map": {},
            },
            "report_pages": 1,
            "report_attempts": state["report_attempts"] + 1,
            "step_count": 1,
            "node_status": {"synthesizer": "done"},
        }

    def quality_eval(state) -> QualityEvalUpdate:
        rewrite = name == "quality_loop" and state["report_attempts"] == 1
        issues = ["fixture: 의도적으로 첫 평가 미달"] if rewrite else []
        verdict = {
            "passed": not rewrite,
            "can_rewrite": rewrite,
            "judge_status": "completed",
            "source_verification": "none",
            "evaluated_body_hash": hashlib.sha256(
                state["final_report"].encode()
            ).hexdigest(),
            "termination_reason": None,
            "rule_checks": {"fixture_contract": True},
            "judge_scores": {
                "groundedness": 2 if rewrite else 5,
                "neutrality": 5,
                "bias": 5,
            },
            "fixable_issues": issues,
            "structural_issues": [],
            "attempt": state["report_attempts"],
        }
        return {
            "eval_result": verdict,
            "eval_feedback": issues,
            "step_count": 1,
            "node_status": {"quality_eval": "fail" if rewrite else "pass"},
        }

    def finalize(state) -> FinalizeUpdate:
        verdict = copy.deepcopy(state["eval_result"])
        verdict["termination_reason"] = decide_termination(state)
        # No real PDF or production-page validation in fixture mode.
        marker = (
            "\n\nFixture 전용 종료: "
            + str(verdict["termination_reason"])
            + ". PDF 미생성.\n"
        )
        return {
            "final_report": state["final_report"] + marker,
            "report_pages": None,
            "eval_result": verdict,
            "step_count": 1,
            "node_status": {"finalize": "done"},
        }

    return {
        "orchestrator": orchestrator,
        "worker": worker,
        "synthesizer": synthesizer,
        "quality_eval": quality_eval,
        "finalize": finalize,
    }
