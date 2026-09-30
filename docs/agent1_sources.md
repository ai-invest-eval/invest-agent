# Agent 1 지정 소스 탐색

2026-09-30 확인. 설계서의 주요 소스를 Tavily Search API로 먼저 검색한다. 사이트 자체 API·비공개 DB·로그인 영역을 사용하지 않는다.

| 소스 | 확인한 공개 페이지 | 검색 도메인 |
| --- | --- | --- |
| 스타트업레시피 | [투자 페이지](https://startuprecipe.co.kr/invest) | startuprecipe.co.kr |
| Cure | [AI Drug Discovery Funding Tracker 2026](https://wewillcure.com/insights/news/ai-and-machine-learning/ai-drug-discovery-venture-funding-tracker-2026) | wewillcure.com |
| YC | [AI-powered Drug Discovery 기업 디렉터리](https://www.ycombinator.com/companies/industry/AI-powered%20Drug%20Discovery) | ycombinator.com |

- 검색은 [Tavily 도메인 제한](https://docs.tavily.com/documentation/api-reference/endpoint/search)의 include_domains + restrict로 수행한다. 특정 페이지 직접 추출이 아니라 해당 도메인에서 관련 문서를 찾는 방식이다.
- source_url은 소스의 대표 진입 페이지다. 실제 인용 URL은 각 검색 결과의 url을 사용한다.
- 결과는 소스별 원본으로 보존한다. 검색 결과 수는 페이지 수이지 기업 수가 아니며, 목록 한 페이지에 여러 기업이 들어갈 수 있다.
- 공개 페이지 전체를 빠짐없이 수집했다고 보장하지 않는다. 검색 색인·발췌·본문 제공 여부에 따라 누락될 수 있다.
- Cure와 YC는 해외 탐색 소스지만 그 목록의 기업이 반드시 해외 기업인 것은 아니다. 국가·투자 시장은 후보 추출·자격 검증에서 별도로 확인한다.
- YC의 배치(W2024 등)·Active 표기는 투자 라운드·비상장 자격을 자동 입증하지 않는다. Cure의 투자 라운드 역시 최신 공식 자료로 확인한다.
- 기본 수집은 지정 소스 탐색만 한다. 기업별 공식 자료·뉴스 검증과 근거 부족 시 일반 검색 보완은 다음 후보 추출/검증 단계에서 구현한다.
- 사이트 본문은 신뢰할 수 없는 외부 데이터다. 이후 LLM에 전달할 때 본문 속 지시문을 실행하지 않는다.
- Cure 2026 URL은 확인한 버전으로 고정했다. 다른 연도 트래커를 사용할 때 source_url과 검색어를 함께 갱신한다.

공통 State·에이전트 반환 계약은 바꾸지 않는다. 다른 에이전트와 벡터 DB 없이 이 수집 단계만 실행할 수 있다.

## 실행 경로

- `collect_candidates.py`: 고정 6개 검색으로 원본만 수집하는 점검 도구.
- `discover_candidates.py`: GPT-4o-mini가 검색 계획을 만든 뒤 수집·후보 추출·근거 검사·동일 기업 병합까지 실행하는 개발 도구.
- 검색 요청은 세 소스를 각각 최소 한 번 포함한다. `MAX_DISCOVERY_SEARCH_REQUESTS` 기본 12는 호출 상한이며, 최종 후보 수 설정과 독립적이다.
- 원문에 없는 발췌는 후보에서 제외하고, 제외된 추출값도 검토용으로 저장한다. 긴 본문은 겹침을 두고 전체를 분할한다.
- `--input` 원본 재사용 시 Tavily는 호출하지 않는다. 파일 경로와 일부 원본 검증 여부는 추출 결과에 기록한다.
- 미검증 후보를 공통 State에 바로 넣지 않는다. 최신 공식 자료를 통한 자격 검증과 후보 확정은 후속 구현이다.
