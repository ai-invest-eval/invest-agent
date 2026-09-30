"""개별 에이전트 실행과 전체 투자 평가 그래프의 CLI 진입점."""

import argparse
import json
import os
from importlib import import_module
from pathlib import Path

from dotenv import load_dotenv

from src.config import (
    DEFAULT_MAX_CANDIDATES,
    PROJECT_ROOT,
    calculate_recursion_limit,
)
from src.state import create_initial_state

# 선택한 에이전트만 import하므로 담당 노드를 독립 실행할 수 있다.
AGENTS = {
    "1": ("src.agents.agent1_search", "startup_search"),
    "2": ("src.agents.agent2_profile", "company_profile"),
    "3a": ("src.agents.agent3a_tech", "tech_analysis"),
    "3b": ("src.agents.agent3b_market", "market_analysis"),
    "4": ("src.agents.agent4_competitor", "competitor_analysis"),
    "5": ("src.agents.agent5_decision", "investment_decision"),
    "6": ("src.agents.agent6_report", "report_writer"),
}


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="AI 신약개발 스타트업 투자 평가")
    parser.add_argument("--keyword", default="AI 신약개발 스타트업")
    parser.add_argument("--agent", choices=AGENTS, help="지정한 에이전트만 실행")
    parser.add_argument("--state", type=Path, help="공통 State 형식의 입력 JSON")
    parser.add_argument("--max-candidates", type=int, help="최대 후보 수 (기본값: 15)")
    args = parser.parse_args()

    # 실행 옵션 > 환경변수(.env 포함) > 기본값.
    try:
        max_candidates = (
            args.max_candidates
            if args.max_candidates is not None
            else int(os.getenv("MAX_CANDIDATES", str(DEFAULT_MAX_CANDIDATES)))
        )
        state = create_initial_state(args.keyword, max_candidates=max_candidates)
    except ValueError as exc:
        parser.error(str(exc))
    if args.state:
        state.update(json.loads(args.state.read_text(encoding="utf-8")))
    state["max_candidates"] = max_candidates

    if args.agent:
        module_name, function_name = AGENTS[args.agent]
        node = getattr(import_module(module_name), function_name)
        try:
            update = node(state)
        except ValueError as exc:
            parser.exit(1, f"실행 중단: {exc}\n")
        except RuntimeError as exc:
            if args.agent != "1":
                raise
            parser.exit(1, f"실행 중단: {exc}\n")
        print(json.dumps(update, ensure_ascii=False, indent=2))
        return

    # 이미 모든 후보의 평가 이력이 있는 State는 보고서만 생성할 수 있다.
    # 새 후보를 분석할 실행에서만 대용량 PDF 색인을 준비한다.
    from src.agents.agent1_search import select_next_candidate
    from src.graph import build_graph

    history = state.get("evaluation_history") or []
    candidates = state.get("candidate_startups") or []
    if not history or select_next_candidate(candidates, history) is not None:
        from src.rag.build_index import build_indexes

        build_indexes()
    result = build_graph().invoke(
        state, config={"recursion_limit": calculate_recursion_limit(max_candidates)}
    )
    print(
        f"전체 실행 완료: 평가 {len(result.get('evaluation_history') or [])}곳, "
        f"보고서 {'생성' if result.get('final_report') else '미생성'}"
    )


if __name__ == "__main__":
    main()
