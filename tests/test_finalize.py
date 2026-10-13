"""finalize 노드 검증 (가짜 렌더러·가짜 종료 판단·가짜 규칙 검사, API 키 불필요).

실행: uv run --with pytest python -m pytest -q tests/test_finalize.py
"""

import json
import re
from pathlib import Path

import pytest

from src.agents import agent6_report as a6
from src.orchestration import finalize as fz

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def load(name: str) -> dict:
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def verdict(**kw) -> dict:
    base = {
        "passed": False,
        "can_rewrite": False,
        "judge_status": "completed",
        "source_verification": "consistency_only",
        "termination_reason": None,
        "rule_checks": {"format_order": True},
        "judge_scores": {"groundedness": 4, "neutrality": 4, "bias": 4},
        "fixable_issues": [],
        "structural_issues": [],
        "attempt": 1,
    }
    return {**base, **kw}


class FakeRenderer:
    """md 길이와 레이아웃 단계로 쪽수를 정한다. pages_by(md, level) 함수를 넘겨 시나리오를 만든다."""

    def __init__(self, pages_by):
        self.pages_by = pages_by
        self.calls = []

    def __call__(self, md, level):
        self.calls.append((level, len(md)))
        return f"PDF:{level}".encode(), self.pages_by(md, level)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("REPORT_FILE_STEM", "report")
    monkeypatch.setattr(a6, "_call_llm", lambda *a, **k: None)
    monkeypatch.setattr(
        "src.tools.report_exporter.render_pdf", lambda md, level=0: (b"", 3)
    )
    rule_calls = []

    def rules(md, refs, pages):
        rule_calls.append(md)
        return {"format_order": True, "neutral_wording": True}, [], []

    monkeypatch.setattr(fz, "_rule_checks", rules)
    return tmp_path, rule_calls


def build_state(name, ev, termination, monkeypatch, **extra):
    """synthesizer(agent6)로 실제 초안을 만든 State."""
    state = {**load(name), "trace_id": "t1", "report_attempts": 1, **extra}
    state.update(a6.report_writer(state))
    state["eval_result"] = ev
    monkeypatch.setattr(fz, "_decide_termination", lambda s: termination)
    return state


def saved(tmp_path):
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    quality = json.loads((tmp_path / "report_quality.json").read_text(encoding="utf-8"))
    return md, quality


def block_lines(md):
    part = md.split("### 품질 평가 결과", 1)[1].split("<!-- quality-block:end -->")[0]
    return [line[2:] for line in part.strip().splitlines() if line.startswith("- ")]


def test_structural_issue_block_and_unfixable(env, monkeypatch):
    tmp, _ = env
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 4))
    ev = verdict(structural_issues=["reference_count: REFERENCE 2건"])
    state = build_state("report_state", ev, "unfixable", monkeypatch)
    out = fz.finalize(state)
    md, quality = saved(tmp)
    lines = block_lines(md)
    assert len(lines) == 4
    assert lines[0] == "결과: 품질 미달 (종료 사유: unfixable)"
    assert "reference_count" in lines[2]
    assert out["eval_result"]["termination_reason"] == "unfixable"
    assert md.index("### 품질 평가 결과") < md.index("## REFERENCE")
    assert quality["verdict"] == out["eval_result"]


def test_max_attempts_shows_remaining_fixable(env, monkeypatch):
    tmp, _ = env
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 4))
    ev = verdict(
        can_rewrite=True, fixable_issues=["중립성 미달: 과장 표현을 사실 서술로"]
    )
    out = fz.finalize(build_state("report_state", ev, "max_attempts", monkeypatch))
    md, _ = saved(tmp)
    assert "남은 재작성 항목: 중립성 미달" in block_lines(md)[1]
    assert out["eval_result"]["termination_reason"] == "max_attempts"


def test_judge_unavailable_is_incomplete(env, monkeypatch):
    tmp, _ = env
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 4))
    ev = verdict(judge_status="unavailable", judge_scores=None)
    out = fz.finalize(
        build_state("report_state", ev, "evaluation_unavailable", monkeypatch)
    )
    md, _ = saved(tmp)
    assert block_lines(md)[0].startswith("결과: 평가 불완전")
    assert "Judge 미실행" in block_lines(md)[3]
    assert out["eval_result"]["termination_reason"] == "evaluation_unavailable"


def test_long_issues_cut_but_json_keeps_all(env, monkeypatch):
    tmp, _ = env
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 4))
    issues = [f"문제 {i}: " + "아주 긴 설명 " * 20 for i in range(10)]
    ev = verdict(fixable_issues=issues, structural_issues=issues)
    fz.finalize(build_state("report_state", ev, "max_attempts", monkeypatch))
    md, quality = saved(tmp)
    lines = block_lines(md)
    limits = list(fz.BLOCK_LIMITS.values())
    assert all(len(line) <= limit for line, limit in zip(lines, limits))
    assert "외 8건" in lines[1]
    assert len(quality["verdict"]["fixable_issues"]) == 10


def test_layout_only_keeps_body_and_judge(env, monkeypatch):
    tmp, rule_calls = env
    # 레이아웃 0단계 11쪽, 1단계부터 10쪽
    monkeypatch.setattr(
        fz, "_render", FakeRenderer(lambda md, lv: 11 if lv == 0 else 10)
    )
    state = build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    out = fz.finalize(state)
    md, quality = saved(tmp)
    assert out["eval_result"]["passed"] is True
    assert out["eval_result"]["judge_status"] == "completed"
    assert quality["layout_level"] == 1 and quality["char_level"] == a6.char_level_of(
        state["report_draft"]
    )
    assert rule_calls == []  # 본문이 바뀌지 않아 규칙을 다시 검사하지 않음
    # 본문(블록 제외)은 synthesizer 초안 그대로
    assert a6.insert_quality_block(state["final_report"], block_lines(md)) == md


def test_shrink_marks_stale_and_rechecks_rules(env, monkeypatch):
    _, rule_calls = env
    state = build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    calls = {"n": 0}

    def pages(md, level):
        # 처음 본문은 모든 레이아웃 단계에서 11쪽, 축약한 뒤부터 9쪽
        calls["n"] += 1
        return 11 if calls["n"] <= fz._layout_levels() else 9

    monkeypatch.setattr(fz, "_render", FakeRenderer(pages))

    def rules(md, refs, pages):
        rule_calls.append(md)
        return (
            {"format_order": True, "risk_present": False},
            ["리스크 문장 없음"],
            ["reference_count"],
        )

    monkeypatch.setattr(fz, "_rule_checks", rules)
    state["eval_result"]["fixable_issues"] = ["이전 지적: 남으면 안 됨"]
    out = fz.finalize(state)
    v = out["eval_result"]
    assert len(rule_calls) == 1 and "### 품질 평가 결과" not in rule_calls[0]
    assert v["judge_status"] == "stale"
    assert v["passed"] is False
    assert v["termination_reason"] == "evaluation_unavailable"
    # 규칙 관련 필드는 모두 새 검사 결과로 바뀐다
    assert v["fixable_issues"] == ["리스크 문장 없음"]
    assert v["structural_issues"] == ["reference_count"]
    assert v["can_rewrite"] is True
    assert (
        v["rule_checks"]["risk_present"] is False
        and v["rule_checks"]["page_limit"] is True
    )
    assert out["report_pages"] == 9


def test_still_over_limit_after_all_steps(env, monkeypatch):
    _ = env
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 11))
    out = fz.finalize(
        build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    )
    v = out["eval_result"]
    assert v["passed"] is False
    assert "최종 쪽수 초과: 11쪽" in v["structural_issues"]
    assert v["rule_checks"]["page_limit"] is False
    assert v["termination_reason"] == "unfixable"


def test_render_failure_saves_markdown_only(env, monkeypatch):
    tmp, _ = env

    def broken(md, level):
        raise OSError("no pango")

    monkeypatch.setattr(fz, "_render", broken)
    out = fz.finalize(
        build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    )
    assert (tmp / "report.md").exists() and not (tmp / "report.pdf").exists()
    v = out["eval_result"]
    assert out["report_pages"] is None
    assert v["passed"] is False and "최종 쪽수 미확인" in v["structural_issues"]
    assert v["termination_reason"] == "evaluation_unavailable"
    assert "쪽수 미확인" in out["last_error"]


def test_saved_files_match_returned_verdict(env, monkeypatch):
    tmp, _ = env
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 7))
    out = fz.finalize(
        build_state("report_state_no_pass", verdict(), "unfixable", monkeypatch)
    )
    md, quality = saved(tmp)
    assert md == out["final_report"]
    assert (
        block_lines(md)
        == quality["quality_block"]
        == fz.make_quality_block(out["eval_result"], 7)
    )
    assert quality["final_pages"] == out["report_pages"] == 7
    assert (
        tmp / "report.pdf"
    ).read_bytes() == b"PDF:0"  # 저장 PDF는 최종 md를 렌더링한 것
    assert quality["page_count_converged"] is True


def test_page_flip_uses_saved_pdf_pages(env, monkeypatch):
    """블록을 바꿀 때마다 쪽수가 바뀌어도 반복은 끝나고, 저장한 PDF의 쪽수를 최종으로 쓴다."""
    tmp, _ = env
    count = {"n": 0}

    def flip(md, level):
        count["n"] += 1
        return 9 + count["n"] % 2

    monkeypatch.setattr(fz, "_render", FakeRenderer(flip))
    out = fz.finalize(
        build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    )
    md, quality = saved(tmp)
    last_pages = 9 + count["n"] % 2  # 저장한(마지막으로 렌더링한) PDF의 쪽수
    assert out["report_pages"] == quality["final_pages"] == last_pages
    assert quality["page_count_converged"] is False
    assert count["n"] <= 2 + fz.MAX_PAGE_SYNC
    assert re.search(r"최종 \d+쪽", block_lines(md)[3])
    # 저장 Markdown의 블록 = JSON에 기록한 블록, 판정은 미달로 남김
    assert block_lines(md) == quality["quality_block"]
    v = out["eval_result"]
    assert v["passed"] is False and v["termination_reason"] == "unfixable"
    assert any("표기 불일치" in s for s in v["structural_issues"])
    assert block_lines(md)[0].startswith("결과: 품질 미달")  # 블록의 결과도 판정과 같다


def test_render_failure_in_final_step_removes_stale_pdf(env, monkeypatch):
    """최종 재렌더링에서 실패하면 쪽수 미확인으로 바꾸고, 이전 실행의 PDF를 남기지 않는다."""
    tmp, _ = env
    (tmp / "report.pdf").write_bytes(b"old")
    count = {"n": 0}

    def fails_later(md, level):
        count["n"] += 1
        if count["n"] > 1:
            raise OSError("font error")
        return b"PDF", 4

    monkeypatch.setattr(fz, "_render", fails_later)
    out = fz.finalize(
        build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    )
    md, quality = saved(tmp)
    assert not (tmp / "report.pdf").exists()
    assert out["report_pages"] is None and quality["final_pages"] is None
    assert (
        "최종 쪽수 미확인" in block_lines(md)[3] or "쪽수 미확인" in block_lines(md)[3]
    )
    assert block_lines(md) == quality["quality_block"]
    assert out["eval_result"]["termination_reason"] == "evaluation_unavailable"


def test_rule_recheck_failure_does_not_stop_saving(env, monkeypatch):
    tmp, _ = env
    calls = {"n": 0}

    def pages(md, level):
        calls["n"] += 1
        return 11 if calls["n"] <= 4 else 9

    def broken_rules(md, refs, pages):
        raise KeyError("rule")

    monkeypatch.setattr(fz, "_render", FakeRenderer(pages))
    monkeypatch.setattr(fz, "_rule_checks", broken_rules)
    out = fz.finalize(
        build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    )
    assert (tmp / "report.md").exists()
    assert out["eval_result"]["passed"] is False
    assert any("재검사 실패" in s for s in out["eval_result"]["structural_issues"])


def test_passed_only_with_passed_termination(env, monkeypatch):
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 4))
    out = fz.finalize(
        build_state("report_state", verdict(passed=True), "max_steps", monkeypatch)
    )
    assert out["eval_result"]["passed"] is False
    assert out["eval_result"]["termination_reason"] == "max_steps"


def test_unexpected_render_error_still_saves_markdown(env, monkeypatch):
    tmp, _ = env

    def weird(md, level):
        raise ValueError("bad font table")

    monkeypatch.setattr(fz, "_render", weird)
    out = fz.finalize(
        build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    )
    assert (tmp / "report.md").exists()
    assert out["report_pages"] is None
    assert out["eval_result"]["termination_reason"] == "evaluation_unavailable"


def test_empty_body_is_rebuilt_from_draft(env, monkeypatch):
    _ = env
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 4))
    state = build_state("report_state", verdict(passed=True), "passed", monkeypatch)
    state["final_report"] = ""
    out = fz.finalize(state)
    assert "## SUMMARY" in out["final_report"]
    assert out["eval_result"]["passed"] is True


def test_empty_body_without_draft_is_not_passed(env, monkeypatch):
    monkeypatch.setattr(fz, "_render", FakeRenderer(lambda md, lv: 1))
    monkeypatch.setattr(fz, "_decide_termination", lambda s: "passed")
    state = {"trace_id": "t", "final_report": "", "eval_result": verdict(passed=True)}
    out = fz.finalize(state)
    v = out["eval_result"]
    assert v["passed"] is False and v["termination_reason"] == "evaluation_unavailable"
    assert "보고서 본문 없음" in v["structural_issues"]
