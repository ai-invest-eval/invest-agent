"""finalize 노드: 품질 평가 결과를 보고서에 반영하고 Markdown·PDF·품질 JSON을 최종 저장한다.

품질 루프의 모든 종료 경로(통과·재작성 불가·평가 불가·작성 상한·step 상한)가 이 노드를 거쳐 END로 간다.

원칙
- 새 LLM 문장을 만들지 않는다. 본문을 다시 만들 때도 synthesizer가 저장한 구조화 초안(report_draft)만 쓴다.
- 쪽수 조정은 레이아웃(글자 크기 단계) 먼저, 본문 축약(문단 길이 단계)은 그다음이다.
- 본문 문장이 바뀌면 Judge 결과를 유지하지 않는다(judge_status="stale"). 규칙 검사는 새 본문으로 다시 하고
  rule_checks·fixable_issues·structural_issues·can_rewrite를 모두 새 결과로 바꾼다(이전 지적이 남지 않게).
- 저장하는 Markdown과 PDF는 같은 최종 Markdown에서 만들고, 품질 결과 블록·반환값·품질 JSON의 쪽수와
  판정은 실제로 저장한 PDF의 쪽수를 기준으로 맞춘다.
"""

import copy
import hashlib
import json
import os
from pathlib import Path

from src.config import (
    MAX_FINAL_RENDER_PASSES,
    MAX_REPORT_PAGES,
    PROJECT_ROOT,
    QUALITY_ITEM_MAX_CHARS,
)
from src.schemas import FinalizeUpdate
from src.state import InvestmentState

PAGE_LIMIT = MAX_REPORT_PAGES  # 과제 기준 최대 10장 (agent6 내부 목표 MAX_PAGES와 별개)
# 품질 결과 블록: 4개 항목 × 항목별 글자 수 상한. 넘는 부분은 "…"로 자르고 전체 목록은 품질 JSON에 남긴다.
BLOCK_LIMITS = {
    key: min(limit, QUALITY_ITEM_MAX_CHARS)
    for key, limit in {
        "result": 60,
        "fixable": 80,
        "structural": 80,
        "condition": 60,
    }.items()
}
# 블록 갱신 ↔ 재렌더링 반복 상한 (쪽수가 계속 바뀌어도 반드시 끝난다)
MAX_PAGE_SYNC = MAX_FINAL_RENDER_PASSES

JUDGE_TEXT = {
    "completed": "Judge 완료",
    "unavailable": "Judge 미실행",
    "stale": "Judge 축약 전 평가",
}
SOURCE_TEXT = {
    "excerpt": "원문 발췌 검증",
    "consistency_only": "분석 근거 일관성만",
    "mixed": "원문 발췌+분석 근거",
    "none": "근거 없음",
}


# ---------------------------------------------------------------- 외부 모듈 연결
# 다른 담당자의 모듈은 호출 시점에 import한다(순환 import 방지, 테스트에서 교체 가능).


def _decide_termination(state: dict) -> str | None:
    from src.orchestration.routing import decide_termination

    return decide_termination(state)


def _rule_checks(md: str, references: list, pages: int | None):
    """quality_eval의 규칙 검사 재사용. 반환: (rule_checks, fixable_issues, structural_issues)."""
    from src.orchestration.quality_eval import rule_checks

    return rule_checks(md, references, pages)


def _render(md: str, layout_level: int) -> tuple[bytes, int]:
    from src.tools.report_exporter import render_pdf

    return render_pdf(md, layout_level)


def _layout_levels() -> int:
    """레이아웃 단계 수 = report_exporter의 글자 크기 단계 수 (본문 불변)."""
    from src.tools.report_exporter import FONT_LEVELS

    return len(FONT_LEVELS)


def _log(trace_id: str | None, decision: str, reason: str, **extra) -> None:
    try:
        from src.orchestration.observability import log_decision
    except ImportError:
        return
    log_decision(trace_id or "", "finalize", decision, reason, **extra)


# ---------------------------------------------------------------- 품질 결과 블록


def _cut(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _summarize(items: list[str], limit: int) -> str:
    """앞 2개 + "외 N건". 없으면 "없음"."""
    if not items:
        return "없음"
    extra = f" 외 {len(items) - 2}건" if len(items) > 2 else ""
    head = " / ".join(items[:2])
    return _cut(head, max(10, limit - len(extra))) + extra


def result_label(verdict: dict) -> str:
    if verdict.get("passed"):
        return "통과"
    if verdict.get("termination_reason") == "evaluation_unavailable":
        return "평가 불완전"
    return "품질 미달"  # unfixable · max_attempts · max_steps


def make_quality_block(verdict: dict, pages: int | None) -> list[str]:
    """보고서에 넣을 품질 결과 4개 항목. 항목마다 글자 수 상한을 지킨다."""
    reason = verdict.get("termination_reason") or "미정"
    page_text = f"최종 {pages}쪽" if pages is not None else "쪽수 미확인"
    judge = JUDGE_TEXT.get(verdict.get("judge_status"), "Judge 미실행")
    source = SOURCE_TEXT.get(verdict.get("source_verification"), "근거 없음")
    lines = {
        "result": f"결과: {result_label(verdict)} (종료 사유: {reason})",
        "fixable": "남은 재작성 항목: "
        + _summarize(verdict.get("fixable_issues") or [], BLOCK_LIMITS["fixable"] - 11),
        "structural": "구조적 미달: "
        + _summarize(
            verdict.get("structural_issues") or [], BLOCK_LIMITS["structural"] - 8
        ),
        "condition": f"평가 조건: {judge} · {source} · {page_text}",
    }
    return [_cut(text, BLOCK_LIMITS[key]) for key, text in lines.items()]


# ---------------------------------------------------------------- 판정


def _default_verdict(state: dict) -> dict:
    """quality_eval 결과가 없을 때(평가 노드 장애·stub)의 기본값: 평가하지 못한 상태."""
    return {
        "passed": False,
        "can_rewrite": False,
        "judge_status": "unavailable",
        "source_verification": "none",
        "termination_reason": None,
        "rule_checks": {},
        "judge_scores": None,
        "fixable_issues": [],
        "structural_issues": [],
        "attempt": state.get("report_attempts") or 0,
    }


def _apply_pages(
    verdict: dict, termination: str, pages: int | None, stale: bool
) -> dict:
    """최종 쪽수·축약 여부로 판정을 확정한다. 입력 verdict는 바꾸지 않는다."""
    v = copy.deepcopy(verdict)
    v["structural_issues"] = [
        s for s in v.get("structural_issues") or [] if not s.startswith("최종 쪽수")
    ]
    v["rule_checks"] = {
        **(v.get("rule_checks") or {}),
        "page_limit": pages is not None and pages <= PAGE_LIMIT,
    }
    v["termination_reason"] = termination
    # 통과는 종료 사유가 passed일 때만 (예: 통과 판정이어도 step 상한으로 끝났으면 통과로 표시하지 않음)
    v["passed"] = bool(v.get("passed")) and termination == "passed"
    if pages is None:
        v["passed"] = False
        v["structural_issues"].append("최종 쪽수 미확인")
        v["termination_reason"] = "evaluation_unavailable"
    elif pages > PAGE_LIMIT:
        v["passed"] = False
        v["structural_issues"].append(f"최종 쪽수 초과: {pages}쪽")
        v["termination_reason"] = "unfixable"
    if stale:
        # Judge는 축약 전 본문을 평가했으므로 최종 본문의 통과를 보장하지 못한다
        v["judge_status"] = "stale"
        v["passed"] = False
    if v["termination_reason"] == "passed" and not v["passed"]:
        # 초안은 통과했지만 최종 단계에서 통과를 확인하지 못한 경우: 평가 불가(축약) / 규칙 미달
        v["termination_reason"] = "evaluation_unavailable" if stale else "unfixable"
    return v


def _recheck_rules(verdict: dict, md: str, references: list, pages: int | None) -> dict:
    """본문이 바뀐 뒤 규칙을 다시 검사하고, 규칙 관련 필드를 모두 새 결과로 바꾼다.

    Judge 지적은 축약 전 본문에 대한 것이라 남기지 않는다(judge_status는 stale로 표시).
    """
    v = copy.deepcopy(verdict)
    try:
        checks, fixable, structural = _rule_checks(md, references, pages)
    except Exception as exc:  # noqa: BLE001 — 재검사 실패로 최종 저장까지 멈추지 않는다
        v["passed"] = False
        v["structural_issues"] = [
            *(v.get("structural_issues") or []),
            f"축약 후 규칙 재검사 실패: {type(exc).__name__}",
        ]
        return v
    v["rule_checks"] = dict(checks)
    v["fixable_issues"] = list(fixable)
    v["structural_issues"] = list(structural)
    v["can_rewrite"] = bool(fixable)
    v["passed"] = bool(v.get("passed")) and all(checks.values())
    return v


# ---------------------------------------------------------------- 렌더링


def _fit_layout(md: str):
    """레이아웃 단계(글자 크기)를 올려 10쪽 이내를 찾는다. 본문은 바뀌지 않는다.

    반환: (pdf_bytes, pages, layout_level). 렌더링 불가면 (None, None, 0).
    """
    pdf, pages, level = None, None, 0
    for level in range(_layout_levels()):
        pdf, pages = _render(md, level)
        if pages <= PAGE_LIMIT:
            break
    return pdf, pages, level


# ---------------------------------------------------------------- 노드


def _body_hash(md: str) -> str:
    return hashlib.sha256(md.encode()).hexdigest()


def finalize(state: InvestmentState) -> FinalizeUpdate:
    """처리 순서 ①~⑧ (설계안 1부 5장)."""
    from src.agents.agent6_report import (
        SECTION_CHAR_LIMITS,
        char_level_of,
        insert_quality_block,
        rebuild_markdown,
    )
    from src.tools.report_exporter import save_outputs

    trace_id = state.get("trace_id")
    references = state.get("references") or []
    report_draft = state.get("report_draft") or {}
    char_level = char_level_of(report_draft)

    # ①② 종료 사유 결정 (분기 함수와 같은 판정)
    base = copy.deepcopy(state.get("eval_result") or _default_verdict(state))
    # finalize는 종료가 결정된 뒤에만 실행된다. None(재작성 대상)이 오면 작성을 멈춘 것으로 기록한다.
    # routing은 eval_result가 dict여야 하므로 품질 평가 결과가 없을 때도 기본 판정을 넘긴다.
    termination = _decide_termination({**state, "eval_result": base}) or "max_attempts"
    base["termination_reason"] = termination

    # ③ 품질 결과 블록 삽입 (초안 쪽수로 1차 작성, ⑦에서 최종 쪽수로 갱신)
    body = state.get("final_report") or ""
    if not body.strip() and report_draft:
        body = rebuild_markdown(
            state, report_draft, char_level
        )  # 초안 본문이 비면 구조화 초안으로 복원
    if not body.strip():
        # 보고서 본문이 없으면 통과로 저장하지 않는다
        base["passed"] = False
        base["structural_issues"] = [
            *(base.get("structural_issues") or []),
            "보고서 본문 없음",
        ]
        termination = base["termination_reason"] = "evaluation_unavailable"
    md = insert_quality_block(body, make_quality_block(base, state.get("report_pages")))

    # ④ 레이아웃 조정 → ⑤ 본문 축약 → ⑥⑦ 판정 확정·블록 교체·재렌더링
    # 렌더링이 어느 단계에서 실패해도 Markdown은 저장하고 쪽수 미확인으로 처리한다.
    # Judge가 평가한 본문(evaluated_body_hash)과 지금 본문이 다르면 처음부터 stale
    evaluated = base.get("evaluated_body_hash")
    stale = bool(evaluated) and evaluated != _body_hash(body)
    render_error, converged = None, True
    pdf, pages, layout = None, None, 0
    try:
        pdf, pages, layout = _fit_layout(md)
        while (
            pages > PAGE_LIMIT
            and report_draft
            and char_level < len(SECTION_CHAR_LIMITS) - 1
        ):
            char_level += 1
            body = rebuild_markdown(state, report_draft, char_level)
            stale = (
                True  # 본문이 바뀐 시점부터 Judge 결과는 최종 본문을 대표하지 못한다
            )
            md = insert_quality_block(body, make_quality_block(base, pages))
            pdf, pages, layout = _fit_layout(md)
    except Exception as exc:  # noqa: BLE001 — 렌더링·재조립 오류가 나도 Markdown은 저장한다
        pdf, pages, layout = None, None, 0
        render_error = f"{type(exc).__name__}: {exc}"

    if stale:
        # 본문이 바뀌었으므로 규칙을 새 본문(블록 제외)으로 다시 검사한다
        base = _recheck_rules(base, body, references, pages)

    # 확정한 판정으로 블록을 교체하고 같은 레이아웃으로 다시 렌더링한다.
    # 쪽수가 바뀌면 다시 확정한다. 상한까지 계속 바뀌면 마지막으로 저장한 PDF의 쪽수를 최종으로 쓴다.
    verdict = _apply_pages(base, termination, pages, stale)
    block = make_quality_block(verdict, pages)
    saved_block = block  # 저장할 Markdown에 실제로 들어간 블록
    for _ in range(MAX_PAGE_SYNC):
        md = insert_quality_block(body, block)
        saved_block = block
        if pages is None:
            break
        try:
            pdf, new_pages = _render(md, layout)
        except Exception as exc:  # noqa: BLE001
            render_error = f"{type(exc).__name__}: {exc}"
            pdf, pages = None, None
            verdict = _apply_pages(base, termination, pages, stale)
            block = saved_block = make_quality_block(verdict, pages)
            md = insert_quality_block(body, block)
            break
        if new_pages == pages:
            break
        pages = new_pages
        verdict = _apply_pages(base, termination, pages, stale)
        block = make_quality_block(verdict, pages)
    else:
        # 블록을 바꿀 때마다 쪽수가 계속 바뀐 경우: 미달로 확정한 판정으로 블록을 한 번 더 넣고
        # 마지막으로 렌더링한 PDF의 실제 쪽수를 최종으로 쓴다(더 반복하지 않음).
        converged = False
        verdict["passed"] = False
        verdict["structural_issues"].append("최종 쪽수 표기 불일치: 저장 PDF 쪽수 기준")
        if verdict["termination_reason"] == "passed":
            verdict["termination_reason"] = "unfixable"
        block = saved_block = make_quality_block(verdict, pages)
        md = insert_quality_block(body, block)
        try:
            pdf, pages = _render(md, layout)
        except Exception as exc:  # noqa: BLE001
            render_error = f"{type(exc).__name__}: {exc}"
            pdf, pages = None, None
        verdict["rule_checks"]["page_limit"] = pages is not None and pages <= PAGE_LIMIT

    # ⑧ 최종 저장 (Markdown·PDF는 같은 md에서 만든 것)
    out_dir = Path(os.getenv("REPORT_OUTPUT_DIR", PROJECT_ROOT / "outputs"))
    stem = os.getenv("REPORT_FILE_STEM", "investment_report")
    update: dict = {}
    try:
        if pdf is None:
            # 이전 실행의 PDF가 남아 있으면 최신 보고서로 오인할 수 있으므로 지운다
            (out_dir / f"{stem}.pdf").unlink(missing_ok=True)
        paths = save_outputs(md, pdf, out_dir, stem)
        quality = {
            "trace_id": trace_id,
            "final_pages": pages,
            "page_count_converged": converged,
            "layout_level": layout,
            "char_level": char_level,
            "verdict": verdict,
            "quality_block": saved_block,  # 저장한 Markdown에 실제로 들어간 블록
            "paths": paths,
        }
        (out_dir / f"{stem}_quality.json").write_text(
            json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        update["last_error"] = f"finalize: 저장 실패 ({type(exc).__name__}: {exc})"
    if render_error and "last_error" not in update:
        update["last_error"] = (
            f"finalize: PDF 렌더링 실패로 쪽수 미확인 ({render_error})"
        )

    _log(
        trace_id,
        verdict["termination_reason"],
        f"{result_label(verdict)} · 최종 {pages if pages is not None else '?'}쪽",
        final_pages=pages,
        layout_level=layout,
        char_level=char_level,
        judge_status=verdict.get("judge_status"),
    )
    return {
        "final_report": md,
        "report_pages": pages,
        "eval_result": verdict,
        "step_count": 1,
        "node_status": {"finalize": "done"},
        **update,
    }
