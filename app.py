"""전체 실행 골격 및 개별 에이전트 개발용 진입점."""

import argparse
import json
from importlib import import_module
from pathlib import Path

from src.state import create_initial_state

# 선택한 에이전트만 import하므로 다른 에이전트 구현 없이 개별 실행 가능.
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
    parser = argparse.ArgumentParser(description="투자 평가 프로젝트 실행 골격")
    parser.add_argument("--keyword", default="AI 신약개발 스타트업")
    parser.add_argument("--agent", choices=AGENTS, help="개발 중인 에이전트만 실행")
    parser.add_argument("--state", type=Path, help="개별 실행에 필요한 샘플 State JSON")
    args = parser.parse_args()

    state = create_initial_state(args.keyword)
    if args.state:
        # TODO(각 에이전트 담당): 입력 계약에 맞는 샘플 State JSON 준비
        state.update(json.loads(args.state.read_text(encoding="utf-8")))

    if args.agent:
        module_name, function_name = AGENTS[args.agent]
        node = getattr(import_module(module_name), function_name)
        try:
            update = node(state)
        except NotImplementedError as exc:
            parser.exit(1, f"미구현: {exc}\n")
        print(json.dumps(update, ensure_ascii=False, indent=2))
        return

    # TODO(3-A/3-B 담당): 색인 준비 구현 후 기존 인덱스 재사용 단계 연결
    # from src.rag.build_index import build_indexes
    # build_indexes()
    # TODO(통합 담당): 그래프 구현 후 전체 실행 연결
    # Agent 1은 그래프 안에서 최초 탐색하고, 5 → 1 재진입 시 다음 후보를 선택한다.
    # from src.graph import build_graph
    # result = build_graph().invoke(state)
    # TODO(6번 담당): Markdown 저장·PDF 출력 연결
    print("실행 골격 준비 완료. 개별 개발: --agent 1 / 전체 연결: TODO 구현")


if __name__ == "__main__":
    main()
