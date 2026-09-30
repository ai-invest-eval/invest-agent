"""Agent 1 지정 소스 검색 계획. 후보 분류·자격 검증은 별도 단계다."""

from dataclasses import dataclass

STARTUP_RECIPE_URL = "https://startuprecipe.co.kr/invest"
CURE_TRACKER_URL = (
    "https://wewillcure.com/insights/news/ai-and-machine-learning/"
    "ai-drug-discovery-venture-funding-tracker-2026"
)
YC_DIRECTORY_URL = (
    "https://www.ycombinator.com/companies/industry/AI-powered%20Drug%20Discovery"
)


@dataclass(frozen=True)
class DiscoverySearchRequest:
    query: str
    source_key: str = "custom"
    source_url: str | None = None
    # 검색 소스 범위일 뿐 기업 국가·투자 시장을 뜻하지 않는다.
    source_scope: str = "general"
    include_domains: tuple[str, ...] = ()


def build_search_requests(
    keyword: str, english_keyword: str = "AI drug discovery"
) -> list[DiscoverySearchRequest]:
    if not keyword.strip() or not english_keyword.strip():
        raise ValueError("국내·해외 검색 키워드를 입력하세요.")
    keyword, english_keyword = keyword.strip(), english_keyword.strip()
    domestic = [
        f"{keyword} 투자 유치 시리즈 스타트업",
        f"{keyword} 후보물질 파이프라인 바이오 기업",
        f"{keyword} 플랫폼 제약사 공동연구 투자",
    ]
    return [
        *[
            DiscoverySearchRequest(
                query=query,
                source_key="startup_recipe",
                source_url=STARTUP_RECIPE_URL,
                source_scope="domestic_source",
                include_domains=("startuprecipe.co.kr",),
            )
            for query in domestic
        ],
        DiscoverySearchRequest(
            query=f"Cure {english_keyword} venture funding tracker 2026 Series Seed A B C",
            source_key="cure",
            source_url=CURE_TRACKER_URL,
            source_scope="global_source",
            include_domains=("wewillcure.com",),
        ),
        DiscoverySearchRequest(
            query=f"{english_keyword} companies startups funding",
            source_key="yc",
            source_url=YC_DIRECTORY_URL,
            source_scope="global_source",
            include_domains=("ycombinator.com",),
        ),
        DiscoverySearchRequest(
            query=f"{english_keyword} platform biotech therapeutics companies",
            source_key="yc",
            source_url=YC_DIRECTORY_URL,
            source_scope="global_source",
            include_domains=("ycombinator.com",),
        ),
    ]
