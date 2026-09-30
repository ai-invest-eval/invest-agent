"""태우 담당 두 노드의 병렬 실행. extract 모드는 LLM 없이 검색 원문만 확인한다."""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

from src.agents.rag_analysis import (
    AnalysisDraft,
    Citation,
    Claim,
    Query,
    RagAnalysisAgent,
    Relevance,
    SearchPlan,
    Section,
    live_ask,
    live_web_search,
)
from src.config import PROJECT_ROOT
from src.rag.retrieval import HybridRetriever
from src.state import InvestmentState, create_initial_state


def extract_ask(schema, payload):
    """API 없는 배선 점검용. 기업 평가를 생성하지 않고 검색된 원문 발췌만 돌려준다."""
    if schema is SearchPlan:
        text = (
            "AI 모델 실험 검증 신약 규제 IND"
            if payload["agent"] == "tech"
            else "시장 규모 제약사 수요 투자 Exit"
        )
        return SearchPlan(queries=[Query(query=text)])
    if schema is Relevance:
        return Relevance(
            sufficient=False,
            reason="원문 발췌 모드는 LLM 근거 판단을 수행하지 않음",
            gaps=[],
            revised_queries=[],
        )
    sources = [source for source in payload["sources"] if source["kind"] == "RAG"][:3]
    return AnalysisDraft(
        sections=[
            Section(
                title="배선 점검용 원문 발췌 (LLM 분석 아님)",
                claims=[
                    Claim(
                        text="검색된 산업 자료 원문",
                        status="supported",
                        citations=[
                            Citation(source_id=s["source_id"], quote=s["content"][:160])
                        ],
                    )
                    for s in sources
                ],
            )
        ],
        missing_information=[
            "가상 기업 샘플. 이 결과는 기업 평가나 투자 판단 결과가 아닙니다."
        ],
    )


def build_taewoo_graph(*, mode="live"):
    import os

    graph = StateGraph(InvestmentState)
    ask = extract_ask if mode == "extract" else live_ask()
    web = live_web_search if mode == "live" and os.getenv("TAVILY_API_KEY") else None
    for agent, node in [("tech", "tech_analysis"), ("market", "market_analysis")]:
        runner = RagAnalysisAgent(
            agent,
            HybridRetriever(agent).search,
            ask,
            web_search=web if agent == "market" else None,
        )
        graph.add_node(node, runner)
        graph.add_edge(START, node)
        graph.add_edge(node, END)
    return graph.compile()


def main():
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state",
        type=Path,
        default=PROJECT_ROOT / "samples/state_agent3_pipeline.json",
    )
    parser.add_argument("--mode", choices=["live", "extract"], default="live")
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "outputs/taewoo"
    )
    args = parser.parse_args()
    state = create_initial_state("AI 신약개발 스타트업")
    state.update(json.loads(args.state.read_text(encoding="utf-8")))
    result = build_taewoo_graph(mode=args.mode).invoke(
        state, config={"recursion_limit": 10}
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "state.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for key in ["tech_analysis", "market_analysis"]:
        (args.output_dir / f"{key}.md").write_text(result[key] + "\n", encoding="utf-8")
    print("실행 모드:", args.mode, "/ 저장:", args.output_dir)


if __name__ == "__main__":
    main()
