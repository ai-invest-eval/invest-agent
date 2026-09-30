"""Agent 6 단독 검증 (가짜 LLM, API 키 불필요).

실행: uv run --with pytest python -m pytest -q tests/test_agent6_report.py
"""

import copy
import json
from pathlib import Path

import pytest

from src.agents import agent6_report as a6
from src.tools.report_format import collect_references

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
BAD = "잘못된 문단: 팀 소항목에 시장 규모가 섞임"


def load(name: str) -> dict:
    return json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def record():
    state = load("report_state")
    return next(r for r in state["evaluation_history"] if r["verdict"] == "통과")


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test")


def draft(tag: str) -> a6.DetailDraft:
    return a6.DetailDraft(
        reasons=[a6.Reason(text="임상 1/2상 진입", area="product")] * 3,
        key_risk="특허 분쟁 여부 미확인",
        **{f"s2_{i}": BAD if i == 5 else f"{tag} 2.{i}" for i in range(1, 8)},
    )


def grades() -> a6.JudgeResult:
    ok = [
        a6.SectionGrade(section=k, faithfulness=5, relevance=5, issues="")
        for k in ["summary", "2.1", "2.2", "2.3", "2.4", "2.6", "2.7"]
    ]
    bad = a6.SectionGrade(section="2.5", faithfulness=2, relevance=2, issues="섞임")
    return a6.JudgeResult(grades=[*ok, bad])


def fake_llm(drafts, judges):
    """호출 순서대로 정해 둔 응답을 돌려준다. None은 호출 실패."""
    drafts, judges = iter(drafts), iter(judges)

    def call(schema, payload, task, limit, system=None):
        return next(drafts) if schema is a6.DetailDraft else next(judges)

    return call


def test_retry_failure_replaces_failed_section(record, monkeypatch):
    monkeypatch.setattr(a6, "_call_llm", fake_llm([draft("초안"), None], [grades()]))
    result, log = a6._write_detail(record)
    assert BAD not in result.s2_5
    assert result.s2_1 == "초안 2.1"
    assert log["replaced"] == ["2.5"]


def test_second_judge_failure_replaces_unverified_retry(record, monkeypatch):
    monkeypatch.setattr(
        a6, "_call_llm", fake_llm([draft("초안"), draft("재작성")], [grades(), None])
    )
    result, log = a6._write_detail(record)
    assert BAD not in result.s2_5 and "재작성" not in result.s2_5
    assert log["replaced"] == ["2.5"]


def test_still_failing_after_retry_is_replaced(record, monkeypatch):
    monkeypatch.setattr(
        a6,
        "_call_llm",
        fake_llm([draft("초안"), draft("재작성")], [grades(), grades()]),
    )
    result, log = a6._write_detail(record)
    assert BAD not in result.s2_5
    assert log["replaced"] == ["2.5"]


def test_references_only_used_sources(record):
    state = load("report_state")
    unused = {
        **state["references"][0],
        "title": "미사용 프로필 뉴스",
        "url": "https://example.invalid/unused",
    }
    item = {
        **unused,
        "title": "선급금 계약 보도자료",
        "url": "https://example.invalid/deal",
    }
    rec = copy.deepcopy(record)
    rec["startup_profile"]["upfront_payment_basis"]["references"] = [item]
    refs = collect_references(rec, [*state["references"], unused])
    titles = [r["title"] for r in refs]
    assert "미사용 프로필 뉴스" not in titles
    assert "선급금 계약 보도자료" in titles


def test_no_pass_report_hides_area_scores(monkeypatch):
    monkeypatch.setattr(a6, "_call_llm", lambda *args, **kwargs: None)
    md = a6.report_writer(load("report_state_no_pass"))["final_report"]
    assert "| 창업자 |" not in md
    assert "**창업자 " not in md
    assert "투자 추천 없음" in md
