"""전체 실행 골격 및 개별 에이전트 개발용 진입점."""

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
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="투자 평가 프로젝트 실행 골격")
    parser.add_argument("--keyword", default="AI 신약개발 스타트업")
    parser.add_argument("--agent", choices=AGENTS, help="개발 중인 에이전트만 실행")
    parser.add_argument("--state", type=Path, help="개별 실행에 필요한 샘플 State JSON")
    parser.add_argument("--max-candidates", type=int, help="최대 후보 수 (기본값: 15)")
    parser.add_argument(
        "--report-only",
        type=Path,
        help="저장된 outputs/run_state.json으로 보고서만 다시 생성",
    )
    args = parser.parse_args()

    # 실행 옵션 > 환경변수(.env 포함) > 기본값. 0은 기본값으로 대체하지 않는다.
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
        # TODO(각 에이전트 담당): 입력 계약에 맞는 샘플 State JSON 준비
        state.update(json.loads(args.state.read_text(encoding="utf-8")))
    # 샘플 State보다 이번 실행에서 지정한 후보 상한을 우선한다.
    state["max_candidates"] = max_candidates
    execution_config = {"recursion_limit": calculate_recursion_limit(max_candidates)}

    if args.report_only:
        # 에이전트를 다시 돌리지 않고 저장된 실행 기록으로 보고서만 다시 만든다.
        from src.agents.agent6_report import report_writer

        saved = json.loads(args.report_only.read_text(encoding="utf-8"))
        state.update(
            {
                "evaluation_history": saved.get("evaluation_history") or [],
                "references": saved.get("references") or [],
            }
        )
        report_writer(state)
        return

    if args.agent:
        module_name, function_name = AGENTS[args.agent]
        node = getattr(import_module(module_name), function_name)
        try:
            update = node(state)
        except NotImplementedError as exc:
            parser.exit(1, f"미구현: {exc}\n")
        except ValueError as exc:
            parser.exit(1, f"실행 중단: {exc}\n")
        except RuntimeError as exc:
            if args.agent != "1":
                raise
            parser.exit(1, f"실행 중단: {exc}\n")
        print(json.dumps(update, ensure_ascii=False, indent=2))
        return

    # 색인 준비: 기존 인덱스가 있으면 재사용한다.
    from src.rag.build_index import build_indexes

    build_indexes()
    # 전체 그래프 실행. 6번 노드가 outputs/에 보고서 Markdown·PDF를 저장한다.
    from src.graph import build_graph

    result = build_graph().invoke(state, config=execution_config)
    history = result.get("evaluation_history") or []
    # 진단용 실행 기록: 질문별 점수·근거·결측 사유와 후보 목록
    out_dir = PROJECT_ROOT / "outputs"
    out_dir.mkdir(exist_ok=True)
    run_state = {
        "candidate_startups": result.get("candidate_startups") or [],
        "evaluation_history": history,
        "references": result.get("references") or [],
    }
    (out_dir / "run_state.json").write_text(
        json.dumps(run_state, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    passed = [r["name"] for r in history if r.get("verdict") == "통과"]
    print(
        f"완료: 후보 {len(history)}곳 평가, 통과 {len(passed)}곳 "
        f"({', '.join(passed) or '없음'}) / 보고서는 outputs/ 폴더"
    )


if __name__ == "__main__":
    main()
