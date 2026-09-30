"""Agent 1 개발용 원본 검색 수집. 후보 추출·자격 검증은 아직 수행하지 않는다."""

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from dotenv import load_dotenv

from src.agents.agent1_sources import DiscoverySearchRequest, build_search_requests
from src.config import PROJECT_ROOT
from src.tools.web_search import TavilySearch, WebSearchError


def build_queries(keyword: str) -> list[str]:
    """기존 호출용 검색어 목록. 실제 수집은 도메인 포함 검색 계획을 사용한다."""
    return [request.query for request in build_search_requests(keyword)]


def redact_secrets(value: Any, secrets: list[str]) -> Any:
    """원본 응답은 보존하되 인증 필드·키의 우발적 포함은 제거한다."""
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if key.casefold() in ("api_key", "authorization", "access_token")
                else redact_secrets(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
    return value


def collect_searches(
    search: TavilySearch,
    queries: list[str | DiscoverySearchRequest],
    *,
    max_results: int = 10,
    search_depth: Literal["basic", "advanced"] = "advanced",
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    requests = [
        DiscoverySearchRequest(query=item) if isinstance(item, str) else item
        for item in queries
    ]
    if not requests or any(not request.query.strip() for request in requests):
        raise ValueError("비어 있지 않은 검색어 목록이 필요합니다.")
    searches: list[dict[str, Any]] = []
    for index, request in enumerate(requests, start=1):
        if progress:
            progress(f"검색 {index}/{len(requests)} [{request.source_key}] 진행 중")
        record = asdict(request)
        try:
            response = search.search(
                request.query,
                max_results=max_results,
                search_depth=search_depth,
                include_domains=request.include_domains or None,
            )
        except WebSearchError as exc:
            searches.append({**record, "status": "error", "error": str(exc)})
        else:
            searches.append({**record, "status": "ok", "response": response})
    successes = sum(item["status"] == "ok" for item in searches)
    return {
        "collected_at": datetime.now(UTC).isoformat(),
        "status": (
            "ok" if successes == len(searches) else "partial" if successes else "error"
        ),
        "search_depth": search_depth,
        "max_results_per_query": max_results,
        "successful_queries": successes,
        "failed_queries": len(searches) - successes,
        "result_count": sum(
            len(item["response"]["results"])
            for item in searches
            if item["status"] == "ok"
        ),
        "searches": searches,
    }


def save_collection(collection: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"discovery_{stamp}_{uuid4().hex[:8]}.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(collection, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return target


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Tavily 후보 탐색 원본 수집")
    parser.add_argument("--keyword", default="AI 신약개발")
    parser.add_argument("--english-keyword", default="AI drug discovery")
    parser.add_argument(
        "--query", action="append", help="지정 검색어. 여러 번 사용 가능"
    )
    parser.add_argument(
        "--include-domain",
        action="append",
        help="--query에 적용할 도메인. 여러 번 지정 가능",
    )
    parser.add_argument("--max-results", type=int, default=10)
    parser.add_argument(
        "--search-depth", choices=("basic", "advanced"), default="advanced"
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "outputs" / "discovery"
    )
    args = parser.parse_args()
    if not 1 <= args.max_results <= 20:
        parser.error("--max-results는 1~20 사이여야 합니다.")
    try:
        if args.include_domain and not args.query:
            raise ValueError("--include-domain은 --query와 함께 사용하세요.")
        queries = (
            [
                DiscoverySearchRequest(
                    query=query, include_domains=tuple(args.include_domain or [])
                )
                for query in args.query
            ]
            if args.query
            else build_search_requests(args.keyword, args.english_keyword)
        )
        if any(not request.query.strip() for request in queries):
            raise ValueError("검색어를 입력하세요.")
        search = TavilySearch(os.getenv("TAVILY_API_KEY"), timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        collection = collect_searches(
            search,
            queries,
            max_results=args.max_results,
            search_depth=args.search_depth,
            progress=lambda message: print(message, flush=True),
        )
    except ValueError as exc:
        parser.error(str(exc))
    collection = redact_secrets(
        collection,
        [os.getenv("TAVILY_API_KEY", ""), os.getenv("OPENAI_API_KEY", "")],
    )
    target = save_collection(collection, args.output_dir)
    print(
        f"완료: 성공 {collection['successful_queries']}, 실패 {collection['failed_queries']}, "
        f"검색 결과 {collection['result_count']}건 (중복 포함·미검증)"
    )
    print(f"원본 저장: {target}")
    if collection["status"] == "error":
        parser.exit(1, "전체 검색 실패. 후보 없음으로 해석하지 마세요.\n")


if __name__ == "__main__":
    main()
