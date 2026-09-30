"""전체 투자 평가 및 개별 에이전트 실행 진입점."""

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


def prepare_indexes() -> None:
    """문서/설정이 같으면 기존 색인을 재사용한다. 개별 실행에는 필요 없다."""
    from src.rag.build_index import build_indexes

    build_indexes()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="AI 신약개발 스타트업 투자 평가")
    parser.add_argument("--keyword", default="AI 신약개발 스타트업")
    parser.add_argument("--agent", choices=AGENTS, help="개발 중인 에이전트만 실행")
    parser.add_argument("--state", type=Path, help="개별 실행에 필요한 샘플 State JSON")
    parser.add_argument("--max-candidates", type=int, help="최대 후보 수 (기본값: 15)")
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

    from src.graph import build_graph

    try:
        result = build_graph(prepare_indexes=prepare_indexes).invoke(
            state, config=execution_config
        )
    except ImportError:
        parser.exit(1, "실행 의존성을 설치하세요: uv sync --extra rag\n")
    except (ValueError, RuntimeError, OSError) as exc:
        parser.exit(1, f"전체 실행 중단: {exc}\n")
    # 보고서 Markdown/PDF 저장은 6번이 담당한다. 앱은 최종 State만 별도로 보존한다.
    output = PROJECT_ROOT / "outputs" / "pipeline_state.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"전체 평가 완료: {len(result.get('evaluation_history', []))}개 기업 / State: {output}"
    )


if __name__ == "__main__":
    main()
