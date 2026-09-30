"""Agent 1 개발용 실행 진입점. 공통 그래프와 다른 에이전트 없이 실행한다.

검색 계획 → Tavily 원본 수집 → 원문 기반 후보 추출 순으로 진행한다.
--input으로 기존 원본을 재사용하면 Tavily 검색을 다시 호출하지 않는다.
TODO(에이전트 1): 자격 검증 후 공통 CandidateStartup 계약으로 변환한다.
"""

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv

from collect_candidates import collect_searches, redact_secrets, save_collection
from src.agents.agent1_discovery import (
    DEFAULT_MAX_SEARCH_REQUESTS,
    extract_candidate_leads,
    plan_searches,
    prepare_documents,
)
from src.config import PROJECT_ROOT
from src.tools.structured_llm import GPTStructuredGenerator, StructuredLLMError
from src.tools.web_search import TavilySearch


def load_collection(path: Path) -> dict:
    """검색 실패·잘못된 파일을 후보 0개로 오해하지 않도록 입력을 검사한다."""
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("status") not in ("ok", "partial"):
        raise ValueError("성공 또는 일부 성공한 검색 원본 JSON이 필요합니다.")
    searches = data.get("searches")
    if not isinstance(searches, list):
        raise ValueError("검색 원본에 searches 목록이 없습니다.")  # noqa: TRY004 -- 파일 계약 위반
    for record in searches:
        if not isinstance(record, dict) or record.get("status") not in ("ok", "error"):
            raise ValueError("검색 기록 형식이 올바르지 않습니다.")
        if record["status"] == "ok":
            response = record.get("response")
            if not isinstance(response, dict) or not isinstance(
                response.get("results"), list
            ):
                raise ValueError("검색 결과 목록 형식이 올바르지 않습니다.")
            for result in response["results"]:
                if not isinstance(result, dict) or any(
                    result.get(key) is not None and not isinstance(result[key], str)
                    for key in ("url", "title", "raw_content", "content")
                ):
                    raise ValueError("검색 문서 필드 형식이 올바르지 않습니다.")
        domains = record.get("include_domains") or []
        if not isinstance(domains, list) or any(
            not isinstance(d, str) for d in domains
        ):
            raise ValueError("검색 도메인 목록 형식이 올바르지 않습니다.")
    return data


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="LLM 검색 계획 및 미검증 후보 추출")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--input", type=Path, help="기존 discovery JSON 재사용")
    modes.add_argument("--plan-only", action="store_true", help="검색 계획만 저장")
    parser.add_argument("--keyword", default="AI 신약개발")
    # 검색 횟수와 최종 후보 수는 별도 설정이다. MAX_CANDIDATES는 여기서 사용하지 않는다.
    parser.add_argument(
        "--max-search-requests",
        type=int,
        default=os.getenv(
            "MAX_DISCOVERY_SEARCH_REQUESTS", str(DEFAULT_MAX_SEARCH_REQUESTS)
        ),
    )
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument(
        "--timeout", type=int, default=90, help="모델 호출 제한 시간(초)"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "outputs" / "discovery"
    )
    args = parser.parse_args()
    if (
        args.max_search_requests < 3
        or not 1 <= args.max_results <= 20
        or args.timeout <= 0
    ):
        parser.error(
            "검색 요청 상한은 3 이상, 결과 수는 1~20, timeout은 양수여야 합니다."
        )
    secrets = [os.getenv("OPENAI_API_KEY", ""), os.getenv("TAVILY_API_KEY", "")]

    def save(data, prefix):
        return save_collection(
            redact_secrets(data, secrets), args.output_dir, prefix=prefix
        )

    try:
        # 파일 오류는 모델 호출 전에 확인한다. 재사용 모드에는 Tavily 키가 필요 없다.
        collection = load_collection(args.input) if args.input else None
        generator = GPTStructuredGenerator(secrets[0], timeout=args.timeout)
        if collection is None:
            print("검색 계획 생성 중", flush=True)
            requests = plan_searches(
                generator, args.keyword, max_requests=args.max_search_requests
            )
            plan_path = save(
                {
                    "keyword": args.keyword,
                    "max_search_requests": args.max_search_requests,
                    "requests": [asdict(r) for r in requests],
                },
                "search_plan",
            )
            print(f"검색 계획 {len(requests)}개 저장: {plan_path}", flush=True)
            if args.plan_only:
                return
            collection = collect_searches(
                TavilySearch(secrets[1]),
                requests,
                max_results=args.max_results,
                progress=lambda text: print(text, flush=True),
            )
            # 모델 추출이 실패해도 이미 수집한 원본은 남겨 재검색 비용을 줄인다.
            raw_path = save(collection, "discovery")
            print(f"원본 저장: {raw_path}", flush=True)
            if collection["status"] == "error":
                raise ValueError("전체 검색 실패. 저장 원본을 확인하세요.")
        if not prepare_documents(collection):
            raise ValueError(
                "추출 가능한 본문이 없습니다. 후보 없음으로 해석하지 마세요."
            )
        leads = extract_candidate_leads(
            generator, collection, progress=lambda text: print(text, flush=True)
        )
        # 어떤 수집 원본으로 만든 결과인지 추적한다. 일부 원본으로 실시한
        # 개발 검증은 전체 탐색 결과와 혼동하지 않도록 표시도 이어받는다.
        leads["source_collection"] = str(args.input if args.input else raw_path)
        leads["smoke_test_subset"] = bool(collection.get("smoke_test_subset", False))
        target = save(leads, "candidate_leads")
        print(
            f"완료: 미검증 후보 {leads['lead_count']}개, 근거 검사 제외 {len(leads['rejected_leads'])}건"
        )
        print(f"후보 저장: {target}")
        print("상장·인수·투자 단계 자격 검증 전이며 최종 평가 후보가 아닙니다.")
    except (ValueError, StructuredLLMError) as exc:
        parser.exit(1, f"실행 중단: {redact_secrets(str(exc), secrets)}\n")
    except OSError:
        parser.exit(1, "파일 읽기·저장 실패. 경로와 접근 권한을 확인하세요.\n")


if __name__ == "__main__":
    main()
