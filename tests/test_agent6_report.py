"""Agent 6 단독 검증 (가짜 LLM, API 키 불필요).

실행: uv run --with pytest python -m pytest -q tests/test_agent6_report.py
"""

import copy
import json
from pathlib import Path

import pytest

from src.agents import agent6_report as a6
from src.tools.report_format import collect_references, rank_records

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
    monkeypatch.delenv("REPORT_INTERNAL_JUDGE", raising=False)


@pytest.fixture
def judge_on(monkeypatch):
    """내장 Judge 경로 검증용. 그래프에서는 quality_eval이 품질 루프를 맡아 기본값은 꺼져 있다."""
    monkeypatch.setenv("REPORT_INTERNAL_JUDGE", "1")


@pytest.fixture
def fake_pdf(monkeypatch):
    """PDF 렌더링 대신 쪽수만 돌려준다. 호출된 (char/layout 단계)를 기록한다."""
    calls = []

    def render(md, level=0):
        calls.append(level)
        return b"%PDF", 3

    monkeypatch.setattr("src.tools.report_exporter.render_pdf", render)
    return calls


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


def test_retry_failure_replaces_failed_section(record, monkeypatch, judge_on):
    monkeypatch.setattr(a6, "_call_llm", fake_llm([draft("초안"), None], [grades()]))
    result, log = a6._write_detail(record)
    assert BAD not in result.s2_5
    assert result.s2_1 == "초안 2.1"
    assert log["replaced"] == ["2.5"]


def test_second_judge_failure_replaces_unverified_retry(record, monkeypatch, judge_on):
    monkeypatch.setattr(
        a6, "_call_llm", fake_llm([draft("초안"), draft("재작성")], [grades(), None])
    )
    result, log = a6._write_detail(record)
    assert BAD not in result.s2_5 and "재작성" not in result.s2_5
    assert log["replaced"] == ["2.5"]


def test_still_failing_after_retry_is_replaced(record, monkeypatch, judge_on):
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


def test_no_pass_report_hides_area_scores(monkeypatch, fake_pdf):
    monkeypatch.setattr(a6, "_call_llm", lambda *args, **kwargs: None)
    md = a6.report_writer(load("report_state_no_pass"))["final_report"]
    assert "| 창업자 |" not in md
    assert "**창업자 " not in md
    assert "투자 추천 없음" in md


# ---------------------------------------------------------------- synthesizer (Orchestrator-Workers)


def planned(state: dict, order: list[str]) -> dict:
    """plan·worker_results에 task_index를 붙인 State."""
    state = copy.deepcopy(state)
    state["plan"] = [
        {"task_index": i, "company": {"name": name}} for i, name in enumerate(order)
    ]
    state["worker_results"] = [
        {"task_index": i, "company": name, "status": "done"}
        for i, name in enumerate(order)
    ]
    return state


def no_llm(monkeypatch):
    monkeypatch.setattr(a6, "_call_llm", lambda *args, **kwargs: None)


def test_internal_judge_off_by_default(record, monkeypatch):
    judged = []
    monkeypatch.setattr(a6, "_judge", lambda *args: judged.append(1))
    monkeypatch.setattr(a6, "_call_llm", fake_llm([draft("초안")], []))
    result, log = a6._write_detail(record)
    assert judged == []
    assert result.s2_5 == BAD  # 품질 판정은 그래프의 quality_eval이 맡는다
    assert log["rounds"] == []


def test_feedback_reaches_llm_task_in_both_paths(monkeypatch, fake_pdf):
    tasks = []
    monkeypatch.setattr(
        a6, "_call_llm", lambda schema, payload, task, *a, **k: tasks.append(task)
    )
    feedback = ["Groundedness 미달: 2.3 시장 규모 수치 근거 없음"]
    for name in ("report_state", "report_state_no_pass"):
        a6.report_writer({**load(name), "eval_feedback": feedback})
    # 통과 보고서 1회 + 무추천 보고서(요약 1회 + 상위 후보 상세 검토 HELD_DETAIL_COUNT회)
    no_pass_records = len(load("report_state_no_pass")["evaluation_history"])
    assert len(tasks) == 2 + min(a6.HELD_DETAIL_COUNT, no_pass_records)
    assert all("2.3 시장 규모 수치 근거 없음" in t for t in tasks)
    assert all("지적된 부분만 고쳐라" in t for t in tasks)


def test_synthesizer_returns_draft_without_saving(tmp_path, monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    update = a6.report_writer({**load("report_state"), "report_attempts": 1})
    assert set(update) >= {
        "final_report",
        "report_pages",
        "report_draft",
        "report_attempts",
        "step_count",
        "node_status",
    }
    assert update["report_pages"] == 3
    assert update["report_attempts"] == 2
    assert update["report_draft"]["kind"] == "pass"
    assert list(tmp_path.iterdir()) == []  # 최종 저장은 finalize


def test_rebuild_markdown_matches_without_llm(monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    state = load("report_state")
    update = a6.report_writer(state)
    draft = update["report_draft"]
    monkeypatch.setattr(
        a6, "_call_llm", lambda *a, **k: pytest.fail("rebuild는 LLM을 부르지 않는다")
    )
    assert (
        a6.rebuild_markdown(state, draft, a6.char_level_of(draft))
        == update["final_report"]
    )
    shorter = a6.rebuild_markdown(state, draft, 3)
    assert len(shorter) < len(update["final_report"])  # 문단만 짧아지고
    assert "## REFERENCE" in shorter and "| 순위 |" in shorter  # 표·출처는 유지


def test_same_markdown_regardless_of_worker_order(monkeypatch, fake_pdf):
    """Worker 완료 순서(evaluation_history·references 순서)가 달라도 보고서와 출처 번호가 같다."""
    no_llm(monkeypatch)
    for name in ("report_state", "report_state_no_pass"):
        base = load(name)
        order = [r["name"] for r in base["evaluation_history"]]
        first = planned(base, order)
        shuffled = planned(base, order)
        shuffled["evaluation_history"].reverse()
        shuffled["references"].reverse()
        md1 = a6.report_writer(first)["final_report"]
        md2 = a6.report_writer(shuffled)["final_report"]
        assert md1 == md2


def test_excluded_company_listed_under_ranking(monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    state = load("report_state_no_pass")
    state["worker_results"] = [
        {
            "task_index": 9,
            "company": "실패 기업",
            "status": "excluded",
            "attempts": 2,
            "error": "RuntimeError: forced failure for demo",
        }
    ]
    md = a6.report_writer(state)["final_report"]
    line = "평가 제외: 실패 기업(RuntimeError: forced failure for demo)"
    assert line in md
    assert md.index("### 1.2") < md.index(line) < md.index("### 1.3")


def test_all_excluded_empty_report_explains(monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    state = {
        "input_keyword": "AI",
        "evaluation_history": [],
        "references": [],
        "worker_results": [
            {"task_index": 0, "company": "A사", "status": "excluded", "error": "X"},
        ],
    }
    md = a6.report_writer(state)["final_report"]
    assert "모두 평가 중 실패해 제외" in md
    assert "평가 제외: A사(X)" in md
    assert md.rstrip().splitlines()[-1] != ""  # REFERENCE까지 정상 조립


def test_render_failure_gives_unknown_pages(monkeypatch):
    no_llm(monkeypatch)

    def broken(md, level=0):
        raise OSError("no pango")

    monkeypatch.setattr("src.tools.report_exporter.render_pdf", broken)
    update = a6.report_writer(load("report_state"))
    assert update["report_pages"] is None
    assert "쪽수 미확인" in update["last_error"]
    assert "## SUMMARY" in update["final_report"]


def test_page_overflow_feedback_starts_shorter(monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    update = a6.report_writer(
        {**load("report_state"), "eval_feedback": ["쪽수 초과: 12쪽 → 축약"]}
    )
    assert fake_pdf[0] == 1
    assert update["report_draft"]["section_char_limit"] == a6.SECTION_CHAR_LIMITS[1]


def test_quality_block_inserted_once_before_reference():
    md = "## SUMMARY\n\n결론\n\n## 2. 상세\n\n본문\n\n## REFERENCE\n\n1. 출처"
    once = a6.insert_quality_block(md, ["결과: 통과", "남은 재작성 항목: 없음"])
    twice = a6.insert_quality_block(once, ["결과: 품질 미달", "남은 재작성 항목: 1건"])
    assert twice.count("### 품질 평가 결과") == 1
    assert "결과: 품질 미달" in twice and "결과: 통과" not in twice
    assert twice.index("### 품질 평가 결과") < twice.index("## REFERENCE")
    headings = [line for line in twice.splitlines() if line.startswith("## ")]
    assert headings[-1] == "## REFERENCE"


def test_excluded_reason_is_html_escaped(monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    state = load("report_state_no_pass")
    state["worker_results"] = [
        {
            "task_index": 0,
            "company": "A&B",
            "status": "excluded",
            "error": "<urlopen error>",
        },
        {"task_index": 1, "company": "C사", "status": "excluded", "error": "Timeout"},
    ]
    md = a6.report_writer(state)["final_report"]
    assert "평가 제외: A&amp;B(&lt;urlopen error&gt;)<br>" in md
    assert "<urlopen" not in md


def test_none_task_index_and_missing_fields_do_not_crash(monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    state = load("report_state_no_pass")
    state["plan"] = [{"task_index": None, "company": {"name": "가상 랩스 E"}}]
    state["worker_results"] = [{"task_index": None, "status": "excluded"}]
    state["references"][0]["authors"] = [None, "홍길동"]
    md = a6.report_writer(state)["final_report"]
    assert "평가 제외: 회사명 미상(사유 미상)" in md


def test_report_draft_follows_shared_contract(monkeypatch, fake_pdf):
    """schemas.ReportDraft: kind, payload, section_char_limit, reference_map."""
    no_llm(monkeypatch)
    draft = a6.report_writer(load("report_state"))["report_draft"]
    assert set(draft) == {"kind", "payload", "section_char_limit", "reference_map"}
    assert draft["payload"]["reasons"]
    # REFERENCE 번호는 묶음 이름과 함께: 보고서의 번호 체계와 같다
    assert all(" " in key for key in draft["reference_map"])
    assert draft["reference_map"]


# ---------------------------------------------------------------- 무추천 보고서 3장: 상위 후보 상세 검토


def test_no_pass_report_adds_held_detail_chapter(monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    state = load("report_state_no_pass")
    update = a6.report_writer(state)
    md = update["final_report"]
    ranked = [r["name"] for _, _, r in rank_records(state["evaluation_history"])]
    expected = ranked[: a6.HELD_DETAIL_COUNT]
    assert "## 3. 상위 후보 상세 검토 (보류)" in md
    assert "투자 추천이 아니다" in md
    for i, name in enumerate(expected, 1):
        assert f"### 3.{i} {name}" in md
        assert f"#### 3.{i}.7 보류 사유와 리스크" in md
    # 통과 0곳 보고서 계약: 영역별 점수는 표시하지 않는다
    assert "**창업자 " not in md
    # 3장은 REFERENCE 앞, SUMMARY·REFERENCE 순서 유지
    assert md.index("## 3. 상위 후보") < md.index("## REFERENCE")
    details = update["report_draft"]["payload"]["details"]
    assert [d["company"] for d in details] == expected


def test_held_detail_llm_input_has_no_scores(monkeypatch, fake_pdf):
    payloads = []

    def fake(schema, payload, task, *a, **k):
        payloads.append((schema, payload, task))
        return None

    monkeypatch.setattr(a6, "_call_llm", fake)
    a6.report_writer(load("report_state_no_pass"))
    held = [(p, t) for schema, p, t in payloads if schema is a6.HeldSections]
    assert held, "상위 후보 상세 검토 LLM 호출이 있어야 한다"
    for payload, task in held:
        assert "area_scores" not in payload and "total" not in payload
        for data in payload["sections"].values():
            for item in (data.get("questions") or {}).values():
                assert "score" not in (item or {})
        assert "추천하거나" in task


def test_rebuild_reads_old_no_pass_draft_without_details(monkeypatch, fake_pdf):
    no_llm(monkeypatch)
    state = load("report_state_no_pass")
    draft = a6.report_writer(state)["report_draft"]
    old = {**draft, "payload": {k: v for k, v in draft["payload"].items() if k != "details"}}
    md = a6.rebuild_markdown(state, old, 0)
    assert "## 3. 상위 후보 상세 검토" not in md
    assert "## REFERENCE" in md
