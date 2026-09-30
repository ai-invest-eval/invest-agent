"""Agent 1 개발용 원본 검색 수집. 후보 추출·자격 검증은 아직 수행하지 않는다."""

import argparse
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from dotenv import load_dotenv

from src.config import PROJECT_ROOT
from src.tools.web_search import TavilySearch, WebSearchError


def build_queries(keyword: str) -> list[str]:
    if not keyword.strip():
        raise ValueError("검색 키워드를 입력하세요.")
    keyword = keyword.strip()
    # 첫 원본 점검은 고정 6개로 시작. LLM 검색어 계획은 다음 탐색 구현에서 연결.
    return [
        f"{keyword} 국내 스타트업 시리즈 투자 유치",
        f"{keyword} 자체 파이프라인 후보물질 바이오 기업",
        f"{keyword} 플랫폼 제약사 공동연구 기업",
        "AI drug discovery startups seed series A series B series C funding",
        "AI drug discovery biotech startups proprietary pipeline clinical",
        "AI drug discovery platform startups pharmaceutical partnerships",
    ]


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
    queries: list[str],
    *,
    max_results: int = 10,
    search_depth: Literal["basic", "advanced"] = "advanced",
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if not queries or any(not query.strip() for query in queries):
        raise ValueError("비어 있지 않은 검색어 목록이 필요합니다.")
    searches: list[dict[str, Any]] = []
    for index, query in enumerate(queries, start=1):
        if progress:
            progress(f"검색 {index}/{len(queries)} 진행 중")
        try:
            response = search.search(
                query, max_results=max_results, search_depth=search_depth
            )
        except WebSearchError as exc:
            searches.append({"query": query, "status": "error", "error": str(exc)})
        else:
            searches.append({"query": query, "status": "ok", "response": response})
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
    parser.add_argument(
        "--query", action="append", help="지정 검색어. 여러 번 사용 가능"
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
        queries = args.query if args.query else build_queries(args.keyword)
        if any(not query.strip() for query in queries):
            raise ValueError("검색어를 입력하세요.")
        search = TavilySearch(os.getenv("TAVILY_API_KEY"), timeout=args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    collection = collect_searches(
        search,
        queries,
        max_results=args.max_results,
        search_depth=args.search_depth,
        progress=lambda message: print(message, flush=True),
    )
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
