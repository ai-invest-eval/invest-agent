"""Tavily 검색 경계. import 시 키 로딩이나 API 호출을 하지 않는다."""

from typing import Any, Literal, Protocol


class SearchClient(Protocol):
    def search(self, **kwargs: Any) -> dict[str, Any]: ...


class WebSearchError(RuntimeError):
    """외부 응답·API 키를 노출하지 않는 검색 오류."""


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
    ) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("검색어를 입력하세요.")
        if not 1 <= max_results <= 20:
            raise ValueError("max_results는 1~20 사이여야 합니다.")
        if search_depth not in ("basic", "advanced"):
            raise ValueError("search_depth는 basic 또는 advanced여야 합니다.")
        try:
            response = self._client.search(
                query=query.strip(),
                topic="general",
                search_depth=search_depth,
                max_results=max_results,
                include_answer=False,
                include_raw_content="text",
                include_images=False,
                auto_parameters=False,
                timeout=self._timeout,
            )
        except Exception:  # noqa: BLE001 -- 외부 SDK 경계에서 인증정보 노출을 차단한다.
            # SDK 예외 본문에 요청·인증 정보가 포함될 수 있으므로 출력하지 않는다.
            raise WebSearchError(
                "Tavily 검색 실패. 키·연결·사용 한도를 확인하세요."
            ) from None
        if not isinstance(response, dict) or not isinstance(
            response.get("results"), list
        ):
            raise WebSearchError("Tavily 응답 형식이 올바르지 않습니다.")
        return response
