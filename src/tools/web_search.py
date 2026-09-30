"""Tavily 검색 경계. import 시 키 로딩이나 API 호출을 하지 않는다."""

import os
import re
from collections.abc import Sequence
from threading import Lock
from time import monotonic, sleep
from typing import Any, Literal, Protocol


class SearchClient(Protocol):
    def search(self, **kwargs: Any) -> dict[str, Any]: ...


class WebSearchError(RuntimeError):
    """외부 응답·API 키를 노출하지 않는 검색 오류."""


class SearchAccessError(WebSearchError):
    """차단·인증·사용 한도 오류. 추가 요청이나 즉시 재시도로 해결하지 않는다."""


_SEARCH_LOCK = Lock()
_NEXT_SEARCH = 0.0
_BLOCKED = False


def wait_search_turn():
    """같은 프로세스에서 검색 시작을 최소 2초 간격으로 제한한다."""
    global _NEXT_SEARCH
    interval = float(os.getenv("TAVILY_MIN_INTERVAL_SECONDS", "2"))
    if not 0.5 <= interval <= 10:
        raise ValueError("TAVILY_MIN_INTERVAL_SECONDS는 0.5~10이어야 합니다.")
    with _SEARCH_LOCK:
        if _BLOCKED:
            raise SearchAccessError(
                "Tavily 차단·인증·사용 한도 오류로 추가 검색을 중단했습니다."
            )
        delay = _NEXT_SEARCH - monotonic()
        if delay > 0:
            sleep(delay)
        _NEXT_SEARCH = monotonic() + interval


class TavilySearch:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: SearchClient | None = None,
        timeout: int = 30,
    ) -> None:
        if timeout < 1:
            raise ValueError("timeout은 1 이상이어야 합니다.")
        self._pace_requests = client is None
        if client is None:
            if not api_key or not api_key.strip():
                raise ValueError("TAVILY_API_KEY를 설정하세요.")
            from tavily import TavilyClient

            client = TavilyClient(api_key=api_key.strip())
        self._client = client
        self._timeout = timeout

    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        search_depth: Literal["basic", "advanced"] = "advanced",
        include_domains: Sequence[str] | None = None,
        include_raw_content: bool = True,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("검색어를 입력하세요.")
        if not 1 <= max_results <= 20:
            raise ValueError("max_results는 1~20 사이여야 합니다.")
        if search_depth not in ("basic", "advanced"):
            raise ValueError("search_depth는 basic 또는 advanced여야 합니다.")
        domains = list(
            dict.fromkeys(domain.strip().lower() for domain in include_domains or [])
        )
        if any(
            not re.fullmatch(
                r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?",
                domain,
            )
            for domain in domains
        ):
            raise ValueError("include_domains에는 URL이 아닌 도메인을 지정하세요.")
        options: dict[str, Any] = {}
        if domains:
            options = {"include_domains": domains, "include_domains_mode": "restrict"}
        try:
            if self._pace_requests:
                wait_search_turn()
            response = self._client.search(
                query=query.strip(),
                topic="general",
                search_depth=search_depth,
                max_results=max_results,
                include_answer=False,
                include_raw_content="text" if include_raw_content else False,
                include_images=False,
                auto_parameters=False,
                timeout=self._timeout,
                **options,
            )
        except SearchAccessError:
            raise
        except Exception as exc:  # noqa: BLE001 -- 인증정보 노출 방지
            # SDK 예외 본문에 요청·인증 정보가 포함될 수 있으므로 출력하지 않는다.
            if type(exc).__name__ in (
                "ForbiddenError",
                "UsageLimitExceededError",
                "InvalidAPIKeyError",
            ):
                global _BLOCKED
                if self._pace_requests:
                    _BLOCKED = True
                raise SearchAccessError(
                    "Tavily 차단·인증·사용 한도 오류입니다. 대시보드의 한도와 production API 키를 확인하세요. 즉시 재시도하지 않습니다."
                ) from None
            raise WebSearchError(
                "Tavily 검색 실패. 키·연결·사용 한도를 확인하세요."
            ) from None
        if not isinstance(response, dict) or not isinstance(
            response.get("results"), list
        ):
            raise WebSearchError("Tavily 응답 형식이 올바르지 않습니다.")
        return response
