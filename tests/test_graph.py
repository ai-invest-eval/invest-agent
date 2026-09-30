"""실제 그래프의 병렬 합류·후보 반복·보고서 경로를 외부 API 없이 확인한다."""

from unittest.mock import patch

import app
from src.agents.agent1_search import startup_search
from src.graph import NODE_IMPORTS, build_graph
from src.state import create_initial_state


def test_all_candidates_join_before_comparison_and_preserve_history():
    state = create_initial_state("AI 신약개발", max_candidates=2)
    state["candidate_startups"] = [
        {"name": name, "country": None, "stage": "시드", "source_url": None}
        for name in ("Alpha", "Beta")
    ]
    state["references"] = [{"company": "Alpha", "agent": "discovery"}]
    observed = []

    def profile(current):
        name = current["selected_startup"]["name"]
        observed.append(("profile", name))
        return {"startup_profile": {"name": name}, "references": []}

    def tech(current):
        name = current["startup_profile"]["name"]
        observed.append(("tech", name))
        return {
            "tech_analysis": f"{name} 기술 근거",
            "references": [{"company": name, "agent": "tech"}],
        }

    def market(current):
        name = current["startup_profile"]["name"]
        observed.append(("market", name))
        return {
            "market_analysis": f"{name} 시장 근거",
            "references": [{"company": name, "agent": "market"}],
        }

    def competitor(current):
        name = current["startup_profile"]["name"]
        assert current["tech_analysis"] == f"{name} 기술 근거"
        assert current["market_analysis"] == f"{name} 시장 근거"
        observed.append(("competitor", name))
        return {"competitor_analysis": f"{name} 경쟁 근거", "references": []}

    def decision(current):
        name = current["selected_startup"]["name"]
        assert current["competitor_analysis"] == f"{name} 경쟁 근거"
        observed.append(("decision", name))
        return {
            "investment_decision": {"name": name},
            "evaluation_history": [{"name": name}],
        }

    def report(current):
        observed.append(("report", len(current["evaluation_history"])))
        return {"final_report": "최종 보고서"}

    nodes = dict(
        zip(
            NODE_IMPORTS,
            (startup_search, profile, tech, market, competitor, decision, report),
            strict=True,
        )
    )
    with patch("src.agents.agent1_search.GPTStructuredGenerator") as generator:
        result = build_graph(nodes).invoke(state, {"recursion_limit": 30})
    generator.assert_not_called()
    assert [row["name"] for row in result["evaluation_history"]] == ["Alpha", "Beta"]
    assert result["selected_startup"]["name"] == "Beta"
    assert result["final_report"] == "최종 보고서"
    assert len(result["references"]) == 5
    assert [item for item in observed if item[0] == "report"] == [("report", 2)]
    for name in ("Alpha", "Beta"):
        position = observed.index(("competitor", name))
        assert ("tech", name) in observed[:position]
        assert ("market", name) in observed[:position]


def test_empty_search_still_writes_report():
    nodes = {name: lambda current: {} for name in NODE_IMPORTS}
    nodes["startup_search"] = lambda current: {
        "candidate_startups": [],
        "selected_startup": None,
        "references": [],
    }
    nodes["report_writer"] = lambda current: {"final_report": "투자 추천 없음"}
    result = build_graph(nodes).invoke(
        create_initial_state("AI 신약개발"), {"recursion_limit": 10}
    )
    assert result["final_report"] == "투자 추천 없음"
    assert result["evaluation_history"] == []


def test_cli_existing_history_generates_markdown_without_rag_or_api(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("REPORT_USE_LLM", "0")
    monkeypatch.setenv("REPORT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setattr(
        "sys.argv", ["app.py", "--state", "samples/report_state_no_pass.json"]
    )
    with patch("src.rag.build_index.build_indexes") as build_indexes:
        app.main()
    build_indexes.assert_not_called()
    report = tmp_path / "investment_report.md"
    assert report.exists()
    assert "투자 추천 없음" in report.read_text(encoding="utf-8")
    assert "전체 실행 완료: 평가 3곳" in capsys.readouterr().out
